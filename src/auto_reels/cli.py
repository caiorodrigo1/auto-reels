from __future__ import annotations

import re
import sys
import typer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from auto_reels.channels import load_channels
from auto_reels.youtube.api import search_recent_videos, get_video_details
from auto_reels.youtube.shorts import filter_shorts, rank_and_select
from auto_reels.transcription.service import transcribe
from auto_reels.narration.minimax import generate_speech
from auto_reels.gemini.agent import (
    extract_characters, send_sync_prompts, translate_to_ptbr,
    translate_to_es, translate_to_en, generate_cultural_chars, _detect_language,
)
from auto_reels.image_gen.webhook import generate_character_images
from auto_reels.sync.dotti import generate_sync
from auto_reels.video_gen.glabs import generate_videos
from auto_reels.editing.compose import compose_final_video
from auto_reels.output import (
    save_transcription, save_characters,
    get_task_dir, get_lang_dir, clean_text,
    load_processed_ids, save_processed_id,
)
from auto_reels.config import SEARCH_DAYS, TOP_N, MAX_SHORT_DURATION_SECONDS, AI33_API_KEY, GEMINI_API_KEY, WEBHOOK_API_KEY, DOTTI_SYNC_URL

app = typer.Typer(name="auto-reels", help="Pipeline de YouTube Shorts + transcrição + narração + personagens + imagens")
console = Console(force_terminal=True, legacy_windows=False)

LANG_LABELS = {"en": "EN", "es": "ES", "ptbr": "PT-BR"}
CULTURE_MAP = {"es": "Mexican", "ptbr": "Brazilian"}


def _step(label: str, icon: str = "•"):
    console.print(f"  [bold cyan]{icon} {label}[/bold cyan]")


