from __future__ import annotations

from youtube_transcript_api import YouTubeTranscriptApi


def fetch_transcript(video_id: str) -> str | None:
    """Fetch transcript using youtube-transcript-api. Returns plain text or None."""
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        # Try Portuguese first, then any language
        try:
            transcript = transcript_list.find_transcript(["pt", "pt-BR"])
        except Exception:
            transcript = transcript_list.find_transcript(
                [t.language_code for t in transcript_list]
            )

        fetched = transcript.fetch()
        return "\n".join(snippet.text for snippet in fetched.snippets)
    except Exception as e:
        print(f"    [DEBUG] youtube-transcript-api: {e}")
        return None
