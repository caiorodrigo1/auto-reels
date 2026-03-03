from __future__ import annotations

import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

FLOW_URL = "https://labs.google/fx/pt/tools/flow"
GENERATION_TIMEOUT = 300  # 5 minutes max per video
POLL_INTERVAL = 10  # seconds between progress checks


def parse_veo_prompts(text: str) -> list[dict]:
    """Parse veo_prompts.txt into structured prompt entries.

    Expected format:
        PROMPT 001 [Char1, Char2] | 00:00 - 00:08:prompt text here
    """
    pattern = re.compile(
        r"PROMPT\s+(\d+)\s+\[([^\]]*)\]\s*\|\s*([\d:]+\s*-\s*[\d:]+)\s*:(.*)",
        re.DOTALL,
    )
    prompts = []
    for block in re.split(r"\n(?=PROMPT\s+\d)", text):
        m = pattern.match(block.strip())
        if m:
            prompts.append({
                "number": int(m.group(1)),
                "characters": m.group(2).strip(),
                "time_range": m.group(3).strip(),
                "prompt": m.group(4).strip(),
            })
    return prompts


def _ensure_authenticated(page: Page):
    """Handle Flow landing page and Google login if needed."""
    # If we're on the marketing/landing page (not logged in), click "Create with Flow"
    create_btn = page.get_by_role("button", name="Create with Flow")
    if create_btn.count() > 0:
        print("    [AUTH] Página de boas-vindas detectada, iniciando login...")
        create_btn.click()
        page.wait_for_timeout(3_000)

    # If redirected to Google login
    if "accounts.google.com" in page.url:
        print("    [AUTH] Login necessário. Faça login no navegador que abriu...")
        print("    [AUTH] Aguardando autenticação (timeout: 5 min)...")
        page.wait_for_url("**/tools/flow**", timeout=300_000)
        page.wait_for_timeout(3_000)

    # If we're on a loading screen, wait for it
    page.wait_for_timeout(2_000)


def _wait_for_dashboard(page: Page, timeout: int = 60_000):
    """Wait for the Flow dashboard to load."""
    page.get_by_text("Novo projeto").first.wait_for(state="visible", timeout=timeout)


def _create_project(page: Page) -> str:
    """Create a new Flow project and return the project URL."""
    page.get_by_role("button", name="Novo projeto").click()
    # Wait for editor to load (prompt textbox appears)
    page.get_by_text("O que você quer criar?").first.wait_for(
        state="visible", timeout=15_000
    )
    return page.url


def _configure_video_portrait(page: Page):
    """Configure model settings: Video, Ingredients, Portrait 9:16, x1."""
    page.wait_for_timeout(2_000)

    # Click the model selector button — it contains "x1", "x2" etc and a media type
    selector_btn = page.locator("button").filter(has_text=re.compile(r"x\d$"))
    selector_btn.first.wait_for(state="visible", timeout=10_000)
    selector_btn.first.click()
    page.wait_for_timeout(1_000)

    # Select Video tab
    video_tab = page.get_by_role("tab", name=re.compile(r"Video|Vídeo"))
    if video_tab.count() and video_tab.first.get_attribute("aria-selected") != "true":
        video_tab.first.click()
        page.wait_for_timeout(1_000)

    # Wait for Ingredients tab to appear (it renders after Video is selected)
    ingredients_tab = page.get_by_role("tab", name="Ingredients")
    ingredients_tab.first.wait_for(state="visible", timeout=5_000)
    if ingredients_tab.first.get_attribute("aria-selected") != "true":
        ingredients_tab.first.click()
        page.wait_for_timeout(500)
    print("    [CONFIG] Modo Ingredients selecionado")

    # Select Portrait (Retrato) tab
    portrait_tab = page.get_by_role("tab", name="Retrato")
    if portrait_tab.count() and portrait_tab.first.get_attribute("aria-selected") != "true":
        portrait_tab.first.click()
        page.wait_for_timeout(300)

    # Select x1 quantity
    x1_tab = page.get_by_role("tab", name="x1")
    if x1_tab.count() and x1_tab.first.get_attribute("aria-selected") != "true":
        x1_tab.first.click()
        page.wait_for_timeout(300)

    # Close menu by pressing Escape
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


def _parse_char_key(filename: str) -> str | None:
    """Extract character key (e.g. 'Char1') from image filename like 'char1___val_ria.png'."""
    m = re.match(r"(char\d+)", filename, re.IGNORECASE)
    return m.group(1).capitalize() if m else None


