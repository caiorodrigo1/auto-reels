from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
CHANNELS_FILE = PROJECT_ROOT / "channels.json"

YOUTUBE_API_KEY: str = os.environ.get("YOUTUBE_API_KEY", "")
RAPIDAPI_KEY: str = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_HOST: str = os.environ.get(
    "RAPIDAPI_HOST", "youtube-transcript3.p.rapidapi.com"
)

AI33_API_KEY: str = os.environ.get("AI33_API_KEY", "")
AI33_VOICE_ID: str = os.environ.get("AI33_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")

SEARCH_DAYS = 7
TOP_N = 2
MAX_SHORT_DURATION_SECONDS = 180
