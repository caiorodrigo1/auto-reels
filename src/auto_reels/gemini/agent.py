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
        if resp.status_code == 400:
            print(f"    [DEBUG] Gemini 400 (key inválida? ...{key[-6:]}): {resp.text[:200]}")
            break
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


def _detect_language(text: str) -> str:
    """Return 'en' if text appears to be English, else 'pt'."""
    sample = text[:500]
    english_words = {"the", "and", "is", "in", "it", "of", "to", "a", "that", "was", "for", "on", "are", "with", "he", "she", "they"}
    words = set(w.lower().strip(".,!?") for w in sample.split())
    matches = len(words & english_words)
    return "en" if matches >= 3 else "pt"


def translate_to_en(text: str) -> str:
    """Translate text to English using Gemini."""
    if not GEMINI_API_KEY:
        return text

    print("    [INFO] Traduzindo para inglês via Gemini...")
    prompt = f"Translate the text below to English. Return only the translated text, no explanations:\n\n{text}"
    return _translate(prompt, fallback=text)


def translate_to_ptbr(text: str) -> str:
    """Translate text to Brazilian Portuguese using Gemini."""
    if not GEMINI_API_KEY:
        return text

    print("    [INFO] Traduzindo para pt-BR via Gemini...")
    prompt = f"Traduza o texto abaixo para o português brasileiro. Retorne apenas o texto traduzido, sem explicações:\n\n{text}"
    return _translate(prompt, fallback=text)


def _translate(prompt: str, fallback: str = "") -> str:
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    resp = None
    for attempt in range(8):
        key = _next_key() if len(_keys) > 1 else _keys[0]
        resp = httpx.post(API_URL, params={"key": key}, json=body, timeout=300)
        if resp.status_code == 429:
            wait = min(2 ** attempt * 10, 120) if len(_keys) == 1 else 2
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            time.sleep(min(2 ** attempt * 5, 60))
            continue
        if resp.status_code == 400:
            return fallback
        resp.raise_for_status()
        break
    else:
        return fallback

    try:
        translated = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        print(f"    [INFO] Tradução concluída ({len(translated)} chars)")
        return translated
    except Exception:
        return fallback


def translate_to_es(text: str) -> str:
    """Translate text to Spanish using Gemini."""
    if not GEMINI_API_KEY:
        return text

    print("    [INFO] Traduzindo para espanhol via Gemini...")
    prompt = f"Traduce el siguiente texto al español. Devuelve solo el texto traducido, sin explicaciones:\n\n{text}"
    return _translate(prompt, fallback=text)


def generate_cultural_chars(history: list, culture: str) -> tuple[str | None, list]:
    """Ask Gemini to regenerate CHAR prompts with cultural appearance."""
    prompt = (
        f"Now regenerate the CHAR reference prompts (CHAR1, CHAR2, CHAR3) "
        f"but adapted for {culture} cultural appearance. Keep the same characters, "
        f"same ages, same roles, but change their physical appearance to reflect "
        f"{culture} ethnicity and cultural traits. Use the exact same format as before."
    )
    print(f"    [INFO] Gerando personagens culturais ({culture})...")
    text, history = _send(history, prompt)
    print(f"    [INFO] Personagens {culture} recebidos ({len(text)} chars)")
    return text, history


def send_sync_prompts(history: list, sync_text: str) -> str | None:
    """Send Dotti Sync prompts to the agent, continuing the conversation."""
    if not GEMINI_API_KEY:
        print("    [DEBUG] GEMINI_API_KEY não configurada")
        return None

    print("    [INFO] Enviando prompts de sync ao Gemini...")
    text, _ = _send(history, sync_text)
    print(f"    [INFO] Resposta recebida ({len(text)} chars)")
    return text
