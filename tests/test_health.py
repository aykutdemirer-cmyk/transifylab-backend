def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["docs"] == "/docs"


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["transcription_backend"] == "faster_whisper"
    assert set(body["features"]) == {
        "pdf_to_word",
        "docx_to_pdf",
        "text_to_pdf",
        "faster_whisper",
        "openai_whisper",
        "diarization",
    }


def test_cors_headers(client):
    r = client.get("/api/v1/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
