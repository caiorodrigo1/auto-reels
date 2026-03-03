from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from auto_reels.channels import load_channels
from auto_reels.youtube.api import search_recent_videos, get_video_details
from auto_reels.youtube.shorts import filter_shorts, rank_and_select
from auto_reels.transcription.service import transcribe
from auto_reels.narration.elevenlabs import generate_speech
from auto_reels.gemini.agent import extract_characters
from auto_reels.image_gen.webhook import generate_character_images
from auto_reels.output import (
    save_transcription, get_narration_path, save_characters,
    get_task_dir, clean_text,
)
from auto_reels.config import SEARCH_DAYS, TOP_N, AI33_API_KEY, GEMINI_API_KEY, WEBHOOK_API_KEY

app = typer.Typer(name="auto-reels", help="Pipeline de YouTube Shorts + transcrição + narração + personagens + imagens")
console = Console()


@app.command()
def run(
    days: int = typer.Option(SEARCH_DAYS, help="Dias para buscar vídeos recentes"),
    top: int = typer.Option(TOP_N, help="Quantidade de shorts para transcrever"),
    narrate: bool = typer.Option(True, help="Gerar narração via ai33.pro"),
    characters: bool = typer.Option(True, help="Extrair personagens via Gemini"),
    images: bool = typer.Option(True, help="Gerar imagens dos personagens via webhook"),
):
    """Busca shorts recentes, seleciona os mais vistos, transcreve, narra, extrai personagens e gera imagens."""
    channels = load_channels()
    if not channels:
        console.print("[red]Nenhum canal configurado em channels.json[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Buscando shorts dos últimos {days} dias em {len(channels)} canal(is)...[/bold]\n")

    all_shorts: list[dict] = []

    for channel in channels:
        console.print(f"[cyan]{channel.name}[/cyan] ({channel.channel_id})")

        video_ids = search_recent_videos(channel.channel_id, days=days)
        console.print(f"  Vídeos encontrados: {len(video_ids)}")

        if not video_ids:
            continue

        details = get_video_details(video_ids)
        shorts = filter_shorts(details)
        console.print(f"  Shorts (≤60s): {len(shorts)}")
        all_shorts.extend(shorts)

    if not all_shorts:
        console.print("\n[yellow]Nenhum short encontrado.[/yellow]")
        raise typer.Exit(0)

    selected = rank_and_select(all_shorts, top_n=top)

    table = Table(title=f"\nTop {len(selected)} Shorts por Views")
    table.add_column("#", style="bold")
    table.add_column("Título")
    table.add_column("Canal")
    table.add_column("Views", justify="right")
    for i, s in enumerate(selected, 1):
        table.add_row(str(i), s["title"], s["channel_title"], f"{s['view_count']:,}")
    console.print(table)

    console.print("\n[bold]Transcrevendo...[/bold]\n")

    for i, video in enumerate(selected, 1):
        console.print(f"[bold]Task {i:02d}:[/bold] {video['title']}")
        text = transcribe(video["video_id"])
        if not text:
            console.print(f"  [red]Transcrição indisponível, pulando.[/red]\n")
            continue

        path = save_transcription(i, text, video)
        console.print(f"  [green]Transcrição salva em {path}[/green]")

        # Narração
        if narrate and AI33_API_KEY:
            console.print(f"  Gerando narração...")
            narration_path = get_narration_path(i)
            result = generate_speech(clean_text(text), narration_path)
            if result:
                console.print(f"  [green]Narração salva em {result}[/green]")
            else:
                console.print(f"  [red]Falha ao gerar narração.[/red]")
        elif narrate and not AI33_API_KEY:
            console.print(f"  [yellow]AI33_API_KEY não configurada, pulando narração.[/yellow]")

        # Extração de personagens
        chars = None
        if characters and GEMINI_API_KEY:
            console.print(f"  Extraindo personagens via Gemini...")
            chars = extract_characters(clean_text(text))
            if chars:
                char_path = save_characters(i, chars)
                console.print(f"  [green]Personagens salvos em {char_path}[/green]")
            else:
                console.print(f"  [red]Falha ao extrair personagens.[/red]")
        elif characters and not GEMINI_API_KEY:
            console.print(f"  [yellow]GEMINI_API_KEY não configurada, pulando personagens.[/yellow]")

        # Geração de imagens
        if images and chars and WEBHOOK_API_KEY:
            console.print(f"  Gerando imagens dos personagens...")
            task_dir = get_task_dir(i)
            img_dir = task_dir / "images"
            generated = generate_character_images(chars, img_dir)
            console.print(f"  [green]{len(generated)} imagens geradas em {img_dir}[/green]")
        elif images and not WEBHOOK_API_KEY:
            console.print(f"  [yellow]WEBHOOK_API_KEY não configurada, pulando imagens.[/yellow]")

        console.print()

    console.print("[bold green]Concluído![/bold green]")
