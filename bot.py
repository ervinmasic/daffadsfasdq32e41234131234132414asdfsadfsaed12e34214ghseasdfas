#!/usr/bin/env python3
"""
TTNiche FYP Bot — GitHub Actions
Fetches trending TikTok videos via tikwm API (no browser needed),
transcribes with Groq Whisper, sends to ttniche.com for AI classification.
"""

import os
import sys
import time
import random
import tempfile
import requests
from groq import Groq

# ── Config from GitHub Secrets ────────────────────────────────────────────────
TTNICHE_URL    = os.environ["TTNICHE_URL"]
TTNICHE_SECRET = os.environ["TTNICHE_SECRET"]
GROQ_API_KEY   = os.environ["GROQ_API_KEY"]
TIKWM_API_KEY  = os.environ["TIKWM_API_KEY"]

MIN_PLAYS    = 80_000
MAX_AGE_DAYS = 7
MAX_VIDEOS   = 6   # process max 6 videos per run

groq_client = Groq(api_key=GROQ_API_KEY)
cutoff      = time.time() - (MAX_AGE_DAYS * 86400)

# Rotating hashtag pool — simulates FYP diversity
HASHTAG_POOL = [
    "fyp", "foryou", "foryoupage", "viral", "trending",
    "finance", "money", "investment", "sidehustle",
    "gym", "fitness", "workout", "motivation",
    "cooking", "recipe", "food", "healthyfood",
    "tech", "ai", "chatgpt", "coding",
    "fashion", "ootd", "style", "outfit",
    "beauty", "skincare", "makeup", "glow",
    "travel", "adventure", "vanlife", "roadtrip",
    "gaming", "minecraft", "roblox", "pcgaming",
    "comedy", "funny", "memes", "prank",
    "pets", "cats", "dogs", "animals",
    "asmr", "satisfying", "oddlysatisfying",
    "mindset", "discipline", "sigma", "selfimprovement",
    "crypto", "stocks", "daytrading", "budgeting",
    "diy", "crafts", "homedecor", "renovation",
    "dance", "music", "cover", "acoustic",
    "truecrime", "horror", "mystery", "storytime",
]

def log(msg):
    print(msg, flush=True)

def fetch_trending(hashtag: str, count: int = 20) -> list:
    """Fetch trending videos for a hashtag via tikwm."""
    try:
        url = "https://www.tikwm.com/api/feed/search"
        r = requests.get(url, params={
            "keywords": hashtag,
            "count": count,
            "region": "US",
            "api_key": TIKWM_API_KEY,
        }, timeout=20)
        data = r.json()
        return data.get("data", {}).get("videos", []) or []
    except Exception as e:
        log(f"  [tikwm] Error fetching #{hashtag}: {e}")
        return []

def transcribe(video_url: str) -> str | None:
    """Download video and transcribe via Groq Whisper."""
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
            )
        os.unlink(tmp)
        text = (result.text or "").strip()
        return text if len(text) > 40 else None
    except Exception as e:
        log(f"  [T] Error: {e}")
        return None

def send_to_ttniche(video: dict, transcript: str | None) -> dict:
    """Send video data + transcript to ingest.php."""
    try:
        resp = requests.post(
            TTNICHE_URL,
            json={
                "video_id":        str(video.get("video_id", "")),
                "description":     video.get("title", ""),
                "plays":           int(video.get("play_count", 0)),
                "likes":           int(video.get("digg_count", 0)),
                "shares":          int(video.get("share_count", 0)),
                "comments":        int(video.get("comment_count", 0)),
                "author_unique":   video.get("author", {}).get("unique_id", ""),
                "author_nickname": video.get("author", {}).get("nickname", ""),
                "author_avatar":   video.get("author", {}).get("avatar", ""),
                "cover_url":       video.get("cover", ""),
                "video_url":       video.get("play", ""),
                "music_title":     video.get("music_info", {}).get("title", ""),
                "duration":        int(video.get("duration", 0)),
                "created_time":    int(video.get("create_time", 0)),
                "transcript":      transcript or "",
            },
            headers={"X-Secret": TTNICHE_SECRET},
            timeout=60,
        )
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def main():
    log("=" * 50)
    log(f"TTNiche FYP Bot — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 50)

    # Pick 3 random hashtags this run
    hashtags = random.sample(HASHTAG_POOL, 3)
    log(f"Hashtags this run: {hashtags}")

    seen_ids  = set()
    processed = 0

    for tag in hashtags:
        if processed >= MAX_VIDEOS:
            break

        log(f"\n── #{tag} ──────────────────────────")
        videos = fetch_trending(tag, count=15)
        log(f"  Fetched {len(videos)} videos")

        for video in videos:
            if processed >= MAX_VIDEOS:
                break

            vid_id  = str(video.get("video_id", ""))
            plays   = int(video.get("play_count", 0))
            created = int(video.get("create_time", 0))

            if not vid_id or vid_id in seen_ids:
                continue
            if plays < MIN_PLAYS:
                continue
            if created and created < cutoff:
                continue

            seen_ids.add(vid_id)

            author  = video.get("author", {})
            desc    = video.get("title", "")
            vid_url = video.get("play", "")

            log(f"\n  VIDEO @{author.get('unique_id','')} — {plays:,} plays")
            log(f"  {desc[:100]}")

            # Transcribe
            transcript = None
            if vid_url:
                log("  [T] Transcribing...")
                transcript = transcribe(vid_url)
                log(f"  [T] {'✓ ' + str(len(transcript)) + ' chars' if transcript else '✗ No speech detected'}")

            result = send_to_ttniche(video, transcript)
            log(f"  [→] {result.get('status')} — {result.get('message','')}")
            processed += 1

    log(f"\n{'='*50}")
    log(f"Done — {processed} videos processed.")

if __name__ == "__main__":
    main()
