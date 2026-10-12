import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import config
from agents import niche, topic_validation, us_trends


def _candidate(title="US trend topic explained", cid="x1", score=50, category=""):
    return {
        "video_id": cid,
        "title": title,
        "description": "A current US trending subject.",
        "channel": "Trend Channel",
        "category_id": category,
        "views": 1000,
        "trend_score": score,
        "published_at": "2026-09-28T08:00:00Z",
    }


def _mock_generate(monkeypatch, payload):
    monkeypatch.setattr(niche, "generate", lambda *args, **kwargs: json.dumps(payload))


@pytest.mark.parametrize("raw, expected", [
    ("Marvel!!!", "marvel"), ("US Trend-Topic", "us trend topic"),
    ("  Latest  News  ", "latest news"), ("A/B/C", "a b c"),
    ("Hello, WORLD", "hello world"), ("", ""), ("   ", ""),
    ("2026 Update", "2026 update"), ("GTA 6", "gta 6"),
    ("Minecraft LIVE", "minecraft live"), ("Foo...bar!!!baz", "foo bar baz"),
    ("A_B-C", "a b c"), ("Hidden Detail #1", "hidden detail 1"),
    ("What’s New?", "what s new"), ("A:B:C", "a b c"),
    ("Election 2026", "election 2026"), ("Tech AI chip", "tech ai chip"),
    ("NBA Finals", "nba finals"), ("Bitcoin update", "bitcoin update"),
])
def test_normalize_matrix(raw, expected):
    assert us_trends.normalize(raw) == expected


@pytest.mark.parametrize("text, expected", [
    ("normal trending video", False), ("graphic gore footage", True),
    ("sexual assault story", True), ("terrorism documentary", True),
    ("self harm discussion", True), ("mass shooting footage", True),
    ("child abuse documentary", True), ("music video", False),
    ("football match", False), ("science documentary", False),
    ("politics update", False), ("technology launch", False),
    ("rape allegation", True), ("dead body found", True),
    ("terrorist attack", True), ("graphic violence", True),
])
def test_safety_matrix(text, expected):
    assert us_trends.is_banned(text) is expected


@pytest.mark.parametrize("a,b,expected", [
    ("Minecraft update", "Minecraft update explained", True),
    ("NBA Finals", "NBA Finals recap", True),
    ("AI chip launch", "AI chip launch details", True),
    ("Bitcoin price", "Bitcoin price update", True),
    ("Movie trailer", "Movie trailer explained", True),
    ("random topic", "unrelated topic", False),
    ("Alpha Beta Core", "Alpha Beta Delta", True),
    ("A B C", "A D E", False),
    ("", "", False), ("", "topic", False), ("topic", "", False),
    ("NASA mission", "NASA mission timeline", True),
    ("Sports highlight", "finance update", False),
    ("Election debate", "election debate highlights", True),
    ("New phone launch", "new phone launch review", True),
    ("Game release", "game release trailer", True),
])
def test_similarity_matrix(a, b, expected):
    assert us_trends.topics_are_similar(a, b) is expected


@pytest.mark.parametrize("hours", [0.5, 1, 2, 4, 8, 12, 18, 24, 36, 48, 60, 72, 90, 120, 240])
def test_trend_score_is_finite(hours):
    published = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    score = us_trends.calculate_video_score({
        "views": 100_000, "likes": 5_000, "comments": 500, "published_at": published,
    })
    assert 0 <= score <= 100


@pytest.mark.parametrize("content_type", [
    "EXPLAINER", "BREAKDOWN", "ANALYSIS", "NEWS_EXPLAINER", "CONTEXT",
    "TIMELINE", "HOW_IT_WORKS", "RECAP", "TREND_EXPLAINER",
])
def test_semantic_content_types(monkeypatch, content_type):
    _mock_generate(monkeypatch, {
        "candidate_id": "x1", "content_type": content_type,
        "content_domain": "GENERAL_TREND", "content_angle": "Explain it",
        "why_it_fits": "Current trend", "confidence": 0.9,
    })
    selected = niche.select_semantic_candidate([_candidate()], config.CHANNEL_DESCRIPTION)
    assert selected["video_id"] == "x1"
    assert selected["content_domain"] == "GENERAL_TREND"
    assert selected["content_type"] == content_type


