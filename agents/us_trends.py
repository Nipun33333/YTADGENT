"""US trend discovery with source-order selection and dated trend fallbacks."""
from __future__ import annotations

import hashlib
import os
import re
import requests
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import config
from agents.niche import select_semantic_candidate

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3"
GOOGLE_TRENDS_RSS_URL = "https://trends.google.com/trending/rss"
USED_TOPICS_FILE = os.path.join(config.PROJECT_ROOT, "used_topics.txt")
SEARCH_HOURS = config.DISCOVERY_WINDOW_HOURS
BANNED_KEYWORDS = [
    "suicide", "self harm", "self-harm", "mass shooting", "dead body",
    "graphic gore", "graphic violence", "rape", "child abuse", "terrorist", "terrorism", "sexual assault",
]


def normalize(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def is_banned(text: str) -> bool:
    normalized = normalize(text)
    return any(normalize(k) in normalized for k in BANNED_KEYWORDS)


def topics_are_similar(topic_a: str, topic_b: str) -> bool:
    a = set(normalize(topic_a).split())
    b = set(normalize(topic_b).split())
    stop = {"the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with", "from", "new", "latest", "official", "video", "youtube", "shorts", "short", "update", "news", "story", "trailer"}
    a -= stop
    b -= stop
    if not a or not b:
        return False
    common = a & b
    if not common:
        return False
    if normalize(topic_a) == normalize(topic_b):
        return True
    if len(common) >= 2:
        return True
    smaller = min(len(a), len(b))
    # A single distinctive entity is enough to treat a more specific title
    # as the same underlying topic (e.g. a more specific title vs a broader title about the same subject).
    return smaller == 1 and len(common) == 1 or (smaller >= 2 and len(common) / smaller >= 0.67)


def load_used_topics() -> list[str]:
    if not os.path.exists(USED_TOPICS_FILE):
        return []
    try:
        with open(USED_TOPICS_FILE, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]
    except Exception as exc:
        print(f"   ⚠ Could not read used_topics.txt: {exc}")
        return []


def save_used_topic(topic: str) -> None:
    try:
        with open(USED_TOPICS_FILE, "a", encoding="utf-8") as f:
            f.write((topic or "").strip() + "\n")
    except Exception as exc:
        print(f"   ⚠ Could not save used topic: {exc}")


def youtube_request(endpoint: str, params: dict, timeout: float = 8.0) -> dict:
    if not config.YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY is missing.")
    query = dict(params)
    query["key"] = config.YOUTUBE_API_KEY
    response = requests.get(
        f"{YOUTUBE_API_URL}/{endpoint}",
        params=query,
        headers={"User-Agent": "YTAGENT-US-Trending/1.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("YouTube API returned an invalid payload.")
    return data


def _age_hours(published_at: str) -> float:
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - published).total_seconds() / 3600
        return age if age >= 0 else float("inf")
    except Exception:
        return float("inf")


def calculate_video_score(video: dict) -> float:
    """Compatibility shim: viral scoring is no longer used."""
    return 0.0


def _source_specs() -> list[tuple[str, dict]]:
    return [("US_mostPopular", {"chart": "mostPopular", "regionCode": "US"})]


def fetch_google_trends_candidates() -> list[dict]:
    """Read only dated US trend records actually supplied by Google's RSS feed.

    The feed is not a 30-day archive. Older fallbacks are available only when
    the source includes records in those windows; never synthesize history.
    """
    try:
        response = requests.get(
            GOOGLE_TRENDS_RSS_URL, params={"geo": "US"},
            headers={"User-Agent": "YTAGENT-US-Trending/1.0"}, timeout=8.0,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
    except Exception as exc:
        print(f"   ⚠ Google Trends discovery failed: {type(exc).__name__}")
        return []

    candidates = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
            if published.tzinfo is None:
                continue
            published_at = published.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            continue
        description = " ".join(
            node.text.strip() for node in item.iter()
            if node.tag.rsplit("}", 1)[-1] in
            {"description", "news_item_title", "news_item_snippet"} and node.text
        )
        if not title or _age_hours(published_at) > 30 * 24 or is_banned(title + " " + description):
            continue
        record_id = hashlib.sha256((title + published_at).encode("utf-8")).hexdigest()
        candidates.append({
            "video_id": "google-trends-" + record_id,
            "title": title, "description": description[:600],
            "published_at": published_at, "trend_recorded_at": published_at,
            "channel": "Google Trends US", "category_id": "",
            "views": 0, "likes": 0, "comments": 0, "trend_score": 0,
            "source": "Google_Trends_US",
        })
    return candidates


def _fetch_source(source_name: str, base_params: dict) -> tuple[str, list[dict]]:
    collected: list[dict] = []
    page_token = None
    for _ in range(max(1, config.DISCOVERY_MAX_PAGES)):
        params = dict(base_params)
        params.update({"part": "snippet,statistics", "maxResults": config.DISCOVERY_RESULTS_PER_SOURCE})
        if page_token:
            params["pageToken"] = page_token
        try:
            data = youtube_request("videos", params)
        except Exception as exc:
            print(f"   ⚠ {source_name} discovery failed: {type(exc).__name__}")
            break
        observed_at = datetime.now(timezone.utc).isoformat()
        for item in data.get("items", []) or []:
            video_id = str(item.get("id") or "").strip()
            snippet = item.get("snippet") or {}
            stats = item.get("statistics") or {}
            title = str(snippet.get("title") or "").strip()
            published_at = str(snippet.get("publishedAt") or "").strip()
            description = str(snippet.get("description") or "").strip()
            if not video_id or not title or not published_at:
                continue
            if is_banned(title + " " + description):
                continue
            collected.append({
                "video_id": video_id,
                "title": title,
                "description": description[:600],
                "published_at": published_at,
                # A live US chart establishes a current observation, not a
                # historical trend date inferred from the video's upload age.
                "trend_recorded_at": observed_at,
                "channel": str(snippet.get("channelTitle") or "").strip(),
                "category_id": str(snippet.get("categoryId") or base_params.get("videoCategoryId") or ""),
                "views": int(stats.get("viewCount", 0) or 0),
                "likes": int(stats.get("likeCount", 0) or 0),
                "comments": int(stats.get("commentCount", 0) or 0),
                "source": source_name,
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return source_name, collected


def _dedupe_and_score(videos: list[dict]) -> list[dict]:
    """Keep the first source occurrence; retain the legacy name for callers."""
    unique: dict[str, dict] = {}
    for video in videos:
        vid = video["video_id"]
        if vid not in unique:
            unique[vid] = dict(video, trend_score=0)
    return list(unique.values())


def fetch_youtube_candidates() -> list[dict]:
    print("\n   🎬 DYNAMIC YOUTUBE DISCOVERY")
    print("   → Broad current signals only; no fixed topic keyword list.")

    videos: list[dict] = []
    for source, params in _source_specs():
        try:
            _, rows = _fetch_source(source, params)
            videos.extend(rows)
            print(f"   → {source}: {len(rows)} current chart candidates")
        except Exception as exc:
            print(f"   ⚠ {source} discovery failed: {type(exc).__name__}")

    candidates = _dedupe_and_score(videos)
    print(f"   → Found {len(candidates)} unique recent YouTube candidates before semantic filtering")
    return candidates


def filter_candidates(candidates: list[dict]) -> list[dict]:
    used = load_used_topics()
    filtered = []
    for candidate in candidates:
        title = candidate.get("title", "").strip()
        if not title or is_banned(title + " " + candidate.get("description", "")):
            continue
        if any(topics_are_similar(title, old) for old in used):
            continue
        filtered.append(candidate)
    print(f"   → {len(filtered)} unused candidates remain before semantic trend gate")
    return filtered



def choose_best_trend(candidates: list[dict], channel_description: str = "") -> dict:
    if not candidates:
        raise RuntimeError("No usable current YouTube candidates found.")

    selected = select_semantic_candidate(candidates, channel_description)

    print(f"   ✅ Selected current US trend: {selected['title']}")
    print(f"   🎯 Domain: {selected['content_domain']} | Type: {selected['content_type']}")
    print(f"   🧠 Angle: {selected['content_angle'] or '(Gemini did not provide one)'}")

    return {
        "candidate_id": selected["video_id"],
        "selected_trend": selected["title"],
        "topic": selected["title"],
        "video_title": selected["title"],
        "source_trend": selected["title"],
        "description": selected.get("description", ""),
        "why_now": selected.get("why_it_fits", ""),
        "content_type": selected["content_type"],
        "content_domain": selected["content_domain"],
        "content_angle": selected.get("content_angle", ""),
        "trend_score": 0,
        "channel": selected.get("channel", ""),
        "published_at": selected.get("published_at", ""),
        "views": selected.get("views", 0),
        "semantic_confidence": selected.get("semantic_confidence", 0),
        "source_subject_anchors": selected.get("source_subject_anchors", []),
    }


def get_best_us_trending_topic(channel_description: str = "") -> dict:
    # Fixed source order, independent of response speed or popularity metrics.
    candidates = fetch_google_trends_candidates() + fetch_youtube_candidates()
    if not candidates:
        raise RuntimeError("Could not retrieve current YouTube discovery candidates.")
    filtered = filter_candidates(candidates)
    if not filtered:
        raise RuntimeError("All current candidates were already used or blocked.")
    # Snapshot ages once so records cannot slip between windows as time passes.
    dated = [(candidate, _age_hours(candidate.get("trend_recorded_at", "")))
             for candidate in filtered]
    for minimum, maximum in ((0, 24), (24, 72), (72, 30 * 24)):
        window = [candidate for candidate, age in dated
                  if (age >= minimum if minimum == 0 else age > minimum) and age <= maximum]
        if not window:
            continue
        print(f"   → Checking US trend records aged {minimum}–{maximum} hours in source order")
        try:
            return choose_best_trend(window, channel_description)
        except RuntimeError as exc:
            if "No usable current US trend candidate" not in str(exc):
                raise
    raise RuntimeError("No usable current US trend candidate after semantic scanning.")
