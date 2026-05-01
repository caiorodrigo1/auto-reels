"""Regenerate veo_prompts, images and video clips for pending tasks."""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
from rich.console import Console
from rich.rule import Rule

from auto_reels.image_gen.webhook import generate_character_images
from auto_reels.video_gen.glabs import generate_videos
from auto_reels.editing.compose import compose_final_video
from auto_reels.gemini.agent import extract_characters, send_sync_prompts, translate_to_es, translate_to_ptbr
from auto_reels.narration.minimax import generate_speech
from auto_reels.sync.dotti import generate_sync
from auto_reels.output import clean_text, save_characters

console = Console(force_terminal=True, legacy_windows=False)
OUTPUT = Path("output")

PENDING = [
    ("2026-04-22", "task-02"),
    ("2026-04-22", "task-03"),
]

LANGS = ["en", "es", "ptbr"]


def run():
    for date, task in PENDING:
        task_dir = OUTPUT / date / task
        chars_file = task_dir / "characters.txt"
        veo_file = task_dir / "veo_prompts.txt"
        sync_file = task_dir / "sync.txt"
        transcription_file = task_dir / "transcription.txt"

        if not task_dir.exists():
            console.print(f"[red]SKIP {date}/{task} — não existe[/red]")
            continue

        console.print(Rule(f"[bold cyan]{date} / {task}[/bold cyan]"))

        # --- Characters + history (always rebuild history when veo_prompts is missing) ---
        gemini_history = []
        if not veo_file.exists() and transcription_file.exists():
            console.print(f"  [yellow]Extraindo personagens via Gemini (rebuild history)...[/yellow]")
            text = transcription_file.read_text(encoding="utf-8")
            try:
                chars, gemini_history = extract_characters(clean_text(text))
                if chars:
                    chars_file.write_text(chars, encoding="utf-8")
                    console.print(f"  [green]✓[/green] Personagens salvos")
                else:
                    console.print(f"  [red]✗ Falha ao extrair personagens[/red]")
            except Exception as e:
                console.print(f"  [red]✗ Gemini indisponível: {e}[/red]")

        chars_text = chars_file.read_text(encoding="utf-8") if chars_file.exists() else ""

        # --- EN Narration (if missing) ---
        en_narration = task_dir / "en" / "narration.mp3"
        if not en_narration.exists() and transcription_file.exists():
            console.print(f"  [yellow]Gerando narração EN...[/yellow]")
            text = transcription_file.read_text(encoding="utf-8")
            result = generate_speech(clean_text(text), en_narration)
            if result:
                console.print(f"  [green]✓[/green] Narração EN salva")
            else:
                console.print(f"  [red]✗ Falha ao gerar narração EN[/red]")

        # --- Dotti Sync (if missing) ---
        if not sync_file.exists() and en_narration.exists():
            console.print(f"  [yellow]Gerando Dotti Sync...[/yellow]")
            result = generate_sync(en_narration, sync_file)
            if result:
                console.print(f"  [green]✓[/green] Sync salvo")
            else:
                console.print(f"  [red]✗ Falha ao gerar sync[/red]")

        # --- veo_prompts (if missing but sync exists) ---
        if not veo_file.exists() and sync_file.exists():
            console.print(f"  [yellow]Gerando veo_prompts via Gemini...[/yellow]")
            sync_content = sync_file.read_text(encoding="utf-8")
            try:
                veo_text = send_sync_prompts(gemini_history, sync_content)
                if veo_text:
                    veo_file.write_text(veo_text, encoding="utf-8")
                    console.print(f"  [green]✓[/green] veo_prompts.txt gerado")
                else:
                    console.print(f"  [red]✗ Falha ao gerar veo_prompts[/red]")
            except Exception as e:
                console.print(f"  [red]✗ Gemini indisponível: {e}[/red]")

        # Read EN narration text once for translations
        en_text = clean_text(transcription_file.read_text(encoding="utf-8")) if transcription_file.exists() else ""

        for lang in LANGS:
            lang_dir = task_dir / lang
            img_dir = lang_dir / "images"
            vid_dir = lang_dir / "videos"
            narration = lang_dir / "narration.mp3"

            # --- ES/PT-BR Narration (if missing) ---
            if lang != "en" and not narration.exists() and en_text:
                console.print(f"  [yellow]Traduzindo e gerando narração [{lang.upper()}]...[/yellow]")
                try:
                    if lang == "es":
                        translated = translate_to_es(en_text)
                    elif lang == "ptbr":
                        translated = translate_to_ptbr(en_text)
                    else:
                        translated = en_text
                    result = generate_speech(translated, narration)
                    if result:
                        console.print(f"  [green]✓[/green] Narração {lang.upper()} salva")
                    else:
                        console.print(f"  [red]✗ Falha ao gerar narração {lang.upper()}[/red]")
                except Exception as e:
                    console.print(f"  [red]✗ Erro na tradução/TTS {lang.upper()}: {e}[/red]")

            # --- Images ---
            existing_imgs = list(img_dir.glob("*.png")) if img_dir.exists() else []
            if not existing_imgs and chars_text:
                console.print(f"  [yellow]Gerando imagens [{lang.upper()}]...[/yellow]")
                generate_character_images(chars_text, img_dir)
            else:
                console.print(f"  [dim]Imagens [{lang.upper()}]: {len(existing_imgs)} já existem[/dim]")

            # --- Videos ---
            if not veo_file.exists():
                console.print(f"  [dim]Sem veo_prompts, pulando vídeos [{lang.upper()}][/dim]")
                continue

            import re
            expected_vids = len(re.findall(r"PROMPT\s+\d+", veo_file.read_text(encoding="utf-8")))
            existing_vids = list(vid_dir.glob("scene_*.mp4")) if vid_dir.exists() else []

            if len(existing_vids) < expected_vids:
                console.print(f"  [yellow]Gerando clipes [{lang.upper()}] ({len(existing_vids)}/{expected_vids})...[/yellow]")
                char_images = sorted(img_dir.glob("*.png")) if img_dir.exists() else []
                generate_videos(veo_file, vid_dir, image_paths=char_images or None)
            else:
                console.print(f"  [dim]Clipes [{lang.upper()}]: {len(existing_vids)}/{expected_vids} completos[/dim]")

            # --- Compose ---
            final_path = lang_dir / "final.mp4"
            clips = sorted(vid_dir.glob("scene_*.mp4")) if vid_dir.exists() else []
            if clips and narration.exists() and not final_path.exists():
                console.print(f"  [yellow]Composição final [{lang.upper()}] ({len(clips)} clipes)...[/yellow]")
                compose_final_video(vid_dir, narration, final_path, num_scenes=len(clips), sync_path=None)
            elif final_path.exists():
                console.print(f"  [dim]Final [{lang.upper()}]: já existe[/dim]")

        console.print()

    console.print(Rule("[bold green]Regeneração concluída![/bold green]", style="green"))


if __name__ == "__main__":
    run()