def test_selector_is_category_agnostic(monkeypatch):
    _mock_generate(monkeypatch, {
        "candidate_id": "sports", "content_type": "RECAP",
        "content_domain": "GENERAL_TREND", "content_angle": "Why the game matters",
        "why_it_fits": "Strong current US trend", "confidence": 0.98,
    })
    candidates = [
        _candidate("AI chip launch", "tech", 90, "28"),
        _candidate("NBA Finals controversy", "sports", 88, "17"),
        _candidate("Movie trailer", "movie", 87, "1"),
    ]
    out = niche.select_semantic_candidate(candidates, config.CHANNEL_DESCRIPTION)
    assert out["video_id"] == "sports"
    assert out["content_domain"] == "GENERAL_TREND"


def test_selector_unknown_candidate_rejected(monkeypatch):
    _mock_generate(monkeypatch, {
        "candidate_id": "missing", "content_type": "EXPLAINER",
        "content_domain": "GENERAL_TREND", "content_angle": "x", "why_it_fits": "x", "confidence": 1,
    })
    with pytest.raises(ValueError, match="unknown candidate_id"):
        niche.select_semantic_candidate([_candidate()], config.CHANNEL_DESCRIPTION)


def test_manual_topic_is_not_niche_gated():
    out = niche.validate_manual_topic("A newly announced technology product")
    assert out["content_domain"] == "GENERAL_TREND"
    assert out["content_type"] == "EXPLAINER"


def test_selector_prompt_is_category_agnostic():
    prompt = niche.build_selection_prompt([_candidate()], config.CHANNEL_DESCRIPTION).lower()
    assert "predefined category allowlist" in prompt
    assert "fixed topical restriction" not in prompt
    assert "candidates:" in prompt


def test_config_identity_is_trending_not_niche():
    text = config.CHANNEL_DESCRIPTION.lower()
    assert "current" in text
    assert "trending" in text
    assert "current" in text and "trending" in text
    assert config.CONTENT_MODE == "US_TREND_EXPLANATION"


def test_topic_validation_accepts_general_trend():
    research = {
        "topic": "AI chip launch explained",
        "source_trend": "AI chip launch",
        "video_title": "What the AI Chip Launch Means",
        "hook_question": "Why is this AI chip launch trending now?",
        "content_domain": "GENERAL_TREND",
        "content_type": "EXPLAINER",
    }
    topic_validation.validate_research_topic_lock(research)


@pytest.mark.parametrize("bad_domain", ["ANIME", "MARVEL", "SPORTS", "SCIENCE", "", "POP_CULTURE"])
def test_topic_validation_rejects_non_general_domain(bad_domain):
    research = {
        "topic": "AI chip launch explained",
        "source_trend": "AI chip launch",
        "video_title": "What the AI Chip Launch Means",
        "hook_question": "Why is this AI chip launch trending now?",
        "content_domain": bad_domain,
        "content_type": "EXPLAINER",
    }
    with pytest.raises(ValueError):
        topic_validation.validate_research_topic_lock(research)


@pytest.mark.parametrize("bad_type", ["SPORTS", "MOTIVATION", "FACTS", "", "FRANCHISE_UPDATE"])
def test_topic_validation_rejects_unknown_types(bad_type):
    research = {
        "topic": "AI chip launch explained",
        "source_trend": "AI chip launch",
        "video_title": "What the AI Chip Launch Means",
        "hook_question": "Why is this AI chip launch trending now?",
        "content_domain": "GENERAL_TREND",
        "content_type": bad_type,
    }
    with pytest.raises(ValueError):
        topic_validation.validate_research_topic_lock(research)


