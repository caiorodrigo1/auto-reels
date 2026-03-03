"""Run all veo prompts with Ingredients mode (Veo 3 - Fast low priority)."""
from pathlib import Path
from auto_reels.video_gen.flow import generate_videos_persistent

veo_file = Path("output/2026-03-03/task-01/veo_prompts.txt")
image_dir = Path("output/2026-03-03/task-01/images")
output_dir = Path("output/2026-03-03/task-01/videos")

# Use a separate Chrome profile for caiorodrigo4455
profile_dir = str(Path.home() / ".auto-reels" / "chrome-profile-caio")

char_images = sorted(image_dir.glob("*.png")) if image_dir.exists() else []
print(f"Veo prompts: {veo_file}")
print(f"Character images: {[p.name for p in char_images]}")
print(f"Output dir: {output_dir}")
print(f"Chrome profile: {profile_dir}")
print(f"Model: Veo 3 (Fast low priority - 0 créditos)")
print()

results = generate_videos_persistent(
    veo_file,
    output_dir,
    image_paths=char_images or None,
    user_data_dir=profile_dir,
    model="Lower Priority",
)

print(f"\n{'='*50}")
print(f"Resultado: {len(results)} vídeos gerados de 24 prompts")
for v in results:
    print(f"  - {v}")
