"""Source-order selector for US trending-topic explanations.

Discovery supplies eligible trends. Selection only checks for readable topic
data and supplies the existing pipeline metadata, without Gemini verification.
"""
from __future__ import annotations

import json
import re
from typing import Any

CONTENT_MODE = "US_TREND_EXPLANATION"
ALLOWED_CONTENT_TYPES = {
    "EXPLAINER",
    "BREAKDOWN",
    "ANALYSIS",
    "NEWS_EXPLAINER",
    "CONTEXT",
    "TIMELINE",
    "HOW_IT_WORKS",
    "RECAP",
    "TREND_EXPLAINER",
}


def clean_json_response(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.I).strip()
    raw = re.sub(r"```$", "", raw).strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError("Gemini returned no valid JSON object.")
    return json.loads(match.group())


def build_selection_prompt(candidates: list[dict], channel_description: str = "") -> str:
    rows = []
    for item in candidates:
        rows.append(json.dumps({
            "candidate_id": item.get("video_id"),
            "title": item.get("title", ""),
            "description": item.get("description", "")[:300],
            "channel": item.get("channel", ""),
            "category_id": item.get("category_id", ""),
            "published_at": item.get("published_at", ""),
            "trend_recorded_at": item.get("trend_recorded_at", ""),
            "source": item.get("source", ""),
        }, ensure_ascii=False))

    return f"""You are the current-US-trend selector for a YouTube explanation channel.

CHANNEL POSITIONING:
{channel_description}

GOAL:
Accept the FIRST safe, usable US trending candidate in the supplied source order.
Discovery has already chosen the current or historical fallback time window.
Historical fallback records are eligible; do not reject them merely for age.
The selected candidate becomes the immutable subject for the entire pipeline.
It can be ANY subject that is genuinely trending. Do not impose any fixed
subject, franchise, category, entertainment, news, or keyword restriction.
Do not use a predefined category allowlist.

SELECTION RULES:
- Choose only a candidate_id present in the supplied list.
- Never rank or compare candidates by views, engagement, velocity, or viral score.
- Accept a candidate if it can be explained, contextualized, analyzed, or broken
  down in a short video.
- A raw clip/performance is acceptable when the surrounding subject itself is
  explainable; do not invent a different topic.
- Category metadata may be used only as supporting context; never prioritize or reject a candidate because of its category.
- Never invent a candidate, entity, or event.
- If all candidates are unsafe or unusable, return candidate_id as null.

CANDIDATES:
""" + "\n".join(rows) + """

Return ONLY JSON:
{
  "candidate_id": "existing candidate_id or null",
  "content_type": "EXPLAINER | BREAKDOWN | ANALYSIS | NEWS_EXPLAINER | CONTEXT | TIMELINE | HOW_IT_WORKS | RECAP | TREND_EXPLAINER",
  "content_domain": "GENERAL_TREND",
  "content_angle": "specific explanation angle tied directly to the selected candidate",
  "why_it_fits": "brief reason this subject is worth explaining now",
  "confidence": 0.0
}
"""


def select_semantic_candidate(candidates: list[dict], channel_description: str = "") -> dict[str, Any]:
    """Retain the public interface without running semantic approval."""
    if not candidates:
        raise ValueError("No candidates supplied to trend selector.")

    for candidate in candidates:
        title = candidate.get("title")
        if not candidate.get("video_id") or not isinstance(title, str) or not title.strip():
            continue
        return _check_semantic_candidate(candidate, channel_description)
    raise RuntimeError("No usable current US trend candidate contains readable topic data.")


def _check_semantic_candidate(candidate: dict, channel_description: str) -> dict[str, Any]:
    """Compatibility adapter only; no model call or topic qualification."""
    selected = dict(candidate)
    selected.update({
        "content_type": "EXPLAINER",
        "content_domain": "GENERAL_TREND",
        "content_angle": f"Explain {candidate['title']} clearly and directly.",
        "why_it_fits": "Discovered in US trend source data.",
        "semantic_confidence": 0.0,
    })
    return selected


def validate_manual_topic(topic: str) -> dict[str, Any]:
    """Accept a user-supplied topic without a fixed niche restriction."""
    topic = topic.strip()
    if not topic:
        raise ValueError("Manual topic cannot be empty.")
    return {
        "video_id": "manual",
        "title": topic,
        "description": "User-supplied topic.",
        "channel": "manual",
        "category_id": "",
        "views": 0,
        "trend_score": 0,
        "published_at": "",
        "content_type": "EXPLAINER",
        "content_domain": "GENERAL_TREND",
        "content_angle": "Explain the selected topic clearly and directly.",
        "semantic_confidence": 1.0,
    }