def test_fetch_source_parallel_result_shape(monkeypatch):
    def fake_request(endpoint, params, timeout=8.0):
        return {"items": [{
            "id": "video-1",
            "snippet": {"title": "Current AI chip trend", "description": "desc", "publishedAt": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z"), "channelTitle": "channel", "categoryId": "28"},
            "statistics": {"viewCount": "1000", "likeCount": "50", "commentCount": "5"},
        }], "nextPageToken": None}
    monkeypatch.setattr(us_trends, "youtube_request", fake_request)
    name, rows = us_trends._fetch_source("US_mostPopular", {"chart": "mostPopular"})
    assert name == "US_mostPopular"
    assert rows[0]["video_id"] == "video-1"


def test_category_ids_default_is_broad():
    assert config.DISCOVERY_CATEGORY_IDS == ()


def test_end_to_end_broad_trend_selection(monkeypatch):
    candidates = [
        _candidate("AI chip launch explained", "tech", 98, "28"),
        _candidate("NBA Finals controversy", "sports", 96, "17"),
        _candidate("Movie trailer explained", "movie", 94, "1"),
    ]
    monkeypatch.setattr(us_trends, "fetch_youtube_candidates", lambda: candidates)
    monkeypatch.setattr(us_trends, "load_used_topics", lambda: [])
    monkeypatch.setattr(niche, "generate", lambda *a, **k: json.dumps({
        "candidate_id": "tech", "content_type": "EXPLAINER", "content_domain": "GENERAL_TREND",
        "content_angle": "What changed and why it matters", "why_it_fits": "Strong current trend", "confidence": 0.99,
    }))
    out = us_trends.get_best_us_trending_topic(config.CHANNEL_DESCRIPTION)
    assert out["candidate_id"] == "tech"
    assert out["content_domain"] == "GENERAL_TREND"


def test_no_fallback_to_other_subject_when_selector_returns_null(monkeypatch):
    monkeypatch.setattr(us_trends, "fetch_youtube_candidates", lambda: [_candidate("AI chip launch", "x")])
    monkeypatch.setattr(us_trends, "load_used_topics", lambda: [])
    monkeypatch.setattr(niche, "generate", lambda *a, **k: json.dumps({"candidate_id": None}))
    with pytest.raises(RuntimeError, match="No usable current US trend"):
        us_trends.get_best_us_trending_topic(config.CHANNEL_DESCRIPTION)


def test_trend_gate_reaches_later_batches(monkeypatch):
    candidates = [_candidate(f"Trend topic {i}", f"bad-{i}", 100-i, "28") for i in range(60)]
    calls = []
    good = _candidate("US trend worth explaining", "good", 1, "17")
    candidates.insert(35, good)

    def fake_selector(batch, channel):
        calls.append([x["video_id"] for x in batch])
        for item in batch:
            if item["video_id"] == "good":
                return {**item, "content_type": "EXPLAINER", "content_domain": "GENERAL_TREND", "content_angle": "Explain it", "why_it_fits": "Current trend", "semantic_confidence": 1}
        raise RuntimeError("No usable current US trend candidate matched the explanation criteria.")

    monkeypatch.setattr(us_trends, "select_semantic_candidate", fake_selector)
    out = us_trends.choose_best_trend(candidates, config.CHANNEL_DESCRIPTION)
    assert out["candidate_id"] == "good"
    assert len(calls) >= 2


def test_trend_gate_respects_max_batches(monkeypatch):
    candidates = [_candidate(f"Trend {i}", f"x{i}", 100-i, "28") for i in range(100)]
    calls = []
    def fake_selector(batch, channel):
        calls.append(batch)
        raise RuntimeError("No usable current US trend candidate matched the explanation criteria.")
    monkeypatch.setattr(us_trends, "select_semantic_candidate", fake_selector)
    monkeypatch.setattr(config, "DISCOVERY_SEMANTIC_BATCH_SIZE", 10)
    monkeypatch.setattr(config, "DISCOVERY_SEMANTIC_MAX_BATCHES", 3)
    with pytest.raises(RuntimeError):
        us_trends.choose_best_trend(candidates, config.CHANNEL_DESCRIPTION)
    assert len(calls) == 3


def _short_script(research):
    subject = research["topic"]
    return {
        "title": "Why This Trend Matters Now",
        "description": f"A concise explanation of {subject}.",
        "tags": ["Trending", "Explained", "#Shorts"],
        "topic": research["topic"],
        "source_trend": research["source_trend"],
        "content_domain": "GENERAL_TREND",
        "content_type": "EXPLAINER",
        "video_type": "shorts",
        "sections": [
            {
                "id": 1, "section_type": "hook", "title": "Hook",
                "narration": f"Here is why {subject} is suddenly everywhere right now.",
                "video_query": subject + " breaking trend footage",
                "video_query_2": subject + " latest development footage",
                "video_query_3": subject + " recent event footage",
                "video_query_4": subject + " current coverage footage",
                "bullet_points": [], "caption_text": subject, "duration_seconds": 7,
            },
            {
                "id": 2, "section_type": "explanation", "title": "What it means",
                "narration": f"The key point is what {subject} actually means and why the latest change matters.",
                "video_query": subject + " explanation footage",
                "video_query_2": subject + " analysis footage",
                "video_query_3": subject + " context footage",
                "video_query_4": subject + " latest update footage",
                "bullet_points": [], "caption_text": "Why it matters", "duration_seconds": 24,
            },
            {
                "id": 3, "section_type": "cta", "title": "CTA",
                "narration": "Follow for more current trend explainers.",
                "video_query": subject + " ending footage",
                "video_query_2": subject + " latest footage",
                "video_query_3": subject + " event footage",
                "video_query_4": subject + " closing coverage footage",
                "bullet_points": [], "caption_text": "More explainers", "duration_seconds": 6,
            },
        ],
    }


@pytest.mark.parametrize("iteration", range(100))
def test_100x_subject_integrity_accepts_creative_title(iteration):
    subject = f"Current US trend topic {iteration} AI launch"
    research = {
        "source_trend": subject,
        "topic": f"Why the {subject} matters now",
        "video_title": f"What Everyone Needs to Know About This {iteration}",
        "hook_question": f"Why is this {iteration} trend exploding?",
        "content_domain": "GENERAL_TREND",
        "content_type": "EXPLAINER",
        "key_points": ["latest change", "why it matters", "current context"],
    }
    assert topic_validation.validate_research_topic_lock(research) is None


@pytest.mark.parametrize("iteration", range(100))
def test_100x_subject_integrity_rejects_changed_source(iteration):
    subject = f"Current US trend topic {iteration} AI launch"
    research = {
        "source_trend": f"Completely different sports event {iteration}",
        "topic": f"Sports event {iteration}",
        "video_title": "A different story",
        "hook_question": "Why is this different story trending?",
        "content_domain": "GENERAL_TREND",
        "content_type": "EXPLAINER",
    }
    with pytest.raises(ValueError, match="source_trend drifted"):
        # Use researcher-level lock for canonical source equality.
        from agents import researcher
        researcher._validate_topic_integrity(research, subject)


@pytest.mark.parametrize("iteration", range(100))
def test_100x_broad_discovery_selection(iteration, monkeypatch):
    candidate_id = f"iter-{iteration}"
    subject = f"US trending topic {iteration} technology update"
    candidate = _candidate(subject, candidate_id, 90, "28")
    monkeypatch.setattr(niche, "generate", lambda *a, cid=candidate_id, **k: json.dumps({
        "candidate_id": cid, "content_type": "EXPLAINER", "content_domain": "GENERAL_TREND",
        "content_angle": "Explain the update", "why_it_fits": "Current US trend", "confidence": 0.99,
    }))
    selected = niche.select_semantic_candidate([candidate], config.CHANNEL_DESCRIPTION)
    assert selected["video_id"] == candidate_id
    assert selected["content_domain"] == "GENERAL_TREND"


@pytest.mark.parametrize("iteration", range(100))
def test_100x_script_lock_accepts_topic_specific_queries(iteration):
    research = {
        "topic": f"US trending topic {iteration} technology update",
        "source_trend": f"US trending topic {iteration} technology update",
        "video_title": f"What the technology update means {iteration}",
        "hook_question": "Why is this update trending now?",
        "content_domain": "GENERAL_TREND",
        "content_type": "EXPLAINER",
        "key_points": ["latest update", "why it matters", "current context"],
    }
    script = _short_script(research)
    topic_validation.validate_script_topic_lock(script, research)


def test_unsupported_domain_is_not_silently_accepted():
    research = {
        "topic": "AI chip launch",
        "source_trend": "AI chip launch",
        "video_title": "AI chip launch explained",
        "hook_question": "Why is the AI chip launch trending?",
        "content_domain": "MARVEL",
        "content_type": "EXPLAINER",
    }
    with pytest.raises(ValueError, match="Unsupported content domain"):
        topic_validation.validate_research_topic_lock(research)


def test_workflow_schedule_is_india_time():
    text = Path(".github/workflows/daily-short.yml").read_text(encoding="utf-8")
    for cron in ['cron: "0 20 * * 1-5"', 'cron: "0 22 * * 1-5"', 'cron: "30 0 * * 2-6"', 'cron: "0 17 * * 6"', 'cron: "0 17 * * 0"']:
        assert cron in text
    assert text.count('timezone: "Asia/Kolkata"') == 5
    assert "VIDEO_PRIVACY: public" in text
    assert "Resolve scheduled video type" in text


def test_no_fixed_popculture_gate_remains():
    for path in [Path("agents/niche.py"), Path("agents/us_trends.py"), Path("agents/researcher.py"), Path("agents/scriptwriter.py")]:
        text = path.read_text(encoding="utf-8").lower()
        assert "no fixed topic keyword" in text or "current us" in text or "general_trend" in text
        assert "no current candidate matched the pop-culture niche" not in text
    assert "pop-culture explanation niche" not in text


def test_default_discovery_is_not_category_restricted():
    assert config.DISCOVERY_CATEGORY_IDS == ()


def test_readme_describes_current_trends():
    text = Path("README.md").read_text(encoding="utf-8").lower()
    assert "current us trending" in text
    assert "fixed topic keyword" in text or "no fixed" in text
