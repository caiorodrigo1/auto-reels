from __future__ import annotations

from youtube_transcript_api import YouTubeTranscriptApi


def fetch_transcript(video_id: str) -> str | None:
    """Fetch transcript using youtube-transcript-api. Returns plain text or None."""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Try Portuguese first, then any language
        try:
            transcript = transcript_list.find_transcript(["pt", "pt-BR"])
        except Exception:
            transcript = transcript_list.find_transcript(
                [t.language_code for t in transcript_list]
            )

        fetched = transcript.fetch()
        return "\n".join(snippet.text for snippet in fetched)
    except Exception:
        return None
