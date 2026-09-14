"""Upload validation + streaming save with an enforced size cap."""
from __future__ import annotations

from pathlib import Path

import aiofiles
from fastapi import HTTPException, UploadFile, status

from app.config import get_settings

_CHUNK = 1024 * 1024  # 1 MiB


def _ext(filename: str | None) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def validate_extension(upload: UploadFile, allowed: set[str], *, label: str) -> str:
    ext = _ext(upload.filename)
    if ext not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported {label} file '.{ext or '?'}'. "
                f"Allowed: {', '.join('.' + e for e in sorted(allowed))}"
            ),
        )
    return ext


async def save_upload(upload: UploadFile, dest: Path) -> int:
    """Stream ``upload`` to ``dest``; abort with 413 past the configured cap."""
    limit = get_settings().max_upload_size_bytes
    written = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(dest, "wb") as out:
        while chunk := await upload.read(_CHUNK):
            written += len(chunk)
            if written > limit:
                await out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"File exceeds the {get_settings().max_upload_size_mb} MB limit."
                    ),
                )
            await out.write(chunk)
    await upload.close()
    if written == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty."
        )
    return written


class MaxBodySizeMiddleware:
    """Reject requests whose Content-Length already exceeds the cap (fast path)."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            cl = headers.get(b"content-length")
            if cl is not None:
                try:
                    if int(cl) > self.max_bytes:
                        await _send_413(send, self.max_bytes)
                        return
                except ValueError:
                    pass
        await self.app(scope, receive, send)


async def _send_413(send, max_bytes: int) -> None:
    mb = max_bytes // (1024 * 1024)
    body = f'{{"detail":"Request body exceeds the {mb} MB limit."}}'.encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