def _process_language(
    task_number: int,
    lang: str,
    narration_text_en: str,
    gemini_history: list,
    veo_prompts_path,
    *,
    do_narrate: bool,
    do_sync: bool,
    do_videos: bool,
):
    """Process a single language variant for a task."""
    lang_dir = get_lang_dir(task_number, lang)
    task_dir = get_task_dir(task_number)
    lang_label = LANG_LABELS.get(lang, lang.upper())

    # --- Narration ---
    if do_narrate and AI33_API_KEY:
        narration_path = lang_dir / "narration.mp3"
        if lang == "en":
            narration_text = narration_text_en
        elif lang == "es":
            _step(f"Traduzindo para espanhol [{lang_label}]")
            narration_text = translate_to_es(narration_text_en)
            console.print(f"  [green]✓[/green] Tradução ES concluída")
        elif lang == "ptbr":
            _step(f"Traduzindo para pt-BR [{lang_label}]")
            narration_text = translate_to_ptbr(narration_text_en)
            console.print(f"  [green]✓[/green] Tradução PT-BR concluída")
        else:
            narration_text = narration_text_en

        _step(f"Narração [{lang_label}]")
        result = generate_speech(clean_text(narration_text), narration_path)
        if result:
            console.print(f"  [green]✓[/green] Narração salva  [dim]{lang}/{result.name}[/dim]")
        else:
            console.print(f"  [red]✗ Falha ao gerar narração [{lang_label}][/red]")
    elif do_narrate and not AI33_API_KEY:
        console.print(f"  [yellow]⚠ AI33_API_KEY não configurada, pulando narração [{lang_label}][/yellow]")

    # --- Dotti Sync + Veo Prompts (EN only) ---
    if lang == "en":
        narration_file = lang_dir / "narration.mp3"

        if do_sync and do_narrate and DOTTI_SYNC_URL:
            if narration_file.exists():
                _step("Dotti Sync")
                sync_path = task_dir / "sync.txt"
                sync_result = generate_sync(narration_file, sync_path)
                if sync_result:
                    console.print(f"  [green]✓[/green] Sync salvo  [dim]{sync_result.name}[/dim]")
                else:
                    console.print(f"  [red]✗ Falha ao gerar sync[/red]")
            else:
                console.print(f"  [yellow]⚠ Narração EN não encontrada, pulando sync[/yellow]")
        elif do_sync and not DOTTI_SYNC_URL:
            console.print(f"  [yellow]⚠ DOTTI_SYNC_URL não configurada, pulando sync[/yellow]")

        # Generate veo_prompts via Gemini (using sync + character history)
        if do_sync and gemini_history:
            sync_file = task_dir / "sync.txt"
            if sync_file.exists():
                _step("Prompts Veo (Gemini)")
                sync_content = sync_file.read_text(encoding="utf-8")
                veo_prompts_text = send_sync_prompts(gemini_history, sync_content)
                if veo_prompts_text:
                    veo_prompts_path.write_text(veo_prompts_text, encoding="utf-8")
                    n = len(re.findall(r"^\*{0,2}PROMPT\s+\d+", veo_prompts_text, re.MULTILINE))
                    console.print(f"  [green]✓[/green] {n} prompts Veo salvos  [dim]{veo_prompts_path.name}[/dim]")
                else:
                    console.print(f"  [red]✗ Falha ao gerar prompts Veo[/red]")

    # --- Video clips ---
    video_dir = lang_dir / "videos"
    if do_videos and WEBHOOK_API_KEY and veo_prompts_path.exists():
        _step(f"Clipes Veo3 [{lang_label}]")
        img_dir = lang_dir / "images"
        char_images = sorted(img_dir.glob("*.png")) if img_dir.exists() else []
        generated_videos = generate_videos(veo_prompts_path, video_dir, image_paths=char_images or None)
        if not generated_videos:
            console.print(f"  [red]✗ Nenhum clipe gerado [{lang_label}][/red]")
    elif do_videos and not veo_prompts_path.exists():
        console.print(f"  [yellow]⚠ veo_prompts.txt não encontrado, pulando vídeos [{lang_label}][/yellow]")

    # --- Final composition ---
    narration_file = lang_dir / "narration.mp3"
    clips = sorted(video_dir.glob("scene_*.mp4")) if video_dir.exists() else []
    if clips and narration_file.exists():
        _step(f"Composição final [{lang_label}] ({len(clips)} clipes)")
        final_path = lang_dir / "final.mp4"
        compose_final_video(
            video_dir, narration_file, final_path,
            num_scenes=len(clips),
            sync_path=None,
        )
    elif clips and not narration_file.exists():
        console.print(f"  [yellow]⚠ Narração não encontrada, pulando composição [{lang_label}][/yellow]")


