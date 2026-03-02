from __future__ import annotations

from pathlib import Path

from google import genai
from google.genai import types

from auto_reels.config import GEMINI_API_KEY

SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text(encoding="utf-8")


def extract_characters(transcription: str, confirm_msg: str = "sim") -> str | None:
    """Send transcription to Gemini, confirm, and capture character prompts."""
    if not GEMINI_API_KEY:
        print("    [DEBUG] GEMINI_API_KEY não configurada")
        return None

    client = genai.Client(api_key=GEMINI_API_KEY)

    chat = client.chats.create(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
        ),
    )

    # Step 1: Send transcription (triggers Etapa 1 analysis)
    print("    [INFO] Enviando roteiro ao Gemini...")
    response1 = chat.send_message(transcription)
    print(f"    [INFO] Análise recebida ({len(response1.text)} chars)")

    # Step 2: Confirm to get reference prompts (triggers Etapa 2)
    print(f"    [INFO] Enviando confirmação: '{confirm_msg}'")
    response2 = chat.send_message(confirm_msg)
    print(f"    [INFO] Prompts de referência recebidos ({len(response2.text)} chars)")

    # Return both responses combined
    return f"{response1.text}\n\n{response2.text}"
