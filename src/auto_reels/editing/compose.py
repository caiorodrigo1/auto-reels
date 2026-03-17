from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from rich.console import Console

from auto_reels.editing.subtitles import sync_to_ass

console = Console()

FFMPEG = "ffmpeg"


def compose_final_video(
    video_dir: Path,
    narration_path: Path,
    output_path: Path,
    num_scenes: int = 24,
    volume_db: int = -30,
    sync_path: Path | None = None,
) -> Path:
    """Compose final video by concatenating scenes, lowering audio, and mixing narration."""
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
            # No previous scene yet — skip (shouldn't happen if scene_001 exists)
            console.print(f"[yellow]Cena {i} faltando e sem cena anterior disponível, pulando.[/yellow]")
            continue

    if not scenes:
        console.print("[red]Nenhuma cena encontrada.[/red]")
        return output_path

    for m in missing:
        console.print(f"[yellow]Cena {m:03d} faltando — repetindo cena anterior.[/yellow]")

    console.print(f"[bold]Compondo {len(scenes)} cenas + narração...[/bold]")

    with tempfile.TemporaryDirectory() as tmp:
        concat_file = Path(tmp) / "concat.txt"
        lines = [f"file '{scene.resolve()}'" for scene in scenes]
        concat_file.write_text("\n".join(lines), encoding="utf-8")

        # Generate ASS subtitles if sync available
        ass_path: Path | None = None
        if sync_path and sync_path.exists():
            ass_path = Path(tmp) / "subtitles.ass"
            result = sync_to_ass(sync_path, ass_path)
            if result:
                console.print("  [dim]Legendas geradas[/dim]")
            else:
                ass_path = None

        # Build video filter
        if ass_path:
            ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")
            vf = f"ass='{ass_escaped}'"
        else:
            vf = None

        audio_filter = (
            f"[0:a]volume={volume_db}dB,aresample=48000[bg];"
            f"[1:a]aresample=48000,apad[narr];"
            f"[bg][narr]amix=inputs=2:duration=longest:normalize=0[aout]"
        )

        cmd = [
            FFMPEG, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-i", str(narration_path),
            "-filter_complex", audio_filter,
            "-map", "0:v", "-map", "[aout]",
        ]

        if vf:
            cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "18"]
        else:
            cmd += ["-c:v", "copy"]

        cmd += ["-c:a", "aac", "-b:a", "192k", str(output_path)]

        console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            console.print(f"[red]FFmpeg erro (code {result.returncode}):[/red]")
            console.print(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)
            return output_path

    console.print(f"[green]Vídeo final salvo em {output_path}[/green]")
    return output_path
