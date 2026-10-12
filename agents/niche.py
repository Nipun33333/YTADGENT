"""Semantic selector for current US trending-topic explanations.

This module has no fixed niche gate. Candidates come from broad current US YouTube
signals and Gemini selects one current subject that can support an explanation,
breakdown, context, analysis, or recap video.
"""
from __future__ import annotations

import json
import re
from typing import Any

from agents.gemini_client import generate
import config


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
            "views": item.get("views", 0),
            "likes": item.get("likes", 0),
            "comments": item.get("comments", 0),
            "trend_score": item.get("trend_score", 0),
            "published_at": item.get("published_at", ""),
        }, ensure_ascii=False))

    return f"""You are the current-US-trend selector for a YouTube explanation channel.

CHANNEL POSITIONING:
{channel_description}

GOAL:
Select ONE genuinely current, high-signal US trending candidate from the list.
The selected candidate becomes the immutable subject for the entire pipeline.
It can be ANY subject that is genuinely trending. Do not impose any fixed
subject, franchise, category, entertainment, news, or keyword restriction.
Do not use a predefined category allowlist.

SELECTION RULES:
- Choose only a candidate_id present in the supplied list.
- Prefer strong current trend signals: recency, view velocity, engagement, and
  broad US interest.
- Prefer candidates that can be explained, contextualized, analyzed, or broken
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
    if not candidates:
        raise ValueError("No candidates supplied to trend selector.")

    prompt = build_selection_prompt(candidates, channel_description)
    try:
        raw = generate(
            prompt,
            timeout_seconds=getattr(config, "GEMINI_SELECTION_TIMEOUT_SECONDS", 30),
            max_models=getattr(config, "GEMINI_SELECTION_MAX_MODELS", 6),
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        raw = generate(prompt)

    result = clean_json_response(raw)
    candidate_id = result.get("candidate_id")
    if not candidate_id:
        raise RuntimeError("No usable current US trend candidate matched the explanation criteria.")

    lookup = {str(x.get("video_id")): x for x in candidates}
    selected = lookup.get(str(candidate_id))
    if selected is None:
        raise ValueError("Trend selector returned an unknown candidate_id.")

    content_type = str(result.get("content_type", "EXPLAINER")).upper().strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        content_type = "EXPLAINER"

    selected = dict(selected)
    selected.update({
        "content_type": content_type,
        "content_domain": "GENERAL_TREND",
        "content_angle": str(result.get("content_angle", "")).strip(),
        "why_it_fits": str(result.get("why_it_fits", "")).strip(),
        "semantic_confidence": float(result.get("confidence", 0) or 0),
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
