"""Audio pre-processing.

Some formats (raw GSM 06.10, AMR, 3GP) are not reliably ingested by the Whisper
backends and are rejected outright by the OpenAI API. For those we transcode to
16 kHz mono PCM WAV using PyAV (``av``), which bundles ffmpeg — no separate
ffmpeg binary is required. Formats Whisper already handles are passed through
untouched.

While transcoding we also run a light filter chain (high-pass + EBU R128
loudness normalisation by default) so quiet narrowband phone recordings are
loud enough for the VAD and the model to work on.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("app.transcription.audio")

# Extensions we transcode before handing to a transcription backend.
NEEDS_TRANSCODE = {"gsm", "amr", "awb", "3gp", "3gpp"}

# Raw/headerless formats need an explicit demuxer hint for av.open().
_FORMAT_HINT = {"gsm": "gsm", "amr": "amr", "awb": "amr", "3gp": "3gp", "3gpp": "3gp"}

# Full set the endpoint accepts = natively-handled + the ones we transcode.
NATIVE_EXT = {"mp3", "wav", "m4a", "ogg", "flac", "webm", "mp4", "mpeg", "mpga"}
ACCEPTED_EXT = NATIVE_EXT | NEEDS_TRANSCODE

_TARGET_FORMAT = "sample_fmts=s16:channel_layouts=mono:sample_rates=16000"


class AudioDecodeError(RuntimeError):
    """The uploaded audio could not be decoded / converted."""


def needs_transcode(ext: str) -> bool:
    return ext.lower().lstrip(".") in NEEDS_TRANSCODE


def _build_graph(av, first_frame, chain: str):
    """abuffer -> <chain> -> aformat(16k/mono/s16) -> abuffersink."""
    graph = av.filter.Graph()
    src = graph.add_abuffer(
        sample_rate=first_frame.sample_rate,
        format=first_frame.format.name,
        layout=first_frame.layout.name,
        time_base=getattr(first_frame, "time_base", None) or None,
    )
    node = src
    for step in (s.strip() for s in chain.split(",") if s.strip()):
        name, _, args = step.partition("=")
        nxt = graph.add(name, args or None)
        node.link_to(nxt)
        node = nxt
    fmt = graph.add("aformat", _TARGET_FORMAT)
    node.link_to(fmt)
    sink = graph.add("abuffersink")
    fmt.link_to(sink)
    graph.configure()
    return graph


def _drain(graph, out_stream, out_container) -> None:
    while True:
        try:
            fr = graph.pull()
        except (BlockingIOError, EOFError):
            return
        except Exception:  # noqa: BLE001 - av raises av.AVError subclasses
            return
        fr.pts = None
        for pkt in out_stream.encode(fr):
            out_container.mux(pkt)


def transcode_to_wav(src: Path, dst: Path) -> Path:
    """Decode + filter ``src`` and write 16 kHz mono s16 WAV to ``dst``."""
    try:
        import av  # bundled with faster-whisper; also a light standalone install
    except ImportError as exc:  # pragma: no cover - depends on env
        raise AudioDecodeError(
            "Bu ses formatını dönüştürmek için 'av' (PyAV) gerekli. "
            "Kurulum: pip install av"
        ) from exc

    chain = get_settings().audio_filter_chain.strip()
    hint = _FORMAT_HINT.get(src.suffix.lower().lstrip("."))
    try:
        in_container = av.open(str(src), format=hint) if hint else av.open(str(src))
    except Exception as exc:  # noqa: BLE001 - av raises broad errors
        raise AudioDecodeError(f"Ses dosyası açılamadı: {exc}") from exc

    try:
        in_stream = next(
            (s for s in in_container.streams if s.type == "audio"), None
        )
        if in_stream is None:
            raise AudioDecodeError("Dosyada ses akışı bulunamadı.")

        out_container = av.open(str(dst), mode="w", format="wav")
        try:
            out_stream = out_container.add_stream(
                "pcm_s16le", rate=16000, layout="mono"
            )
        except TypeError:  # older PyAV without the layout kwarg
            out_stream = out_container.add_stream("pcm_s16le", rate=16000)
            out_stream.layout = "mono"

        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        graph = None

        def _mux_resampled(frame) -> None:
            resampled = resampler.resample(frame)
            for rf in resampled if isinstance(resampled, list) else [resampled]:
                if rf is not None:
                    for pkt in out_stream.encode(rf):
                        out_container.mux(pkt)

        for frame in in_container.decode(in_stream):
            frame.pts = None
            if chain and graph is None:
                try:
                    graph = _build_graph(av, frame, chain)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "audio filter chain %r disabled (%s); using plain resample",
                        chain, exc,
                    )
                    graph = False  # sentinel: don't retry
            if graph:
                graph.push(frame)
                _drain(graph, out_stream, out_container)
            else:
                _mux_resampled(frame)

        if graph:
            graph.push(None)
            _drain(graph, out_stream, out_container)
        for pkt in out_stream.encode(None):  # flush encoder
            out_container.mux(pkt)
        out_container.close()
    except AudioDecodeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AudioDecodeError(f"Ses dönüştürme başarısız: {exc}") from exc
    finally:
        in_container.close()

    if not dst.exists() or dst.stat().st_size == 0:
        raise AudioDecodeError("Ses dönüştürme çıktı üretmedi.")
    return dst
