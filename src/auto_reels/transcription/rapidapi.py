from __future__ import annotations

import json
import subprocess

from auto_reels.config import RAPIDAPI_HOST, RAPIDAPI_KEY


def fetch_transcript(video_id: str) -> str | None:
    """Fetch transcript via RapidAPI using curl. Returns plain text or None."""
    if not RAPIDAPI_KEY:
        return None

    url = f"https://{RAPIDAPI_HOST}/api/transcript?videoId={video_id}&lang=auto&flat_text=true"

    print(f"    [DEBUG] url: {url}")
    print(f"    [DEBUG] key: {RAPIDAPI_KEY[:10]}...")
    print(f"    [DEBUG] host: {RAPIDAPI_HOST}")

    try:
        result = subprocess.run(
            [
                "curl", "-v", "--max-time", "30",
                url,
                "-H", f"x-rapidapi-key: {RAPIDAPI_KEY}",
                "-H", f"x-rapidapi-host: {RAPIDAPI_HOST}",
                "-H", "Accept: application/json, text/plain, */*",
                "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "-H", "Origin: http://localhost:5173",
                "-H", "Referer: http://localhost:5173/",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )

        print(f"    [DEBUG] curl returncode={result.returncode}")
        print(f"    [DEBUG] curl stderr: {result.stderr[:1000]}")
        print(f"    [DEBUG] curl stdout: {result.stdout[:300]}")

        if not result.stdout.strip():
            print("    [DEBUG] empty response")
            return None

        data = json.loads(result.stdout)

        if not data.get("success"):
            print(f"    [DEBUG] success=false: {data}")
            return None

        transcript = data.get("transcript")
        if isinstance(transcript, str):
            return transcript
        if isinstance(transcript, list):
            return "\n".join(item.get("text", "") for item in transcript)
        return None
    except Exception as e:
        print(f"    [DEBUG] RapidAPI exception: {e}")
        return None