@app.command()
def run(
    days: int = typer.Option(SEARCH_DAYS, help="Dias para buscar vídeos recentes"),
    count: int = typer.Option(TOP_N, help="Quantidade de vídeos a processar"),
    languages: str = typer.Option("en", help="Idiomas: en,es,ptbr (separados por vírgula)"),
    narrate: bool = typer.Option(True, help="Gerar narração via ai33.pro"),
    characters: bool = typer.Option(True, help="Extrair personagens via Gemini"),
    images: bool = typer.Option(True, help="Gerar imagens dos personagens via webhook"),
    sync: bool = typer.Option(True, help="Gerar sincronização Dotti Sync a partir da narração"),
    videos: bool = typer.Option(True, help="Gerar clipes Veo3 via G-Labs API"),
):
    """Busca shorts recentes, seleciona os mais vistos, transcreve, narra, extrai personagens e gera imagens."""
    channels = load_channels()
    if not channels:
        console.print("[red]Nenhum canal configurado em channels.json[/red]")
        raise typer.Exit(1)

    target_langs = [l.strip() for l in languages.split(",")]
    # Ensure "en" is always first
    if "en" in target_langs:
        target_langs.remove("en")
        target_langs.insert(0, "en")

    lang_label = "[dim]" + ", ".join(LANG_LABELS.get(l, l.upper()) for l in target_langs) + "[/dim]"
    console.print(Rule(f"[bold cyan]auto-reels[/bold cyan]  [dim]{len(channels)} canais · {days} dias · {count} vídeos[/dim]  {lang_label}"))
    console.print()

    all_shorts: list[dict] = []

    for channel in channels:
        console.print(f"  [cyan]{channel.name}[/cyan] [dim]({channel.channel_id})[/dim]")

        video_ids = search_recent_videos(channel.channel_id, days=days)
        console.print(f"    Vídeos encontrados: {len(video_ids)}")

        if not video_ids:
            continue

        details = get_video_details(video_ids)
        shorts = filter_shorts(details)
        console.print(f"    Shorts (<={MAX_SHORT_DURATION_SECONDS}s): {len(shorts)}")
        all_shorts.extend(shorts)

    # Filter out already-processed videos
    processed_ids = load_processed_ids()
    new_shorts = [s for s in all_shorts if s["video_id"] not in processed_ids]
    if processed_ids and len(new_shorts) < len(all_shorts):
        skipped = len(all_shorts) - len(new_shorts)
        console.print(f"\n  [dim]{skipped} vídeo(s) já processado(s), ignorando.[/dim]")

    if not new_shorts:
        console.print("\n[yellow]Nenhum short novo encontrado (todos já processados).[/yellow]")
        raise typer.Exit(0)

    selected = rank_and_select(new_shorts, top_n=count)

    console.print()
    table = Table(title=f"Top {len(selected)} Shorts por Views", border_style="dim")
    table.add_column("#", style="bold", width=3)
    table.add_column("Título")
    table.add_column("Canal", style="cyan")
    table.add_column("Views", justify="right", style="green")
    for i, s in enumerate(selected, 1):
        table.add_row(str(i), s["title"], s["channel_title"], f"{s['view_count']:,}")
    console.print(table)
    console.print()

    # Detect existing task directories to continue numbering
    from auto_reels.config import OUTPUT_DIR
    today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
    today_dir = OUTPUT_DIR / today
    existing = [d for d in today_dir.glob("task-*") if d.is_dir()] if today_dir.exists() else []
    start_number = len(existing) + 1

    for i, video in enumerate(selected, start_number):
        console.print(Rule(f"[bold]Task {i:02d}[/bold]  [dim]{video['title']}[/dim]", style="dim"))

        # 1. Transcription (once)
        _step("Transcrição")
        text = transcribe(video["video_id"])
        if not text:
            console.print(f"  [red]✗ Transcrição indisponível, pulando[/red]\n")
            continue

        path = save_transcription(i, text, video)
        console.print(f"  [green]✓[/green] Transcrição salva  [dim]{path.name}[/dim]")

        # 2. Ensure English text
        narration_text_en = text
        if _detect_language(text) != "en":
            _step("Traduzindo para inglês...")
            narration_text_en = translate_to_en(text)
            console.print(f"  [green]✓[/green] Tradução EN concluída")

        # 3. Character extraction (once)
        chars = None
        gemini_history = []
        if characters and GEMINI_API_KEY:
            _step("Personagens (Gemini)")
            try:
                chars, gemini_history = extract_characters(clean_text(narration_text_en))
            except Exception as e:
                console.print(f"  [red]✗ Gemini indisponível: {e}[/red]")
                chars, gemini_history = None, []
            if chars:
                char_path = save_characters(i, chars)
                console.print(f"  [green]✓[/green] Personagens salvos  [dim]{char_path.name}[/dim]")
            else:
                console.print(f"  [red]✗ Falha ao extrair personagens[/red]")
        elif characters and not GEMINI_API_KEY:
            console.print(f"  [yellow]⚠ GEMINI_API_KEY não configurada, pulando personagens[/yellow]")

        # 4. Generate cultural character variants via Gemini (same conversation)
        cultural_chars = {"en": chars}
        for lang in target_langs:
            culture = CULTURE_MAP.get(lang)
            if culture and gemini_history and chars:
                _step(f"Personagens culturais ({culture})")
                try:
                    culture_chars, gemini_history = generate_cultural_chars(gemini_history, culture)
                except Exception as e:
                    console.print(f"  [red]✗ Gemini indisponível: {e}[/red]")
                    culture_chars = None
                if culture_chars:
                    cultural_chars[lang] = culture_chars
                    console.print(f"  [green]✓[/green] Personagens {culture} gerados")
                else:
                    console.print(f"  [red]✗ Falha ao gerar personagens {culture}[/red]")

        # 5. Generate character images for all languages
        if images and WEBHOOK_API_KEY:
            for lang in target_langs:
                if cultural_chars.get(lang):
                    lang_label_short = LANG_LABELS.get(lang, lang.upper())
                    _step(f"Imagens dos personagens [{lang_label_short}]")
                    img_dir = get_lang_dir(i, lang) / "images"
                    generate_character_images(cultural_chars[lang], img_dir)
        elif images and not WEBHOOK_API_KEY:
            console.print(f"  [yellow]⚠ WEBHOOK_API_KEY não configurada, pulando imagens[/yellow]")

        # 6-16. Process each language (EN first, then others)
        veo_prompts_path = get_task_dir(i) / "veo_prompts.txt"
        for lang in target_langs:
            lang_label_short = LANG_LABELS.get(lang, lang.upper())
            console.print(Rule(f"[dim]{lang_label_short}[/dim]", style="dim", align="left"))
            _process_language(
                i, lang, narration_text_en, gemini_history, veo_prompts_path,
                do_narrate=narrate,
                do_sync=sync,
                do_videos=videos,
            )

        # Mark video as processed
        save_processed_id(video["video_id"])
        console.print()

    console.print(Rule("[bold green]Concluído![/bold green]", style="green"))


