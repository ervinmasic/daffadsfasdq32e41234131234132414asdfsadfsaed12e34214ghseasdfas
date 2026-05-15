#!/usr/bin/env python3
"""
TTNiche FYP Bot — Playwright edition
Otvara tiktok.com, interceptuje interne API pozive i skuplja FYP videe.
Radi bez TikTok account sessiona.
"""

import os
import sys
import json
import time
import random
import asyncio
import tempfile
import requests
from groq import Groq
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# ── Config ────────────────────────────────────────────────────────────────────
TTNICHE_URL    = os.environ["TTNICHE_URL"]
TTNICHE_SECRET = os.environ["TTNICHE_SECRET"]
GROQ_API_KEY   = os.environ["GROQ_API_KEY"]

MIN_PLAYS    = 50_000
MAX_AGE_DAYS = 14
MAX_VIDEOS   = 25

groq_client = Groq(api_key=GROQ_API_KEY)
cutoff      = time.time() - (MAX_AGE_DAYS * 86400)
seen_ids    = set()
collected   = []

def log(msg):
    print(msg, flush=True)

# ── Intercept TikTok internal API responses ───────────────────────────────────
async def handle_response(response):
    """Catch TikTok's internal item_list API responses."""
    try:
        url = response.url
        # TikTok FYP endpoint
        if "item_list" not in url and "recommend" not in url and "feed" not in url:
            return
        if response.status != 200:
            return

        body = await response.body()
        data = json.loads(body)

        items = (
            data.get("itemList") or
            data.get("item_list") or
            data.get("data", {}).get("items") or
            data.get("data", {}).get("videos") or
            []
        )

        for item in items:
            vid_id = str(item.get("id", "") or item.get("video_id", ""))
            if not vid_id or vid_id in seen_ids:
                continue

            stats  = item.get("stats", {}) or item.get("statistics", {})
            plays  = int(stats.get("playCount", 0) or stats.get("play_count", 0) or 0)
            likes  = int(stats.get("diggCount", 0) or stats.get("like_count", 0) or 0)
            shares = int(stats.get("shareCount", 0) or stats.get("share_count", 0) or 0)
            comments = int(stats.get("commentCount", 0) or stats.get("comment_count", 0) or 0)

            if plays < MIN_PLAYS:
                continue

            create_time = int(item.get("createTime", 0) or item.get("create_time", 0) or 0)
            if create_time and create_time < cutoff:
                continue

            author = item.get("author", {}) or {}
            video  = item.get("video", {}) or {}
            music  = item.get("music", {}) or {}
            desc   = item.get("desc", "") or ""

            cover = (
                video.get("cover") or
                video.get("dynamicCover") or
                video.get("originCover") or
                item.get("cover_url", "") or ""
            )
            vid_url = (
                video.get("playAddr") or
                video.get("downloadAddr") or
                item.get("play", "") or ""
            )

            seen_ids.add(vid_id)
            collected.append({
                "video_id":        vid_id,
                "description":     desc,
                "plays":           plays,
                "likes":           likes,
                "shares":          shares,
                "comments":        comments,
                "author_unique":   author.get("uniqueId", "") or author.get("unique_id", ""),
                "author_nickname": author.get("nickname", ""),
                "author_avatar":   author.get("avatarThumb", "") or author.get("avatar", ""),
                "cover_url":       cover,
                "video_url":       vid_url,
                "music_title":     music.get("title", ""),
                "duration":        int(video.get("duration", 0) or 0),
                "created_time":    create_time,
            })
            log(f"  [+] @{author.get('uniqueId','?')} — {plays:,} plays — {desc[:60]}")

    except Exception as e:
        pass  # silently skip parse errors


# ── Transcribe via Groq Whisper ───────────────────────────────────────────────
def transcribe(video_url: str) -> str | None:
    if not video_url:
        return None
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


# ── Send to TTNiche ───────────────────────────────────────────────────────────
def send_to_ttniche(video: dict, transcript: str | None) -> dict:
    try:
        payload = {**video, "transcript": transcript or ""}
        resp = requests.post(
            TTNICHE_URL,
            json=payload,
            headers={"X-Secret": TTNICHE_SECRET},
            timeout=60,
        )
        if resp.status_code != 200:
            return {"status": "error", "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        text = resp.text.strip()
        if not text:
            return {"status": "error", "message": "Empty response from server"}
        try:
            return resp.json()
        except Exception:
            return {"status": "error", "message": f"Non-JSON response: {text[:300]}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Main ──────────────────────────────────────────────────────────────────────
async def scrape_fyp():
    log("=" * 55)
    log(f"TTNiche FYP Bot (Playwright) — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 55)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--lang=en-US",
            ]
        )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )

        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        # Intercept all responses
        page.on("response", handle_response)

        log("Opening tiktok.com...")
        try:
            await page.goto("https://www.tiktok.com/foryou", timeout=30000, wait_until="domcontentloaded")
        except Exception:
            await page.goto("https://www.tiktok.com", timeout=30000, wait_until="domcontentloaded")

        log("Waiting for FYP to load...")
        await asyncio.sleep(4)

        # Scroll to load more videos
        log("Scrolling FYP...")
        for i in range(20):
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(random.uniform(0.8, 1.6))
            if i % 5 == 4:
                log(f"  Scroll {i+1}/20 — collected {len(collected)} videos so far")
            if len(collected) >= MAX_VIDEOS:
                break

        await browser.close()

    log(f"\nCollected {len(collected)} videos from FYP")
    return collected


def main():
    videos = asyncio.run(scrape_fyp())

    if not videos:
        log("No videos collected — TikTok may have blocked. Exiting.")
        sys.exit(0)

    processed = 0
    for video in videos[:MAX_VIDEOS]:
        log(f"\n── @{video['author_unique']} — {video['plays']:,} plays")
        log(f"   {video['description'][:80]}")
        log(f"   cover={'yes' if video.get('cover_url') else 'EMPTY'}  video_url={'yes' if video.get('video_url') else 'EMPTY'}")

        transcript = None
        if video.get("video_url"):
            log("  [T] Transcribing...")
            transcript = transcribe(video["video_url"])
            log(f"  [T] {'✓ ' + str(len(transcript)) + ' chars' if transcript else '✗ No speech'}")

        result = send_to_ttniche(video, transcript)
        log(f"  [→] {result.get('status')} — {result.get('message','')}")
        processed += 1

    log(f"\n{'='*55}")
    log(f"Done — {processed} videos processed.")


if __name__ == "__main__":
    main()
