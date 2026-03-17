from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

console = Console()

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def _get_duration(path: Path) -> float:
    """Get media duration in seconds via ffprobe."""
    result = subprocess.run(
        [FFPROBE, "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def compose_final_video(
    video_dir: Path,
    narration_path: Path,
    output_path: Path,
    num_scenes: int = 24,
    sync_path: Path | None = None,
) -> Path:
    """Compose final video by concatenating scenes and adding narration."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build scene list, repeating previous scene for missing ones
    scenes: list[Path] = []
    last_valid: Path | None = None
    missing = []

    for i in range(1, num_scenes + 1):
        scene_path = video_dir / f"scene_{i:03d}.mp4"
        if scene_path.exists():
            scenes.append(scene_path)
            last_valid = scene_path
        elif last_valid is not None:
            scenes.append(last_valid)
            missing.append(i)
        else:
            continue

    if not scenes:
        console.print("  [red]Nenhuma cena encontrada.[/red]")
        return output_path

    for m in missing:
        console.print(f"  [yellow]Cena {m:03d} faltando — repetindo anterior.[/yellow]")

    # Write concat file next to output (not in temp dir)
    concat_file = output_path.parent / "concat.txt"
    lines = [f"file '{scene.resolve()}'" for scene in scenes]
    concat_file.write_text("\n".join(lines), encoding="utf-8")

    # Get durations
    narration_dur = _get_duration(narration_path)
    video_dur = sum(_get_duration(s) for s in set(scenes))  # unique files only
    # Adjust for repeated scenes
    if len(set(scenes)) != len(scenes):
        video_dur = sum(_get_duration(s) for s in scenes)

    need_slowdown = narration_dur > 0 and video_dur > 0 and narration_dur > video_dur
    factor = narration_dur / video_dur if need_slowdown else 1.0

    if need_slowdown:
        console.print(f"  [dim]narração={narration_dur:.0f}s  clipes={video_dur:.0f}s  slowdown={factor:.3f}x[/dim]")
        cmd = [
            FFMPEG, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-i", str(narration_path),
            "-filter_complex",
            f"[0:v]setpts=PTS*{factor:.6f}[v]",
            "-map", "[v]", "-map", "1:a",
            "-c:v", "h264_nvenc", "-preset", "p1", "-cq", "26",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_path),
        ]
    else:
        console.print(f"  [dim]narração={narration_dur:.0f}s  clipes={video_dur:.0f}s  (sem ajuste)[/dim]")
        cmd = [
            FFMPEG, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-i", str(narration_path),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_path),
        ]

    console.print(f"  [dim]{len(scenes)} cenas + {narration_path.name}[/dim]")

    with console.status("  [cyan]Renderizando...[/cyan]"):
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    # Clean up concat file
    concat_file.unlink(missing_ok=True)

    if result.returncode != 0:
        console.print(f"  [red]FFmpeg erro (code {result.returncode}):[/red]")
        console.print(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)
        return output_path

    if output_path.exists() and output_path.stat().st_size > 10_000:
        size_mb = output_path.stat().st_size / 1_048_576
        console.print(f"  [green]✓[/green] Vídeo final  [dim]{output_path.name} ({size_mb:.1f} MB)[/dim]")
    else:
        size = output_path.stat().st_size if output_path.exists() else 0
        console.print(f"  [red]✗ FFmpeg falhou — arquivo inválido ({size} bytes)[/red]")

    return output_path
