#!/usr/bin/env python3
"""
TTNiche FYP Bot — GitHub Actions
Scrolls real TikTok For You Page, transcribes with Groq Whisper,
sends to ttniche.com for AI classification.
"""

import asyncio
import os
import sys
import tempfile
import time
import requests
from groq import Groq
from TikTokApi import TikTokApi

# Config from GitHub Secrets (environment variables)
TTNICHE_URL    = os.environ["TTNICHE_URL"]
TTNICHE_SECRET = os.environ["TTNICHE_SECRET"]
GROQ_API_KEY   = os.environ["GROQ_API_KEY"]
MS_TOKEN       = os.environ["MS_TOKEN"]

MIN_PLAYS    = 80_000
MAX_AGE_DAYS = 7
MAX_VIDEOS   = 2  # process max 2 videos per run (keeps job under 5 min)

groq_client = Groq(api_key=GROQ_API_KEY)
cutoff      = time.time() - (MAX_AGE_DAYS * 86400)


def log(msg):
    print(msg, flush=True)


def transcribe(video_url: str) -> str | None:
    try:
        resp = requests.get(video_url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.tiktok.com/",
        })
        if resp.status_code != 200 or len(resp.content) < 10_000:
            return None

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(resp.content)
            tmp = f.name

        with open(tmp, "rb") as f:
            result = groq_client.audio.transcriptions.create(
                file=("video.mp4", f),
                model="whisper-large-v3",
                language="en",
            )
        os.unlink(tmp)
        text = (result.text or "").strip()
        return text if len(text) > 40 else None
    except Exception as e:
        log(f"  [T] Error: {e}")
        return None


def send_to_ttniche(data: dict, transcript: str | None) -> dict:
    try:
        resp = requests.post(
            TTNICHE_URL,
            json={**data, "transcript": transcript or ""},
            headers={"X-Secret": TTNICHE_SECRET},
            timeout=60,
        )
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def main():
    log("=" * 50)
    log(f"TTNiche FYP Bot — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 50)

    processed = 0

    async with TikTokApi() as api:
        await api.create_sessions(
            ms_tokens=[MS_TOKEN],
            num_sessions=1,
            sleep_after=3,
            headless=True,
        )

        async for video in api.trending.videos(count=20):
            if processed >= MAX_VIDEOS:
                break

            vid        = video.as_dict
            vid_id     = str(vid.get("id", ""))
            stats      = vid.get("stats", {})
            plays      = int(stats.get("playCount", 0))
            created    = int(vid.get("createTime", 0))
            author     = vid.get("author", {})
            music      = vid.get("music", {})
            video_info = vid.get("video", {})
            desc       = vid.get("desc", "")

            # Filters
            if not vid_id or plays < MIN_PLAYS:
                continue
            if created and created < cutoff:
                continue

            author_unique = author.get("uniqueId", "")
            video_url     = video_info.get("playAddr", "")
            cover_url     = video_info.get("originCover", "")
            music_orig    = bool(music.get("original", True))

            log(f"\nVIDEO @{author_unique} — {plays:,} plays")
            log(f"  {desc[:100]}")
            log(f"  https://tiktok.com/@{author_unique}/video/{vid_id}")

            # Transcribe only if original audio
            transcript = None
            if music_orig and video_url:
                log("  [T] Transcribing...")
                transcript = await asyncio.to_thread(transcribe, video_url)
                log(f"  [T] {'✓ ' + str(len(transcript)) + ' chars' if transcript else '✗ No speech'}")
            else:
                log("  [T] Skipped (song track)")

            result = send_to_ttniche({
                "video_id":        vid_id,
                "description":     desc,
                "plays":           plays,
                "likes":           int(stats.get("diggCount", 0)),
                "shares":          int(stats.get("shareCount", 0)),
                "comments":        int(stats.get("commentCount", 0)),
                "author_unique":   author_unique,
                "author_nickname": author.get("nickname", ""),
                "author_avatar":   author.get("avatarThumb", ""),
                "cover_url":       cover_url,
                "video_url":       video_url,
                "music_title":     music.get("title", ""),
                "music_original":  music_orig,
                "duration":        int(video_info.get("duration", 0)),
                "created_time":    created,
            }, transcript)

            log(f"  [→] {result.get('status')} — {result.get('message')}")
            processed += 1

    log(f"\nDone — {processed} videos processed.")


if __name__ == "__main__":
    asyncio.run(main())
