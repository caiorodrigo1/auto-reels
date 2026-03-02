from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

from auto_reels.config import CLAUDE_PROJECT_URL

# Persistent browser data so login session is reused across runs
BROWSER_DATA_DIR = Path.home() / ".auto-reels-browser"


def login() -> None:
    """Open browser for manual login. Session is saved for future runs."""
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(BROWSER_DATA_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://claude.ai", wait_until="domcontentloaded", timeout=60_000)
        print("Navegador aberto. Faça login via OAuth e pressione Enter aqui quando terminar...")
        input()
        context.close()
        print("Sessão salva!")


def extract_characters(transcription: str, confirm_msg: str = "sim") -> str | None:
    """Send transcription to Claude project, confirm response, and capture characters."""
    if not CLAUDE_PROJECT_URL:
        print("    [DEBUG] CLAUDE_PROJECT_URL não configurada")
        return None

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(BROWSER_DATA_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            return _run_flow(page, transcription, confirm_msg)
        finally:
            context.close()


def _run_flow(page: Page, transcription: str, confirm_msg: str) -> str | None:
    # 1. Navigate to project
    print("    [INFO] Abrindo Claude web...")
    page.goto(CLAUDE_PROJECT_URL, wait_until="domcontentloaded", timeout=60_000)

    # Wait for chat input - if login is needed, user has up to 5min
    input_sel = 'div[contenteditable="true"]'
    print("    [INFO] Aguardando chat ficar pronto (faça login se necessário)...")

    deadline = time.time() + 300
    while time.time() < deadline:
        if "/login" not in page.url:
            try:
                page.wait_for_selector(input_sel, timeout=5_000)
                break
            except Exception:
                pass
        time.sleep(2)
    else:
        print("    [DEBUG] Timeout aguardando chat (5min)")
        return None

    print("    [INFO] Chat pronto!")
    time.sleep(2)

    # 2. Type transcription and send
    _send_message(page, transcription, input_sel)

    # 3. Wait for agent first response
    print("    [INFO] Aguardando resposta do agente (até 3min)...")
    _wait_for_response(page, timeout=180)
    time.sleep(2)

    # 4. Send confirmation
    print("    [INFO] Enviando confirmação...")
    _send_message(page, confirm_msg, input_sel)

    # 5. Wait for final response with characters
    print("    [INFO] Aguardando resposta final com personagens (até 3min)...")
    _wait_for_response(page, timeout=180)
    time.sleep(2)

    # 6. Capture last assistant response
    return _get_last_response(page)


def _send_message(page: Page, text: str, input_sel: str) -> None:
    input_box = page.locator(input_sel).last
    input_box.click()
    time.sleep(0.5)
    # Inject text via JS into contenteditable, then dispatch input event
    input_box.evaluate(
        "(el, text) => { el.innerText = text; el.dispatchEvent(new Event('input', {bubbles: true})); }",
        text,
    )
    time.sleep(1)
    # Find and click the send button
    send_btn = page.locator('button[aria-label="Send Message"]')
    if send_btn.is_visible():
        send_btn.click()
    else:
        page.keyboard.press("Enter")
    print(f"    [DEBUG] Mensagem enviada ({len(text)} chars)")


def _wait_for_response(page: Page, timeout: int = 120) -> None:
    """Wait until Claude finishes responding (stop button appears then disappears)."""
    # Try multiple selectors for the stop/loading indicator
    stop_selectors = [
        'button[aria-label="Stop Response"]',
        'button[aria-label="Stop response"]',
        'button[aria-label="Parar resposta"]',
        '[data-testid="stop-button"]',
    ]

    # Wait for any stop indicator to appear (response started)
    print("    [DEBUG] Waiting for response to start...")
    started = False
    start_deadline = time.time() + 30
    while time.time() < start_deadline:
        for sel in stop_selectors:
            if page.locator(sel).is_visible():
                print(f"    [DEBUG] Response started (found: {sel})")
                started = True
                break
        if started:
            break
        time.sleep(0.5)

    if not started:
        print("    [DEBUG] No stop button found - checking if response already completed")
        time.sleep(5)
        return

    # Wait for stop button to disappear (response finished)
    print("    [DEBUG] Waiting for response to finish...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        visible = False
        for sel in stop_selectors:
            if page.locator(sel).is_visible():
                visible = True
                break
        if not visible:
            print("    [DEBUG] Response finished!")
            return
        time.sleep(1)

    print("    [DEBUG] Timeout waiting for Claude response")


def _get_last_response(page: Page) -> str | None:
    """Extract text from the last assistant (Claude) message."""
    # [data-is-streaming] marks Claude's responses, not user messages
    messages = page.locator("[data-is-streaming]").all()
    if messages:
        print(f"    [DEBUG] Found {len(messages)} Claude responses")
        return messages[-1].inner_text()

    print("    [DEBUG] No Claude responses found on page")
    return None
