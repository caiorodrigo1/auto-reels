from __future__ import annotations

import time
from pathlib import Path

import httpx

from auto_reels.config import GEMINI_API_KEY

SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text(encoding="utf-8")
MODEL = "gemini-2.5-flash"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

# Support multiple keys separated by comma for rotation
_keys = [k.strip() for k in GEMINI_API_KEY.split(",") if k.strip()]
_key_index = 0


def _next_key() -> str:
    """Rotate to the next API key."""
    global _key_index
    key = _keys[_key_index % len(_keys)]
    _key_index += 1
    return key


def _send(history: list[dict], message: str) -> tuple[str, list[dict]]:
    """Send message via Gemini REST API with conversation history."""
    history = list(history)
    history.append({"role": "user", "parts": [{"text": message}]})

    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": history,
    }

    for attempt in range(8):
        key = _next_key() if len(_keys) > 1 else _keys[0]
        resp = httpx.post(
            API_URL,
            params={"key": key},
            json=body,
            timeout=300,
        )
        if resp.status_code == 429:
            wait = min(2 ** attempt * 10, 120) if len(_keys) == 1 else 2
            print(f"    [DEBUG] Rate limited (key ...{key[-4:]}), aguardando {wait}s...")
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            wait = min(2 ** attempt * 5, 60)
            print(f"    [DEBUG] Gemini {resp.status_code}, aguardando {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        break
    else:
        raise Exception("Gemini API indisponível após retries")

    data = resp.json()

    text = data["candidates"][0]["content"]["parts"][0]["text"]
    history.append({"role": "model", "parts": [{"text": text}]})
    return text, history


def extract_characters(transcription: str, confirm_msg: str = "sim") -> tuple[str | None, list]:
    """Send transcription to Gemini, confirm, and return (text, history)."""
    if not GEMINI_API_KEY:
        print("    [DEBUG] GEMINI_API_KEY não configurada")
        return None, []

    # Step 1: Send transcription (triggers Etapa 1 analysis)
    print("    [INFO] Enviando roteiro ao Gemini...")
    text1, history = _send([], transcription)
    print(f"    [INFO] Análise recebida ({len(text1)} chars)")

    # Step 2: Confirm to get reference prompts (triggers Etapa 2)
    time.sleep(5)
    print(f"    [INFO] Enviando confirmação: '{confirm_msg}'")
    text2, history = _send(history, confirm_msg)
    print(f"    [INFO] Prompts de referência recebidos ({len(text2)} chars)")

    return f"{text1}\n\n{text2}", history


def send_sync_prompts(history: list, sync_text: str) -> str | None:
    """Send Dotti Sync prompts to the agent, continuing the conversation."""
    if not GEMINI_API_KEY:
        print("    [DEBUG] GEMINI_API_KEY não configurada")
        return None

    print("    [INFO] Enviando prompts de sync ao Gemini...")
    text, _ = _send(history, sync_text)
    print(f"    [INFO] Resposta recebida ({len(text)} chars)")
    return text