def _upload_character_images(page: Page, image_paths: list[Path]) -> dict[str, bool]:
    """Upload character reference images to the project.

    Returns dict mapping character key (e.g. 'Char1') to upload success.
    """
    results: dict[str, bool] = {}
    for img_path in image_paths:
        if not img_path.exists():
            print(f"    [WARN] Imagem não encontrada: {img_path}")
            continue

        char_key = _parse_char_key(img_path.name)
        if not char_key:
            print(f"    [WARN] Não foi possível extrair char key de: {img_path.name}")
            continue

        # Click "Adicionar mídia"
        page.get_by_role("button", name="Adicionar mídia").click()
        page.wait_for_timeout(500)

        # Click "Faça upload de uma imagem"
        with page.expect_file_chooser(timeout=5_000) as fc_info:
            page.get_by_role("menuitem", name=re.compile(r"upload.*imagem", re.IGNORECASE)).click()

        file_chooser = fc_info.value
        file_chooser.set_files(str(img_path))

        # Count content grid links/items before upload (not UI icons)
        # Flow project grid items are links with role="link"
        grid_links_before = page.get_by_role("link").filter(has=page.locator("img")).count()

        # Wait for upload result
        upload_ok = False
        error_found = False
        for i in range(30):  # up to ~15 seconds
            page.wait_for_timeout(500)

            # Check for success — more grid link items with images
            grid_links_after = page.get_by_role("link").filter(has=page.locator("img")).count()
            if grid_links_after > grid_links_before:
                upload_ok = True
                break

            # Check for upload-specific error phrases
            error_phrases = [
                "proíbem o envio",
                "não permitimos uploads",
                "Falha no upload",
                "famosas no momento",
            ]
            for phrase in error_phrases:
                notif = page.locator(f"text={phrase}")
                if notif.count() > 0:
                    try:
                        if notif.first.is_visible():
                            err_text = notif.first.inner_text()
                            print(f"    [DEBUG] Erro de upload: {err_text[:100]}")
                            error_found = True
                            break
                    except Exception:
                        pass
            if error_found:
                break

        if upload_ok:
            results[char_key] = True
            print(f"    [OK] Imagem enviada: {char_key} ({img_path.name})")
        else:
            if error_found:
                print(f"    [WARN] Upload bloqueado para {char_key} ({img_path.name})")
            else:
                print(f"    [WARN] Upload timeout para {char_key} ({img_path.name})")
            results[char_key] = False
            # Dismiss any error/overlay
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)

    return results


def _parse_scene_characters(characters_str: str) -> list[str]:
    """Parse character list from prompt header like 'Char1, Char2 and Char3'."""
    # Normalize separators: "Char1, Char2 and Char3" → ["Char1", "Char2", "Char3"]
    chars = re.split(r"\s*,\s*|\s+and\s+|\s+e\s+", characters_str)
    return [c.strip() for c in chars if c.strip()]


def _attach_ingredients(page: Page, char_keys: list[str], uploaded: dict[str, bool]):
    """Attach character ingredient images to the current prompt via @ picker.

    For each character that was successfully uploaded, types @ and selects the image.
    """
    chars_to_attach = [c for c in char_keys if uploaded.get(c)]
    if not chars_to_attach:
        return

    for char_key in chars_to_attach:
        # Click the textbox to ensure focus
        textbox = page.get_by_role("textbox").filter(has_text="O que você quer criar?")
        if not textbox.count():
            textbox = page.locator("[contenteditable='true']").last
        textbox.click()
        page.wait_for_timeout(300)

        # Type @ to open ingredient picker
        page.keyboard.type("@")
        page.wait_for_timeout(1_000)

        # The picker dialog should open — look for the search box
        search_box = page.get_by_placeholder("Pesquisar recursos")
        if not search_box.count():
            print(f"    [WARN] Picker não abriu para {char_key}, pulando")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            continue

        # The current project images should be visible (we uploaded them)
        # Find clickable image items in the picker (try multiple selectors)
        items = page.locator("[role='dialog'] img, [role='listbox'] img")
        if items.count() == 0:
            items = page.locator("img[alt='Untitled']")
        if items.count() == 0:
            # Broader fallback: any img inside the picker area
            items = page.locator("[class*='picker'] img, [class*='resource'] img")

        # Calculate index based on upload order
        uploaded_keys = sorted([k for k, v in uploaded.items() if v])
        idx = uploaded_keys.index(char_key) if char_key in uploaded_keys else 0

        if items.count() > idx:
            items.nth(idx).click()
            page.wait_for_timeout(500)
            print(f"    [OK] Ingredient {char_key} anexado ao prompt")
        else:
            print(f"    [WARN] Imagem de {char_key} não encontrada no picker ({items.count()} itens)")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)


