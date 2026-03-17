from __future__ import annotations

import re
import typer
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from auto_reels.channels import load_channels
from auto_reels.youtube.api import search_recent_videos, get_video_details
from auto_reels.youtube.shorts import filter_shorts, rank_and_select
from auto_reels.transcription.service import transcribe
from auto_reels.narration.elevenlabs import generate_speech
from auto_reels.gemini.agent import extract_characters, send_sync_prompts, translate_to_ptbr, _detect_language
from auto_reels.image_gen.webhook import generate_character_images
from auto_reels.sync.dotti import generate_sync
from auto_reels.video_gen.glabs import generate_videos
from auto_reels.editing.compose import compose_final_video
from auto_reels.output import (
    save_transcription, get_narration_path, save_characters,
    get_task_dir, clean_text,
)
from auto_reels.config import SEARCH_DAYS, TOP_N, MAX_SHORT_DURATION_SECONDS, AI33_API_KEY, GEMINI_API_KEY, WEBHOOK_API_KEY, DOTTI_SYNC_URL

app = typer.Typer(name="auto-reels", help="Pipeline de YouTube Shorts + transcrição + narração + personagens + imagens")
console = Console()


def _step(label: str, icon: str = "•"):
    console.print(f"  [bold cyan]{icon} {label}[/bold cyan]")