@app.command()
def render(
    task: int = typer.Argument(..., help="Número da task (ex: 1)"),
    date: str = typer.Option(None, help="Data da task no formato YYYY-MM-DD (padrão: hoje)"),
    lang: str = typer.Option("en", help="Idioma: en, es, ptbr"),
    subtitles: bool = typer.Option(False, "--subtitles/--no-subtitles", help="Incluir legendas animadas"),
):
    """Renderiza o vídeo final de uma task já processada (clipes + narração + legendas)."""
    from datetime import datetime, timezone
    from auto_reels.config import OUTPUT_DIR

    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    task_dir = OUTPUT_DIR / day / f"task-{task:02d}"

    if not task_dir.exists():
        console.print(f"[red]Task não encontrada: {task_dir}[/red]")
        raise typer.Exit(1)

    lang_label = LANG_LABELS.get(lang, lang.upper())
    console.print(Rule(f"[bold cyan]render[/bold cyan]  [dim]task-{task:02d} · {day} · {lang_label}[/dim]"))

    lang_dir = task_dir / lang
    video_dir = lang_dir / "videos"
    narration_file = lang_dir / "narration.mp3"
    sync_file = task_dir / "sync.txt"
    final_path = lang_dir / "final.mp4"

    clips = sorted(video_dir.glob("scene_*.mp4")) if video_dir.exists() else []

    if not clips:
        console.print(f"  [red]Nenhum clipe encontrado em {video_dir}[/red]")
        raise typer.Exit(1)

    if not narration_file.exists():
        console.print(f"  [red]Narração não encontrada: {narration_file}[/red]")
        raise typer.Exit(1)

    console.print(f"  [dim]{len(clips)} clipes · narração: {narration_file.name}[/dim]")
    if sync_file.exists():
        console.print(f"  [dim]sync: {sync_file.name}[/dim]")

    compose_final_video(
        video_dir, narration_file, final_path,
        num_scenes=len(clips),
        sync_path=sync_file if (subtitles and sync_file.exists()) else None,
    )

    console.print(Rule("[bold green]Concluído![/bold green]", style="green"))