def _count_completed_videos(page: Page) -> int:
    """Count completed video thumbnails in the project grid."""
    # Completed videos have a thumbnail image with play_circle overlay
    # Try multiple selectors for robustness
    links = page.get_by_role("link", name="Miniatura do vídeo")
    if links.count() > 0:
        return links.count()
    # Fallback: look for play_circle icons (appear on completed videos)
    play_icons = page.locator("text=play_circle")
    return play_icons.count()


def _submit_prompt(
    page: Page,
    prompt_text: str,
    char_keys: list[str] | None = None,
    uploaded: dict[str, bool] | None = None,
):
    """Attach ingredients (if any) and submit a video generation prompt."""
    # Attach character ingredients before typing the prompt
    if char_keys and uploaded:
        _attach_ingredients(page, char_keys, uploaded)

    # Find and fill the prompt textbox
    textbox = page.get_by_role("textbox").filter(has_text="O que você quer criar?")
    if not textbox.count():
        textbox = page.locator("[contenteditable='true']").last

    textbox.click()
    textbox.fill(prompt_text)
    page.wait_for_timeout(500)

    # Click the submit button (arrow_forward Criar)
    page.get_by_role("button", name="arrow_forward Criar").click()
    page.wait_for_timeout(2_000)


def _wait_for_generation(
    page: Page, prev_completed: int, timeout: int = GENERATION_TIMEOUT
) -> bool:
    """Wait for a new completed video beyond prev_completed count."""
    start = time.time()
    last_pct = ""
    while time.time() - start < timeout:
        page.wait_for_timeout(POLL_INTERVAL * 1000)

        # Check if a new completed video appeared
        current = _count_completed_videos(page)
        if current > prev_completed:
            return True

        # Check for active progress percentage
        progress_cards = page.locator("text=/\\d+%/")
        if progress_cards.count() > 0:
            try:
                pct_text = progress_cards.first.inner_text()
                if pct_text != last_pct:
                    print(f"    [PROGRESS] {pct_text}")
                    last_pct = pct_text
            except Exception:
                pass
            continue

        # No progress and no new completion — might have just finished
        # Wait one more cycle to let the UI update
        elapsed = time.time() - start
        if elapsed > 30:
            # Re-check completion after a brief extra wait
            page.wait_for_timeout(3_000)
            current = _count_completed_videos(page)
            if current > prev_completed:
                return True

        # Check for failure
        fail_markers = page.locator("text=Falha")
        if fail_markers.count() > 0:
            # Verify it's a video generation failure (has "Reutilizar comando")
            reuse_buttons = page.get_by_role("button", name="Reutilizar comando")
            if reuse_buttons.count() > 0:
                print("    [ERROR] Geração falhou")
                return False

    print("    [ERROR] Timeout na geração do vídeo")
    return False


def _download_video(page: Page, output_path: Path) -> Path | None:
    """Click on the latest video, download at 720p, and save to output_path."""
    # Click the latest video thumbnail link
    thumbnail_link = page.get_by_role("link", name="Miniatura do vídeo").last
    if not thumbnail_link.count():
        # Fallback: click on any thumbnail image inside a link
        thumbnail_link = page.locator("a").filter(has=page.locator("img")).last
    thumbnail_link.click()

    # Wait for edit page to load (download button appears)
    page.get_by_role("button", name="Baixar").wait_for(state="visible", timeout=10_000)

    # Click "Baixar" (Download)
    page.get_by_role("button", name="Baixar").click()
    page.wait_for_timeout(500)

    # Select 720p Original Size and capture the download
    with page.expect_download(timeout=120_000) as dl_info:
        page.get_by_role("menuitem", name="720p").click()

    download = dl_info.value
    output_path.parent.mkdir(parents=True, exist_ok=True)
    download.save_as(str(output_path))

    # Go back to project view
    page.get_by_role("button", name="Voltar").click()
    page.wait_for_timeout(1_000)

    return output_path if output_path.exists() else None


