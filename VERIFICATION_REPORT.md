# Verification Report — US Trending Topics v9

## Final content mode
- `US_TREND_EXPLANATION`
- Broad current US YouTube discovery.
- No fixed Anime/Marvel or other topical keyword list.
- No fixed topic-category allowlist.
- Candidate category metadata is retained only as metadata/context; it never changes selection priority or rejection.
- Gemini selects one current candidate from the measured US trend pool.
- The selected candidate is the canonical source subject for research, script, media, and upload metadata.

## Discovery
- Default source: YouTube `mostPopular` for `regionCode=US`.
- `DISCOVERY_CATEGORY_IDS` defaults to empty, so discovery is not restricted to a fixed category set.
- Candidate ordering is based on observed trend score and views only; there is no film/entertainment category boost.
- Recency, views, likes, comments, and velocity contribute to the trend score.
- Used-topic filtering remains enabled.

## Gemini resilience
- Preferred model: `gemini-3.5-flash-lite`.
- Fallback chain includes `gemini-2.5-flash-lite`, `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.1-flash-lite`, `gemini-3.5-flash`, and `gemini-2.5-flash`.
- Transient 503/504/429/5xx/timeouts use application-level retries and model fallback.
- Whole-task recovery is enabled after the configured model chain is exhausted.
- Startup health-check requests remain disabled.

## Schedule / upload
- Monday-Friday: 20:00 and 22:00 `Asia/Kolkata` — Shorts.
- Tuesday-Saturday: 00:30 `Asia/Kolkata` — the third Shorts slot for the previous weekday evening.
- Saturday: 17:00 `Asia/Kolkata` — Long.
- Sunday: 17:00 `Asia/Kolkata` — Long.
- `VIDEO_PRIVACY=public` is explicit in the workflow and config.
- Scheduled video type is explicitly resolved from the triggering cron so the Saturday 00:30 third-Shorts run cannot be mistaken for the Saturday Long run.

## Runtime compatibility
- GitHub Actions Python: 3.11.
- MoviePy pinned to 1.0.3 for the legacy `moviepy.editor` API.

## Validation performed
- Full pytest suite: **514 passed**.
- Python `compileall`: **PASS**.
- 100 deterministic category-agnostic schedule/discovery invariant iterations: **PASS**.
- Runtime source scan: no category-priority helper remains.
- `.env` remains ignored; no plaintext `.env` is packaged.

## Important limitation
- The full 514-test suite was not executed 100 times in this environment because repeated pytest process startup exceeded the execution timeout. The single full suite run passed, and the deterministic 100-iteration invariant loop passed.
