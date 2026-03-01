from __future__ import annotations

import time
from pathlib import Path

import httpx

from auto_reels.config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID

BASE_URL = "https://api.ai33.pro"


def generate_speech(text: str, output_path: Path) -> Path | None:
    """Convert text to speech via ai33.pro TTS API and save as MP3."""
    if not ELEVENLABS_API_KEY:
        return None

    # 1. Submit TTS task
    url = f"{BASE_URL}/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    params = {"output_format": "mp3_44100_128"}
    headers = {
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY,
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
    }

    try:
        resp = httpx.post(url, params=params, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            print(f"    [DEBUG] TTS submit failed: {data}")
            return None

        task_id = data["task_id"]
        print(f"    [DEBUG] TTS task_id: {task_id}")

    except Exception as e:
        print(f"    [DEBUG] TTS submit exception: {e}")
        return None

    # 2. Poll for result
    audio_url = _poll_task(task_id, headers)
    if not audio_url:
        return None

    # 3. Download audio
    try:
        audio_resp = httpx.get(audio_url, timeout=60)
        audio_resp.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_resp.content)
        return output_path
    except Exception as e:
        print(f"    [DEBUG] Audio download exception: {e}")
        return None


def _poll_task(task_id: str, headers: dict, max_wait: int = 120) -> str | None:
    """Poll GET /v1/task/{task_id} until done. Returns audio_url or None."""
    url = f"{BASE_URL}/v1/task/{task_id}"
    elapsed = 0
    interval = 3

    while elapsed < max_wait:
        try:
            resp = httpx.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status")
            if status == "done":
                audio_url = data.get("metadata", {}).get("audio_url")
                if audio_url:
                    return audio_url
                print(f"    [DEBUG] Task done but no audio_url: {data}")
                return None

            if status in ("failed", "error"):
                print(f"    [DEBUG] Task failed: {data.get('error_message')}")
                return None

            # Still processing
            time.sleep(interval)
            elapsed += interval

        except Exception as e:
            print(f"    [DEBUG] Poll exception: {e}")
            time.sleep(interval)
            elapsed += interval

    print(f"    [DEBUG] Polling timeout after {max_wait}s")
    return None
