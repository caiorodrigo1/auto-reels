from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from rich.console import Console

console = Console()

FFMPEG = "/opt/homebrew/bin/ffmpeg"


def compose_final_video(
    video_dir: Path,
    narration_path: Path,
    output_path: Path,
    volume_db: int = -20,
) -> Path:
    """Compose final video by concatenating scenes, lowering audio, and mixing narration."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect all mp4 files sorted by name (numeric prefix ensures correct order)
    scenes = sorted(video_dir.glob("*.mp4"))

    if not scenes:
        console.print("[red]Nenhuma cena encontrada.[/red]")
        return output_path

    console.print(f"[bold]Compondo {len(scenes)} cenas + narração...[/bold]")

    with tempfile.TemporaryDirectory() as tmp:
        concat_file = Path(tmp) / "concat.txt"
        lines = [f"file '{scene.resolve()}'" for scene in scenes]
        concat_file.write_text("\n".join(lines), encoding="utf-8")

        cmd = [
            FFMPEG, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-i", str(narration_path),
            "-filter_complex",
            f"[0:a]volume={volume_db}dB[bg];"
            f"[1:a]aresample=48000,apad[narr];"
            f"[bg][narr]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ]

        console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            console.print(f"[red]FFmpeg erro (code {result.returncode}):[/red]")
            console.print(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)
            return output_path

    console.print(f"[green]Vídeo final salvo em {output_path}[/green]")
    return output_path
