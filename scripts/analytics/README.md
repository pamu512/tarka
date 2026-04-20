# Analytics tooling

- **`export_weekly_scorecard_json.py`** — N4.2 weekly aggregate export stub: calls analytics-sink `GET /v1/analytics/scorecard`, writes wrapped JSON (stdout or `-o`). Use with cron or upload to object storage.
- **`publish_scorecard_discussion.py`** — OSS #53: same scorecard JSON, opens a GitHub Discussion via GraphQL (see `.github/workflows/scorecard-discussion.yml`).

Both expect `SCORECARD_BASE_URL` to your UI gateway analytics prefix (e.g. `https://host/api/analytics`, no trailing slash) unless you run against the service directly.
