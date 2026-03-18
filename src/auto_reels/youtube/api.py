from __future__ import annotations

from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from auto_reels.config import YOUTUBE_API_KEY, SEARCH_DAYS


def get_youtube_client():
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY não configurada. Defina no .env")
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def search_recent_videos(channel_id: str, days: int = SEARCH_DAYS) -> list[str]:
    """Return video IDs published in the last `days` days for a channel."""
    youtube = get_youtube_client()
    published_after = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    video_ids: list[str] = []
    page_token: str | None = None

    try:
        while True:
            request = youtube.search().list(
                part="id",
                channelId=channel_id,
                type="video",
                order="date",
                publishedAfter=published_after,
                maxResults=50,
                pageToken=page_token,
            )
            response = request.execute()

            for item in response.get("items", []):
                video_ids.append(item["id"]["videoId"])

            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except HttpError as e:
        if e.resp.status == 403:
            print(f"    [WARN] YouTube quota exceeded for channel {channel_id}, skipping")
        else:
            raise

    return video_ids


def get_video_details(video_ids: list[str]) -> list[dict]:
    """Return video details (duration, views, title) for given IDs."""
    if not video_ids:
        return []

    youtube = get_youtube_client()
    details: list[dict] = []

    # API accepts max 50 IDs per request
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        request = youtube.videos().list(
            part="contentDetails,statistics,snippet",
            id=",".join(batch),
        )
        response = request.execute()

        for item in response.get("items", []):
            details.append(
                {
                    "video_id": item["id"],
                    "title": item["snippet"]["title"],
                    "channel_title": item["snippet"]["channelTitle"],
                    "duration": item["contentDetails"]["duration"],
                    "view_count": int(item["statistics"].get("viewCount", 0)),
                }
            )

    return details
