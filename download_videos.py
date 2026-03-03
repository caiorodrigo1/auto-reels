"""Download all videos from the existing Flow project in correct order."""
from pathlib import Path
from playwright.sync_api import sync_playwright

output_dir = Path("output/2026-03-03/task-01/videos")
output_dir.mkdir(parents=True, exist_ok=True)
profile_dir = str(Path.home() / ".auto-reels" / "chrome-profile-caio")

# Successful scenes in generation order (oldest to newest)
# Failed: 002, 008, 009
success_scenes = [1, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]
# Flow grid shows newest first, so reverse the list
grid_to_scene = list(reversed(success_scenes))

print(f"Esperados {len(grid_to_scene)} vídeos no grid (newest first):")
for i, s in enumerate(grid_to_scene):
    print(f"  Grid[{i}] → scene_{s:03d}")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        profile_dir,
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.pages[0] if context.pages else context.new_page()

    page.goto("https://labs.google/fx/pt/tools/flow", wait_until="commit", timeout=30_000)
    page.wait_for_timeout(5_000)

    # Find and click the most recent project on the dashboard
    # Projects have timestamps like "Mar 03" in the dashboard
    page.wait_for_timeout(3_000)

    # Take screenshot to see dashboard state
    page.screenshot(path="/tmp/dashboard.png")

    # Click the first project card (most recent)
    # Project cards are typically links in the main content area
    project_links = page.locator("a[href*='/tools/flow/']")
    if project_links.count() == 0:
        # Fallback: click on any card-like element with an image
        project_links = page.get_by_role("link").filter(has=page.locator("img"))

    print(f"\nProjetos encontrados: {project_links.count()}")
    if project_links.count() == 0:
        print("Nenhum projeto encontrado!")
        context.close()
        exit(1)

    project_links.first.click()
    page.wait_for_timeout(5_000)

    # Wait for project content to load (video thumbnails or prompt box)
    page.wait_for_timeout(5_000)

    # Count video thumbnails
    video_links = page.get_by_role("link", name="Miniatura do vídeo")
    total_videos = video_links.count()
    print(f"Vídeos no projeto: {total_videos}")

    if total_videos != len(grid_to_scene):
        print(f"AVISO: esperados {len(grid_to_scene)}, encontrados {total_videos}")
        # Adjust mapping if needed
        if total_videos < len(grid_to_scene):
            grid_to_scene = grid_to_scene[:total_videos]

    downloaded = []
    for i in range(total_videos):
        scene_num = grid_to_scene[i] if i < len(grid_to_scene) else i + 1
        video_path = output_dir / f"scene_{scene_num:03d}.mp4"

        print(f"\n[{i+1}/{total_videos}] Baixando grid[{i}] → {video_path.name}...")

        # Click the video thumbnail at this index
        video_links = page.get_by_role("link", name="Miniatura do vídeo")
        video_links.nth(i).click()
        page.wait_for_timeout(2_000)

        # Wait for edit page (download button)
        download_btn = page.get_by_role("button", name="Baixar")
        download_btn.wait_for(state="visible", timeout=10_000)
        download_btn.click()
        page.wait_for_timeout(500)

        # Download 720p
        with page.expect_download(timeout=120_000) as dl_info:
            page.get_by_role("menuitem", name="720p").click()

        download = dl_info.value
        download.save_as(str(video_path))
        print(f"  [OK] Salvo: {video_path}")
        downloaded.append(video_path)

        # Go back to project grid
        page.get_by_role("button", name="Voltar").click()
        page.wait_for_timeout(2_000)

    context.close()

print(f"\n{'='*50}")
print(f"Baixados: {len(downloaded)} vídeos")
for v in downloaded:
    print(f"  - {v}")