def generate_videos(
    veo_prompts_path: Path,
    output_dir: Path,
    image_paths: list[Path] | None = None,
    headless: bool = False,
) -> list[Path]:
    """Generate videos from Veo prompts using Google Flow via Playwright.

    Args:
        veo_prompts_path: Path to the veo_prompts.txt file
        output_dir: Directory to save generated video files
        image_paths: Optional list of character reference image paths
        headless: Run browser in headless mode (requires existing auth)

    Returns:
        List of paths to downloaded video files
    """
    text = veo_prompts_path.read_text(encoding="utf-8")
    prompts = parse_veo_prompts(text)

    if not prompts:
        print("    [ERROR] Nenhum prompt encontrado em veo_prompts.txt")
        return []

    print(f"    [INFO] {len(prompts)} prompts encontrados")
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        # Use persistent context to reuse existing Google auth
        context = browser.new_context()
        page = context.new_page()

        # Navigate to Flow
        page.goto(FLOW_URL, wait_until="networkidle", timeout=30_000)
        _wait_for_dashboard(page)

        # Create new project
        print("    [INFO] Criando novo projeto no Flow...")
        _create_project(page)

        # Configure video settings
        print("    [INFO] Configurando: Vídeo, Retrato 9:16, x1...")
        _configure_video_portrait(page)

        # Upload character images if provided
        uploaded: dict[str, bool] = {}
        if image_paths:
            print(f"    [INFO] Enviando {len(image_paths)} imagens de personagens...")
            uploaded = _upload_character_images(page, image_paths)

        # Submit each prompt and download
        for prompt_info in prompts:
            num = prompt_info["number"]
            prompt_text = prompt_info["prompt"]
            scene_chars = _parse_scene_characters(prompt_info["characters"])
            print(f"    [INFO] Prompt {num:03d} ({prompt_info['time_range']}) chars={scene_chars}...")

            prev_count = _count_completed_videos(page)
            _submit_prompt(page, prompt_text, char_keys=scene_chars, uploaded=uploaded)

            if _wait_for_generation(page, prev_count):
                video_path = output_dir / f"scene_{num:03d}.mp4"
                result = _download_video(page, video_path)
                if result:
                    print(f"    [OK] Vídeo salvo: {result}")
                    downloaded.append(result)
                else:
                    print(f"    [ERROR] Falha ao baixar vídeo {num:03d}")
            else:
                print(f"    [ERROR] Geração falhou para prompt {num:03d}")

        browser.close()

    return downloaded


def generate_videos_persistent(
    veo_prompts_path: Path,
    output_dir: Path,
    image_paths: list[Path] | None = None,
    user_data_dir: str | None = None,
) -> list[Path]:
    """Generate videos using a persistent browser context (preserves Google login).

    Args:
        veo_prompts_path: Path to the veo_prompts.txt file
        output_dir: Directory to save generated video files
        image_paths: Optional list of character reference image paths
        user_data_dir: Path to Chrome user data directory for persistent auth

    Returns:
        List of paths to downloaded video files
    """
    text = veo_prompts_path.read_text(encoding="utf-8")
    prompts = parse_veo_prompts(text)

    if not prompts:
        print("    [ERROR] Nenhum prompt encontrado em veo_prompts.txt")
        return []

    print(f"    [INFO] {len(prompts)} prompts encontrados")
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []

    if not user_data_dir:
        user_data_dir = str(Path.home() / ".auto-reels" / "chrome-profile")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        # Navigate to Flow
        page.goto(FLOW_URL, wait_until="networkidle", timeout=60_000)

        # Handle auth if needed
        _ensure_authenticated(page)
        _wait_for_dashboard(page)

        # Create new project
        print("    [INFO] Criando novo projeto no Flow...")
        _create_project(page)

        # Configure video settings
        print("    [INFO] Configurando: Vídeo, Retrato 9:16, x1...")
        _configure_video_portrait(page)

        # Upload character images if provided
        uploaded: dict[str, bool] = {}
        if image_paths:
            print(f"    [INFO] Enviando {len(image_paths)} imagens de personagens...")
            uploaded = _upload_character_images(page, image_paths)

        # Submit each prompt and download
        for prompt_info in prompts:
            num = prompt_info["number"]
            prompt_text = prompt_info["prompt"]
            scene_chars = _parse_scene_characters(prompt_info["characters"])
            print(f"    [INFO] Prompt {num:03d} ({prompt_info['time_range']}) chars={scene_chars}...")

            prev_count = _count_completed_videos(page)
            _submit_prompt(page, prompt_text, char_keys=scene_chars, uploaded=uploaded)

            if _wait_for_generation(page, prev_count):
                video_path = output_dir / f"scene_{num:03d}.mp4"
                result = _download_video(page, video_path)
                if result:
                    print(f"    [OK] Vídeo salvo: {result}")
                    downloaded.append(result)
                else:
                    print(f"    [ERROR] Falha ao baixar vídeo {num:03d}")
            else:
                print(f"    [ERROR] Geração falhou para prompt {num:03d}")

        context.close()

    return downloaded
