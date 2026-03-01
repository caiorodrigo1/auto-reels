from __future__ import annotations

import yt_dlp


def fetch_transcript(video_id: str) -> str | None:
    """Extract subtitles using yt-dlp. Returns plain text or None."""
    url = f"https://www.youtube.com/watch?v={video_id}"

    opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["pt", "pt-BR", "en"],
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        subs = info.get("subtitles", {})
        auto_subs = info.get("automatic_captions", {})

        # Prefer manual subs, then auto-generated
        for lang in ["pt", "pt-BR", "en"]:
            for source in [subs, auto_subs]:
                if lang in source:
                    for fmt in source[lang]:
                        if fmt.get("ext") == "json3":
                            return _extract_text_from_json3(ydl, fmt["url"])
                    # Fallback: use first available format
                    sub_url = source[lang][0]["url"]
                    return _fetch_sub_text(ydl, sub_url)

        return None
    except Exception:
        return None


def _extract_text_from_json3(ydl: yt_dlp.YoutubeDL, url: str) -> str | None:
    """Download json3 subtitle and extract text."""
    import json

    try:
        data = ydl.urlopen(url).read().decode("utf-8")
        parsed = json.loads(data)
        lines = []
        for event in parsed.get("events", []):
            segs = event.get("segs", [])
            text = "".join(s.get("utf8", "") for s in segs).strip()
            if text and text != "\n":
                lines.append(text)
        return "\n".join(lines)
    except Exception:
        return None


def _fetch_sub_text(ydl: yt_dlp.YoutubeDL, url: str) -> str | None:
    """Download subtitle and return raw text."""
    try:
        data = ydl.urlopen(url).read().decode("utf-8")
        # Strip basic XML/VTT tags
        import re
        text = re.sub(r"<[^>]+>", "", data)
        text = re.sub(r"WEBVTT.*?\n\n", "", text)
        text = re.sub(r"\d{2}:\d{2}[\d:.,\s->]+\n", "", text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)
    except Exception:
        return None