@app.command()
def run(
    days: int = typer.Option(SEARCH_DAYS, help="Dias para buscar vídeos recentes"),
    count: int = typer.Option(TOP_N, help="Quantidade de vídeos a processar"),
    english: bool = typer.Option(True, "--english/--ptbr", help="Manter narração em inglês (sem tradução para pt-BR)"),
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

    lang_label = "[dim]EN[/dim]" if english else "[dim]PT-BR[/dim]"
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

    if not all_shorts:
        console.print("\n[yellow]Nenhum short encontrado.[/yellow]")
        raise typer.Exit(0)

    selected = rank_and_select(all_shorts, top_n=count)

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

    for i, video in enumerate(selected, 1):
        console.print(Rule(f"[bold]Task {i:02d}[/bold]  [dim]{video['title']}[/dim]", style="dim"))
        _step("Transcrição")
        text = transcribe(video["video_id"])
        if not text:
            console.print(f"  [red]✗ Transcrição indisponível, pulando[/red]\n")
            continue

        path = save_transcription(i, text, video)
        console.print(f"  [green]✓[/green] Transcrição salva  [dim]{path.name}[/dim]")

        # Tradução da narração se roteiro estiver em inglês e flag --ptbr ativa
        narration_text = text
        if not english and _detect_language(text) == "en":
            _step("Traduzindo narração para pt-BR...")
            narration_text = translate_to_ptbr(text)
            console.print(f"  [green]✓[/green] Tradução concluída")

        # Narração
        if narrate and AI33_API_KEY:
            _step("Narração (ElevenLabs)")
            narration_path = get_narration_path(i)
            result = generate_speech(clean_text(narration_text), narration_path)
            if result:
                console.print(f"  [green]✓[/green] Narração salva  [dim]{result.name}[/dim]")
            else:
                console.print(f"  [red]✗ Falha ao gerar narração[/red]")
        elif narrate and not AI33_API_KEY:
            console.print(f"  [yellow]⚠ AI33_API_KEY não configurada, pulando narração[/yellow]")

        # Dotti Sync
        if sync and narrate and DOTTI_SYNC_URL:
            narration_file = get_narration_path(i)
            if narration_file.exists():
                _step("Dotti Sync")
                sync_path = get_task_dir(i) / "sync.txt"
                sync_result = generate_sync(narration_file, sync_path)
                if sync_result:
                    console.print(f"  [green]✓[/green] Sync salvo  [dim]{sync_result.name}[/dim]")
                else:
                    console.print(f"  [red]✗ Falha ao gerar sync[/red]")
            else:
                console.print(f"  [yellow]⚠ Narração não encontrada, pulando sync[/yellow]")
        elif sync and not DOTTI_SYNC_URL:
            console.print(f"  [yellow]⚠ DOTTI_SYNC_URL não configurada, pulando sync[/yellow]")

        # Extração de personagens
        chars = None
        gemini_history = []
        if characters and GEMINI_API_KEY:
            _step("Personagens (Gemini)")
            chars, gemini_history = extract_characters(clean_text(text))
            if chars:
                char_path = save_characters(i, chars)
                console.print(f"  [green]✓[/green] Personagens salvos  [dim]{char_path.name}[/dim]")
            else:
                console.print(f"  [red]✗ Falha ao extrair personagens[/red]")
        elif characters and not GEMINI_API_KEY:
            console.print(f"  [yellow]⚠ GEMINI_API_KEY não configurada, pulando personagens[/yellow]")

        # Geração de imagens
        if images and chars and WEBHOOK_API_KEY:
            _step("Imagens dos personagens")
            task_dir = get_task_dir(i)
            img_dir = task_dir / "images"
            generated = generate_character_images(chars, img_dir)
        elif images and not WEBHOOK_API_KEY:
            console.print(f"  [yellow]⚠ WEBHOOK_API_KEY não configurada, pulando imagens[/yellow]")

        # Gerar veo_prompts.txt via Gemini (usando histórico da extração de personagens)
        veo_prompts_path = get_task_dir(i) / "veo_prompts.txt"
        if sync and gemini_history:
            sync_file = get_task_dir(i) / "sync.txt"
            if sync_file.exists():
                _step("Prompts Veo (Gemini)")
                sync_content = sync_file.read_text(encoding="utf-8")
                veo_prompts_text = send_sync_prompts(gemini_history, sync_content)
                if veo_prompts_text:
                    veo_prompts_path.write_text(veo_prompts_text, encoding="utf-8")
                    n = len(re.findall(r"^PROMPT\s+\d+", veo_prompts_text, re.MULTILINE))
                    console.print(f"  [green]✓[/green] {n} prompts Veo salvos  [dim]{veo_prompts_path.name}[/dim]")
                else:
                    console.print(f"  [red]✗ Falha ao gerar prompts Veo[/red]")

        # Geração de clipes via G-Labs API
        video_dir = get_task_dir(i) / "videos"
        if videos and WEBHOOK_API_KEY and veo_prompts_path.exists():
            _step("Clipes Veo3 (G-Labs)")
            img_dir = get_task_dir(i) / "images"
            char_images = sorted(img_dir.glob("*.png")) if img_dir.exists() else []
            generated_videos = generate_videos(veo_prompts_path, video_dir, image_paths=char_images or None)
            if not generated_videos:
                console.print(f"  [red]✗ Nenhum clipe gerado[/red]")
        elif videos and not veo_prompts_path.exists():
            console.print(f"  [yellow]⚠ veo_prompts.txt não encontrado, pulando geração de vídeos[/yellow]")

        # Composição final: clipes + narração
        narration_file = get_narration_path(i)
        clips = sorted(video_dir.glob("scene_*.mp4")) if video_dir.exists() else []
        if clips and narration_file.exists():
            _step(f"Composição final ({len(clips)} clipes)")
            final_path = get_task_dir(i) / "final.mp4"
            sync_file = get_task_dir(i) / "sync.txt"
            compose_final_video(
                video_dir, narration_file, final_path,
                num_scenes=len(clips),
                sync_path=None,
            )
        elif clips and not narration_file.exists():
            console.print(f"  [yellow]⚠ Narração não encontrada, pulando composição[/yellow]")

        console.print()

    console.print(Rule("[bold green]Concluído![/bold green]", style="green"))


@app.command()
def render(
    task: int = typer.Argument(..., help="Número da task (ex: 1)"),
    date: str = typer.Option(None, help="Data da task no formato YYYY-MM-DD (padrão: hoje)"),
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

    console.print(Rule(f"[bold cyan]render[/bold cyan]  [dim]task-{task:02d} · {day}[/dim]"))

    video_dir = task_dir / "videos"
    narration_file = task_dir / "narration.mp3"
    sync_file = task_dir / "sync.txt"
    final_path = task_dir / "final.mp4"

    clips = sorted(video_dir.glob("scene_*.mp4")) if video_dir.exists() else []

    if not clips:
        console.print(f"  [red]Nenhum clipe encontrado em {video_dir}[/red]")
        raise typer.Exit(1)

    if not narration_file.exists():
        console.print(f"  [red]Narração não encontrada: {narration_file}[/red]")
        raise typer.Exit(1)

    console.print(f"  [dim]{len(clips)} clipes · narração: {narration_file.name}[/dim]")
    if sync_file.exists():
        console.print(f"  [dim]sync: {sync_file.name} (legendas ativas)[/dim]")

    compose_final_video(
        video_dir, narration_file, final_path,
        num_scenes=len(clips),
        sync_path=sync_file if (subtitles and sync_file.exists()) else None,
    )

    console.print(Rule("[bold green]Concluído![/bold green]", style="green"))
