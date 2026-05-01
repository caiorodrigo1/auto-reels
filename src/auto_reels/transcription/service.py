from __future__ import annotations

from rich.console import Console

from auto_reels.transcription import ytdlp, rapidapi, youtube_transcript

console = Console(force_terminal=True)


def transcribe(video_id: str) -> str | None:
    """Try yt-dlp first, then RapidAPI, then youtube-transcript-api."""
    text = ytdlp.fetch_transcript(video_id)
    if text:
        console.print(f"  [green]Transcrição obtida via yt-dlp[/green]")
        return text

    console.print(f"  [yellow]Fallback para RapidAPI...[/yellow]")
    text = rapidapi.fetch_transcript(video_id)
    if text:
        console.print(f"  [green]Transcrição obtida via RapidAPI[/green]")
        return text

    console.print(f"  [yellow]Fallback para youtube-transcript-api...[/yellow]")
    text = youtube_transcript.fetch_transcript(video_id)
    if text:
        console.print(f"  [green]Transcrição obtida via youtube-transcript-api[/green]")
        return text

    console.print(f"  [red]Não foi possível transcrever {video_id}[/red]")
    return None
