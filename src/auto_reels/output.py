from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from auto_reels.config import OUTPUT_DIR, PROJECT_ROOT

SEEN_FILE = PROJECT_ROOT / "seen_videos.json"


def load_seen() -> set[str]:
    """Load set of already-processed video IDs."""
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def mark_seen(video_id: str) -> None:
    """Add a video ID to the seen registry."""
    seen = load_seen()
    seen.add(video_id)
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")


def clean_text(text: str) -> str:
    """Remove HTML entities, tags, and stray symbols from transcript text."""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r">{1,}", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def save_transcription(task_number: int, text: str, video: dict) -> Path:
    """Save transcription to output/YYYY-MM-DD/task-NN/transcription.txt."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    task_dir = OUTPUT_DIR / today / f"task-{task_number:02d}"
    task_dir.mkdir(parents=True, exist_ok=True)

    header = f"# {video['title']}\n# Canal: {video['channel_title']}\n# https://youtube.com/watch?v={video['video_id']}\n# Views: {video['view_count']}\n\n"

    file_path = task_dir / "transcription.txt"
    file_path.write_text(header + clean_text(text), encoding="utf-8")
    return file_path


def get_narration_path(task_number: int) -> Path:
    """Return the path for the narration audio file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    task_dir = OUTPUT_DIR / today / f"task-{task_number:02d}"
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir / "narration.mp3"


def get_next_task_number() -> int:
    """Return the next task number based on existing task dirs for today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_dir = OUTPUT_DIR / today
    if not today_dir.exists():
        return 1
    existing = [
        d for d in today_dir.iterdir()
        if d.is_dir() and d.name.startswith("task-")
    ]
    if not existing:
        return 1
    numbers = []
    for d in existing:
        try:
            numbers.append(int(d.name.split("-")[1]))
        except (IndexError, ValueError):
            pass
    return max(numbers) + 1 if numbers else 1


def get_task_dir(task_number: int) -> Path:
    """Return the task directory path for today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    task_dir = OUTPUT_DIR / today / f"task-{task_number:02d}"
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir


def save_characters(task_number: int, text: str) -> Path:
    """Save extracted characters to output/YYYY-MM-DD/task-NN/characters.txt."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    task_dir = OUTPUT_DIR / today / f"task-{task_number:02d}"
    task_dir.mkdir(parents=True, exist_ok=True)
    file_path = task_dir / "characters.txt"
    file_path.write_text(text, encoding="utf-8")
    return file_path
