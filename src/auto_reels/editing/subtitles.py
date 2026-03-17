from __future__ import annotations

import re
from pathlib import Path

WORDS_PER_LINE = 4
FONT_SIZE = 75


def sync_to_ass(sync_path: Path, ass_path: Path) -> Path | None:
    """Convert sync.txt blocks to an ASS subtitle file with pop animation."""
    blocks = _parse_sync(sync_path)
    if not blocks:
        return None

    dialogues = _build_dialogues(blocks)
    content = _ass_header() + "\n".join(dialogues) + "\n"
    ass_path.write_text(content, encoding="utf-8")
    return ass_path


def _parse_sync(sync_path: Path) -> list[dict]:
    text = sync_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"PROMPT\s+\d+\s*\|\s*(\d+:\d+)\s*-\s*(\d+:\d+)\n(.+?)(?=\n-{10,})",
        re.DOTALL,
    )
    blocks = []
    for m in pattern.finditer(text):
        content = m.group(3).strip()
        if not content:
            continue
        blocks.append({
            "start": _ts_to_s(m.group(1)),
            "end": _ts_to_s(m.group(2)),
            "text": content,
        })
    return blocks


def _ts_to_s(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def _s_to_ass(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def _build_dialogues(blocks: list[dict]) -> list[str]:
    dialogues = []
    for block in blocks:
        words = block["text"].split()
        if not words:
            continue
        chunks = [words[i:i + WORDS_PER_LINE] for i in range(0, len(words), WORDS_PER_LINE)]
        duration = block["end"] - block["start"]
        time_per_chunk = duration / len(chunks)

        for j, chunk in enumerate(chunks):
            start = block["start"] + j * time_per_chunk
            end = start + time_per_chunk
            text = " ".join(chunk)
            # Pop-in animation: scale 0→100% in 120ms, then scale back at end
            animated = r"{\an2\fscx0\fscy0\t(0,120,\fscx100\fscy100)}" + text
            dialogues.append(
                f"Dialogue: 0,{_s_to_ass(start)},{_s_to_ass(end)},Default,,0,0,0,,{animated}"
            )
    return dialogues


def _ass_header() -> str:
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 720\n"
        "PlayResY: 1280\n"
        "WrapStyle: 1\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial,{FONT_SIZE},&H00FFFFFF,&H000000FF,&H00000000,&HAA000000,"
        "-1,0,0,0,100,100,0,0,1,4,1,2,20,20,100,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
