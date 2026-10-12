from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "daily-short.yml"
CONFIG = ROOT / "config.py"
ENV_EXAMPLE = ROOT / ".env.example"
PIPELINE = ROOT / "pipeline.py"
README = ROOT / "README.md"
SETUP = ROOT / "SETUP.md"


def test_timezone_aware_schedule_is_exact():
    text = WORKFLOW.read_text(encoding="utf-8")
    expected = [
        'cron: "0 20 * * 1-5"',
        'cron: "0 22 * * 1-5"',
        'cron: "30 0 * * 2-6"',
        'cron: "0 17 * * 6"',
        'cron: "0 17 * * 0"',
    ]
    for line in expected:
        assert line in text
    assert text.count('timezone: "Asia/Kolkata"') == 5
    assert '30 8 * * 1-5' not in text
    assert '50 10 * * 1-5' not in text
    assert '6 12 * * 1-5' not in text
    assert '0 14 * * 1-5' not in text
    assert '0 16 * * 1-5' not in text
    assert '0 18 * * 1-5' not in text


def test_public_upload_is_explicit():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    config = CONFIG.read_text(encoding="utf-8")
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "VIDEO_PRIVACY: public" in workflow
    assert 'VIDEO_PRIVACY = os.getenv("VIDEO_PRIVACY", "public")' in config
    assert "VIDEO_PRIVACY=public" in env_example


def test_production_runs_are_serialized():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "concurrency:" in text
    assert "group: daily-youtube-pipeline" in text
    assert "cancel-in-progress: false" in text


def test_pipeline_comments_match_timezone_aware_schedule():
    text = PIPELINE.read_text(encoding="utf-8")
    assert "workflow schedule itself is explicitly" in text
    assert "UTC is what the cron trigger fires on" not in text


def test_docs_contain_current_schedule():
    for path in (README, SETUP):
        text = path.read_text(encoding="utf-8")
        assert "8:00 PM IST" in text
        assert "10:00 PM IST" in text
        assert "12:30 AM IST" in text
        assert "previous weekday evening" in text
        assert "5:00 PM IST" in text
