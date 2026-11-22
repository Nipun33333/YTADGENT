"""Offline regressions for US topic choice and strictly relevant video footage."""
import ast
from pathlib import Path
from agents import us_trends


def test_subject_free_source_titles_are_rejected():
    for title in ("This Sucks", "We Won", "The Internet Exploded Over This", "WOW!"):
        assert not us_trends.has_specific_subject({"title": title}), title
    for title in ("Demon Slayer ep 43", "Why Binding of Isaac Music Changed",
                  "BIGBANG GiiiRIP", "ドラゴンボール 新予告"):
        assert us_trends.has_specific_subject({"title": title}), title


def test_downloaded_video_validation_not_bypassed():
    stock = ast.parse(Path("video/stock.py").read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(stock)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_post_download_validate"
    ]
    # Both Google/Tavily and Pexels videos must have a real post-download
    # vision check, not only a metadata/title check.
    assert len(calls) >= 2
    for call in calls:
        arguments = {kw.arg: kw.value for kw in call.keywords}
        assert "skip_visual_check" not in arguments or (
            isinstance(arguments["skip_visual_check"], ast.Constant)
            and arguments["skip_visual_check"].value is False
        )


def test_empty_sections_cannot_borrow_other_section_footage():
    stock = ast.parse(Path("video/stock.py").read_text(encoding="utf-8"))
    pipeline = next(
        node for node in stock.body
        if isinstance(node, ast.FunctionDef) and node.name == "download_videos"
    )
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "_fill_empty_sections_from_pool"
        for node in ast.walk(pipeline)
    )
    assert any(isinstance(node, ast.Raise) for node in ast.walk(pipeline))


def test_viral_ranking_considers_view_velocity_not_only_lifetime_views(monkeypatch):
    import config
    monkeypatch.setattr(config, "DISCOVERY_MODE", "viral")
    monkeypatch.setattr(us_trends, "_age_hours", lambda t: {"fresh": 2.0, "old": 60.0}[t])
    videos = [
        {"video_id": "old", "title": "Big entertainment announcement",
         "published_at": "old", "views": 600000, "likes": 2000, "comments": 100},
        {"video_id": "fresh", "title": "New gaming developer announcement",
         "published_at": "fresh", "views": 30000, "likes": 3000, "comments": 300},
    ]
    ranked = us_trends._dedupe_and_score(videos)
    assert ranked[0]["video_id"] == "fresh"
    assert ranked[0]["views_per_hour"] == 15000
    assert ranked[0]["viral_score"] > ranked[1]["viral_score"]


def test_full_candidate_pool_is_ranked_before_limit(monkeypatch):
    import config
    monkeypatch.setattr(config, "DISCOVERY_MODE", "viral")
    monkeypatch.setattr(config, "DISCOVERY_CANDIDATE_LIMIT", 1)
    monkeypatch.setattr(us_trends, "select_semantic_candidate", lambda batch, desc: {
        **batch[0], "content_type": "EXPLAINER",
        "content_domain": "GENERAL_TREND", "content_angle": "Grounded explanation"
    })
    candidates = [
        {"video_id": "low", "title": "Low signal", "viral_score": 1},
        {"video_id": "high", "title": "High signal", "viral_score": 90},
    ]
    assert us_trends.choose_best_trend(candidates)["candidate_id"] == "high"


