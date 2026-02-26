import json
from pathlib import Path

from models import DailyUsage, ModelTokens, ServiceUsage

STATS_PATH = Path.home() / ".claude" / "stats-cache.json"


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
    )
