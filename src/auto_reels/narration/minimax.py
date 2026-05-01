from __future__ import annotations

import time
from pathlib import Path

import httpx

from auto_reels.config import AI33_API_KEY, MINIMAX_VOICE_ID, MINIMAX_MODEL

BASE_URL = "https://api.ai33.pro"
KEY_RETRY_WAIT = 15

_keys = [k.strip() for k in AI33_API_KEY.split(",") if k.strip()]


def generate_speech(text: str, output_path: Path) -> Path | None:
    """Convert text to speech via ai33.pro MiniMax TTS and save as MP3."""
    if not _keys:
        return None

    for i, key in enumerate(_keys):
        if i > 0:
            print(f"    [DEBUG] Aguardando {KEY_RETRY_WAIT}s antes de tentar próxima key...")
            time.sleep(KEY_RETRY_WAIT)
        result = _try_generate(key, text, output_path)
        if result:
            return result
        print(f"    [DEBUG] Key ...{key[-4:]} falhou, tentando próxima ({i + 1}/{len(_keys)})")

    print(f"    [DEBUG] Todas as {len(_keys)} key(s) falharam")
    return None


def _try_generate(key: str, text: str, output_path: Path) -> Path | None:
    headers = {
        "Content-Type": "application/json",
        "xi-api-key": key,
    }
    payload = {
        "text": text,
        "model": MINIMAX_MODEL,
        "voice_setting": {
            "voice_id": MINIMAX_VOICE_ID,
            "vol": 1,
            "pitch": 0,
            "speed": 1,
        },
        "language_boost": "Auto",
    }

    try:
        resp = httpx.post(f"{BASE_URL}/v1m/task/text-to-speech", headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            print(f"    [DEBUG] MiniMax submit failed (key ...{key[-4:]}): {data}")
            return None

        task_id = data["task_id"]
        print(f"    [DEBUG] MiniMax task_id: {task_id} (key ...{key[-4:]})")

    except Exception as e:
        print(f"    [DEBUG] MiniMax submit exception (key ...{key[-4:]}): {e}")
        return None

    audio_url = _poll_task(task_id, headers)
    if not audio_url:
        return None

    try:
        audio_resp = httpx.get(audio_url, timeout=60)
        audio_resp.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_resp.content)
        return output_path
    except Exception as e:
        print(f"    [DEBUG] MiniMax audio download exception: {e}")
        return None


def _poll_task(task_id: str, headers: dict, max_wait: int = 300) -> str | None:
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
                print(f"    [DEBUG] MiniMax task done mas sem audio_url: {data}")
                return None

            if status == "error":
                print(f"    [DEBUG] MiniMax task error: {data.get('error_message')}")
                return None

            progress = data.get("progress", 0)
            print(f"    [DEBUG] MiniMax progress: {progress}%")
            time.sleep(interval)
            elapsed += interval

        except Exception as e:
            print(f"    [DEBUG] MiniMax poll exception: {e}")
            time.sleep(interval)
            elapsed += interval

    print(f"    [DEBUG] MiniMax polling timeout após {max_wait}s")
    return None
