from __future__ import annotations

import time
from pathlib import Path

import httpx

from auto_reels.config import GEMINI_API_KEY

SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text(encoding="utf-8")
MODEL = "gemini-2.5-flash"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

_keys = [k.strip() for k in GEMINI_API_KEY.split(",") if k.strip()]
KEY_RETRY_WAIT = 15
_RETRY_ROUNDS = 3


def _call_gemini(body: dict) -> httpx.Response:
    """Try all keys up to _RETRY_ROUNDS times, 15s between each attempt."""
    last_resp = None
    for _ in range(_RETRY_ROUNDS):
        for key in _keys:
            try:
                resp = httpx.post(API_URL, params={"key": key}, json=body, timeout=300)
            except Exception as e:
                print(f"    [DEBUG] Gemini network error (key ...{key[-4:]}): {e}, aguardando {KEY_RETRY_WAIT}s...")
                time.sleep(KEY_RETRY_WAIT)
                continue
            last_resp = resp
            if resp.status_code == 400:
                print(f"    [DEBUG] Gemini 400 (key ...{key[-4:]}): {resp.text[:200]}")
                raise Exception(f"Gemini 400: {resp.text[:200]}")
            if resp.status_code in (429, 403, 500, 503):
                print(f"    [DEBUG] Gemini {resp.status_code} (key ...{key[-4:]}), aguardando {KEY_RETRY_WAIT}s...")
                time.sleep(KEY_RETRY_WAIT)
                continue
            resp.raise_for_status()
            return resp
    raise Exception(f"Gemini API indisponível após testar {len(_keys)} key(s) × {_RETRY_ROUNDS} rounds")


def _send(history: list[dict], message: str) -> tuple[str, list[dict]]:
    """Send message via Gemini REST API with conversation history."""
    history = list(history)
    history.append({"role": "user", "parts": [{"text": message}]})

    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": history,
    }

    resp = _call_gemini(body)
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
    try:
        resp = _call_gemini(body)
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
    try:
        text, _ = _send(history, sync_text)
    except Exception as e:
        print(f"    [DEBUG] Falha no send_sync_prompts: {e}")
        return None
    print(f"    [INFO] Resposta recebida ({len(text)} chars)")
    return text
