"""Regression tests for recurring Gemini video-query drift failures."""
import copy
import json

import pytest

from agents import scriptwriter
from agents.topic_validation import repair_script_video_queries, validate_script_topic_lock


@pytest.fixture
def research():
    return {
        "topic": "The Restructuring and Future of Halo Studios",
        "source_trend": "The Inevitable End of Halo Studios",
        "video_title": "The End of Halo Studios: What Happens Next?",
        "hook_question": "What is next for Halo Studios?",
        "content_domain": "GENERAL_TREND",
        "content_type": "NEWS_EXPLAINER",
        "content_angle": "Halo Studios restructuring and the Halo franchise",
        "key_points": ["Halo Studios leadership", "Halo franchise outlook"],
    }


@pytest.fixture
def script(research):
    sections = []
    for index, section_type in enumerate(("hook", "explanation", "cta"), 1):
        sections.append({
            "id": index,
            "section_type": section_type,
            "narration": ("Follow for more explainers." if index == 3 else
                          "Halo Studios faces changes to the Halo franchise."),
            "video_query": "Halo Studios footage",
            "video_query_2": "Halo video coverage",
            "video_query_3": "Halo franchise behind the scenes footage",
            "video_query_4": "Halo Studios official interviews",
            "bullet_points": [],
            "caption_text": "Halo Studios",
        })
    return {
        "title": "Halo Studios Explained",
        "description": "Halo Studios changes.",
        "tags": ["Halo"],
        "video_type": "shorts",
        "topic": research["topic"],
        "source_trend": research["source_trend"],
        "content_domain": "GENERAL_TREND",
        "content_type": "NEWS_EXPLAINER",
        "sections": sections,
    }


def test_repair_halo_section_2_drift_without_regeneration(research, script):
    script["sections"][1]["video_query_3"] = "penguins swimming across Antarctic waters"
    with pytest.raises(ValueError, match="Section 2 video_query_3 drifted"):
        validate_script_topic_lock(script, research)
    narration_before = [s["narration"] for s in script["sections"]]
    changed = repair_script_video_queries(script, research)
    assert changed == ["Section 2 video_query_3"]
    assert "Halo Studios" in script["sections"][1]["video_query_3"]
    assert [s["narration"] for s in script["sections"]] == narration_before
    validate_script_topic_lock(script, research)


def test_valid_queries_are_never_modified(research, script):
    original = copy.deepcopy(script)
    assert repair_script_video_queries(script, research) == []
    assert script == original


@pytest.mark.parametrize("invalid_query", ["", "    ", "random butterfly video", None, 99])
def test_missing_and_unrelated_queries_repaired(research, script, invalid_query):
    script["sections"][0]["video_query_4"] = invalid_query
    assert repair_script_video_queries(script, research) == ["Section 1 video_query_4"]
    validate_script_topic_lock(script, research)


def test_does_not_hide_unrelated_narration(research, script):
    script["sections"][1]["narration"] = "A new recipe for chocolate cake is popular."
    repair_script_video_queries(script, research)
    with pytest.raises(ValueError, match="narration drifted"):
        validate_script_topic_lock(script, research)


def test_scriptwriter_repairs_one_bad_query_in_single_generation(monkeypatch, research, script):
    script["sections"][1]["video_query_3"] = "penguins swimming across Antarctic waters"
    calls = []
    def generate_once(prompt):
        calls.append(prompt)
        return json.dumps(script)
    monkeypatch.setattr(scriptwriter, "generate", generate_once)
    repaired = scriptwriter.write_script(research, video_type="shorts")
    assert len(calls) == 1
    assert "Halo Studios" in repaired["sections"][1]["video_query_3"]
    validate_script_topic_lock(repaired, research)


def test_scriptwriter_rejects_unrelated_script_even_after_query_repair(monkeypatch, research, script):
    script["sections"][1]["narration"] = "Cooking a delicious pasta dinner is fun."
    monkeypatch.setattr(scriptwriter, "generate", lambda prompt: json.dumps(script))
    with pytest.raises(ValueError, match="narration drifted"):
        scriptwriter.write_script(research, video_type="shorts")
