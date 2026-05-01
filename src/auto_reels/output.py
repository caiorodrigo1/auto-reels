from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from auto_reels.config import OUTPUT_DIR

PROCESSED_FILE = OUTPUT_DIR / "processed.json"


def load_processed_ids() -> set[str]:
    """Load set of already-processed video IDs."""
    if PROCESSED_FILE.exists():
        data = json.loads(PROCESSED_FILE.read_text(encoding="utf-8"))
        return set(data)
    return set()


def save_processed_id(video_id: str) -> None:
    """Append a video ID to the processed list."""
    ids = load_processed_ids()
    ids.add(video_id)
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_FILE.write_text(json.dumps(sorted(ids), indent=2), encoding="utf-8")


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


def get_narration_en_path(task_number: int) -> Path:
    """Return the path for the English narration audio file (used for Dotti Sync)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    task_dir = OUTPUT_DIR / today / f"task-{task_number:02d}"
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir / "narration_en.mp3"


def get_narration_path(task_number: int) -> Path:
    """Return the path for the narration audio file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    task_dir = OUTPUT_DIR / today / f"task-{task_number:02d}"
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir / "narration.mp3"


def get_task_dir(task_number: int) -> Path:
    """Return the task directory path for today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    task_dir = OUTPUT_DIR / today / f"task-{task_number:02d}"
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir


def get_lang_dir(task_number: int, lang: str) -> Path:
    """Return the language-specific subdirectory for a task (e.g. task-01/en/)."""
    task_dir = get_task_dir(task_number)
    lang_dir = task_dir / lang
    lang_dir.mkdir(parents=True, exist_ok=True)
    return lang_dir


def save_characters(task_number: int, text: str) -> Path:
    """Save extracted characters to output/YYYY-MM-DD/task-NN/characters.txt."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    task_dir = OUTPUT_DIR / today / f"task-{task_number:02d}"
    task_dir.mkdir(parents=True, exist_ok=True)
    file_path = task_dir / "characters.txt"
    file_path.write_text(text, encoding="utf-8")
    return file_path
