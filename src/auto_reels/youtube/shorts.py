from __future__ import annotations

import isodate
from rich.console import Console

from auto_reels.config import MAX_SHORT_DURATION_SECONDS, TOP_N

console = Console()


def filter_shorts(videos: list[dict]) -> list[dict]:
    """Keep only videos with duration <= MAX_SHORT_DURATION_SECONDS."""
    shorts = []
    for video in videos:
        duration = isodate.parse_duration(video["duration"])
        secs = duration.total_seconds()
        if secs <= MAX_SHORT_DURATION_SECONDS:
            shorts.append(video)
        else:
            console.print(f"    [dim]Descartado ({secs:.0f}s): {video['title']}[/dim]")
    return shorts


def rank_and_select(shorts: list[dict], top_n: int = TOP_N) -> list[dict]:
    """Sort by view_count descending and return top_n."""
    sorted_shorts = sorted(shorts, key=lambda v: v["view_count"], reverse=True)
    return sorted_shorts[:top_n]
