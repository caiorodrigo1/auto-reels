"""Test single prompt with ingredients workflow."""
from pathlib import Path
from auto_reels.video_gen.flow import (
    parse_veo_prompts,
    _parse_scene_characters,
    _ensure_authenticated,
    _wait_for_dashboard,
    _create_project,
    _configure_video_portrait,
    _upload_character_images,
    _submit_prompt,
    _wait_for_generation,
    _download_video,
    _count_completed_videos,
    FLOW_URL,
)
from playwright.sync_api import sync_playwright

veo_file = Path("output/2026-03-03/task-01/veo_prompts.txt")
image_dir = Path("output/2026-03-03/task-01/images")
output_dir = Path("output/2026-03-03/task-01/videos")
output_dir.mkdir(parents=True, exist_ok=True)

# Parse first prompt only
text = veo_file.read_text(encoding="utf-8")
prompts = parse_veo_prompts(text)
first = prompts[0]
scene_chars = _parse_scene_characters(first["characters"])
print(f"Testing PROMPT {first['number']:03d} chars={scene_chars}")
print(f"Prompt text: {first['prompt'][:100]}...")

# Get character images
char_images = sorted(image_dir.glob("*.png"))
print(f"Character images: {[p.name for p in char_images]}")

user_data_dir = str(Path.home() / ".auto-reels" / "chrome-profile")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir,
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.pages[0] if context.pages else context.new_page()

    page.goto(FLOW_URL, wait_until="networkidle", timeout=60_000)
    _ensure_authenticated(page)
    _wait_for_dashboard(page)

    print("\n[1/5] Criando projeto...")
    _create_project(page)

    print("[2/5] Configurando vídeo...")
    _configure_video_portrait(page)

    print("[3/5] Uploading character images...")
    uploaded = _upload_character_images(page, char_images)
    print(f"Upload results: {uploaded}")

    print(f"[4/5] Submitting prompt with ingredients...")
    prev_count = _count_completed_videos(page)
    _submit_prompt(page, first["prompt"], char_keys=scene_chars, uploaded=uploaded)

    print("[5/5] Waiting for generation...")
    if _wait_for_generation(page, prev_count):
        video_path = output_dir / f"scene_{first['number']:03d}.mp4"
        result = _download_video(page, video_path)
        if result:
            print(f"\nSUCCESS: Video saved to {result}")
        else:
            print("\nFAILED: Could not download video")
    else:
        print("\nFAILED: Video generation timed out or failed")

    context.close()
