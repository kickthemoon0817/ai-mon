import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models import DailyUsage, ModelTokens, RateLimit, ServiceUsage

STATS_PATH = Path.home() / ".claude" / "stats-cache.json"
PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _compute_window_usage() -> list[RateLimit]:
    """Compute rolling 5h and 7d token usage from session JSONL files."""
    if not PROJECTS_DIR.exists():
        return []

    now = datetime.now(timezone.utc)
    five_h_ago = now - timedelta(hours=5)
    seven_d_ago = now - timedelta(days=7)

    tokens_5h = 0
    tokens_7d = 0

    for fp in PROJECTS_DIR.rglob("*.jsonl"):
        if "tool-results" in str(fp):
            continue
        try:
            for line in fp.read_text(errors="replace").splitlines():
                if '"assistant"' not in line:
                    continue
                data = json.loads(line)
                if data.get("type") != "assistant":
                    continue
                ts_str = data.get("timestamp", "")
                if not ts_str:
                    continue
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                usage = data.get("message", {}).get("usage", {})
                total = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

                if ts >= five_h_ago:
                    tokens_5h += total
                if ts >= seven_d_ago:
                    tokens_7d += total
        except (json.JSONDecodeError, ValueError, OSError):
            continue

    five_h_reset = (now + timedelta(hours=5)).isoformat()
    seven_d_reset = (now + timedelta(days=7)).isoformat()

    return [
        RateLimit(
            name="5h window",
            used_percent=0,  # no known limit, show raw tokens
            window_minutes=300,
            resets_at=five_h_reset,
            used_tokens=tokens_5h,
        ),
        RateLimit(
            name="7d window",
            used_percent=0,
            window_minutes=10080,
            resets_at=seven_d_reset,
            used_tokens=tokens_7d,
        ),
    ]


def collect() -> ServiceUsage:
    if not STATS_PATH.exists():
        return ServiceUsage(service="claude")

    data = json.loads(STATS_PATH.read_text())

    daily_usage = []
    for day in data.get("dailyActivity", []):
        daily_usage.append(DailyUsage(
            date=day["date"],
            message_count=day.get("messageCount", 0),
            session_count=day.get("sessionCount", 0),
            tool_call_count=day.get("toolCallCount", 0),
        ))

    # Merge token totals into daily_usage by date
    token_by_date: dict[str, int] = {}
    for day in data.get("dailyModelTokens", []):
        total = sum(day.get("tokensByModel", {}).values())
        token_by_date[day["date"]] = total
    for du in daily_usage:
        du.token_count = token_by_date.get(du.date, 0)

    model_tokens = []
    for model, usage in data.get("modelUsage", {}).items():
        model_tokens.append(ModelTokens(
            model=model,
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
            cache_read_tokens=usage.get("cacheReadInputTokens", 0),
            cache_creation_tokens=usage.get("cacheCreationInputTokens", 0),
        ))

    hour_counts = data.get("hourCounts", {})
    rate_limits = _compute_window_usage()

    dates = [d.date for d in daily_usage]
    return ServiceUsage(
        service="claude",
        daily_usage=daily_usage,
        model_tokens=model_tokens,
        total_messages=data.get("totalMessages", 0),
        total_sessions=data.get("totalSessions", 0),
        total_tokens=sum(
            mt.input_tokens + mt.output_tokens
            for mt in model_tokens
        ),
        hour_counts=hour_counts,
        first_date=min(dates) if dates else None,
        last_date=max(dates) if dates else None,
        rate_limits=rate_limits,
    )
