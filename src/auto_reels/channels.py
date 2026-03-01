from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from auto_reels.config import CHANNELS_FILE


@dataclass
class Channel:
    name: str
    channel_id: str


def load_channels(path: Path = CHANNELS_FILE) -> list[Channel]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Channel(name=ch["name"], channel_id=ch["channel_id"]) for ch in data["channels"]]
