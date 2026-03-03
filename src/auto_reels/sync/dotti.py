from __future__ import annotations

from pathlib import Path

import httpx

from auto_reels.config import DOTTI_SYNC_URL


def generate_sync(audio_path: Path, output_path: Path) -> Path | None:
    """Send audio to Dotti Sync webhook and save the sync text."""
    if not DOTTI_SYNC_URL:
        print("    [DEBUG] DOTTI_SYNC_URL não configurada")
        return None

    if not audio_path.exists():
        print(f"    [DEBUG] Arquivo de áudio não encontrado: {audio_path}")
        return None

    url = DOTTI_SYNC_URL.rstrip("/")
    mime = _mime_type(audio_path)

    try:
        with audio_path.open("rb") as f:
            resp = httpx.post(
                url,
                files={"file": (audio_path.name, f, mime)},
                timeout=120,
            )
        resp.raise_for_status()
        output_path.write_text(resp.text, encoding="utf-8")
        return output_path
    except Exception as e:
        print(f"    [DEBUG] Dotti Sync error: {e}")
        return None


def _mime_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".aac": "audio/aac",
        ".webm": "audio/webm",
    }.get(ext, "audio/mpeg")
