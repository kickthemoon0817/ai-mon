import json
import logging
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models import DailyUsage, ModelTokens, RateLimit, ServiceUsage

log = logging.getLogger(__name__)

STATS_PATH = Path.home() / ".claude" / "stats-cache.json"
PROJECTS_DIR = Path.home() / ".claude" / "projects"

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
KEYCHAIN_SERVICE = "Claude Code-credentials"

# Map API response fields to display names and window sizes
_API_WINDOWS = {
    "five_hour": ("5h window", 300),
    "seven_day": ("7d window", 10080),
    "seven_day_opus": ("7d opus", 10080),
    "seven_day_sonnet": ("7d sonnet", 10080),
}


def _query_usage_api() -> list[RateLimit]:
    """Query Claude's live usage API for real utilization percentages."""
    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if raw.returncode != 0:
            log.debug("Keychain lookup failed: %s", raw.stderr.strip())
            return []

        creds = json.loads(raw.stdout.strip())
        token = creds.get("claudeAiOauth", {}).get("accessToken")
        if not token:
            log.debug("No accessToken in keychain credentials")
            return []

        req = urllib.request.Request(
            USAGE_API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
    except Exception as exc:
        log.debug("Usage API call failed: %s", exc)
        return []

    limits: list[RateLimit] = []
    for key, (name, window_min) in _API_WINDOWS.items():
        entry = body.get(key)
        if entry is None:
            continue
        limits.append(RateLimit(
            name=name,
            used_percent=entry.get("utilization", 0.0),
            window_minutes=window_min,
            resets_at=entry.get("resets_at"),
        ))
    return limits


def _compute_window_usage() -> list[RateLimit]:
    """Compute rolling 5h and 7d token usage from session JSONL files."""
    if not PROJECTS_DIR.exists():
        return []

    now = datetime.now(timezone.utc)
    five_h_ago = now - timedelta(hours=5)
    seven_d_ago = now - timedelta(days=7)

    tokens_5h = 0
    tokens_7d = 0
    oldest_5h: datetime | None = None
    oldest_7d: datetime | None = None

    # Per-model accumulators: {model: {input, output, cache_read, cache_create, count}}
    models_5h: dict[str, dict] = {}
    models_7d: dict[str, dict] = {}

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
                if ts < seven_d_ago:
                    continue

                usage = data.get("message", {}).get("usage", {})
                inp = usage.get("input_tokens", 0)
                out = usage.get("output_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
                cache_create = usage.get("cache_creation_input_tokens", 0)
                total = inp + out + cache_read + cache_create

                model = data.get("message", {}).get("model", "unknown")

                if ts >= five_h_ago:
                    tokens_5h += total
                    if oldest_5h is None or ts < oldest_5h:
                        oldest_5h = ts
                    acc = models_5h.setdefault(model, {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "count": 0})
                    acc["input"] += inp
                    acc["output"] += out
                    acc["cache_read"] += cache_read
                    acc["cache_create"] += cache_create
                    acc["count"] += 1

                tokens_7d += total
                if oldest_7d is None or ts < oldest_7d:
                    oldest_7d = ts
                acc = models_7d.setdefault(model, {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "count": 0})
                acc["input"] += inp
                acc["output"] += out
                acc["cache_read"] += cache_read
                acc["cache_create"] += cache_create
                acc["count"] += 1
        except (json.JSONDecodeError, ValueError, OSError):
            continue

    five_h_reset = (oldest_5h + timedelta(hours=5)).isoformat() if oldest_5h else None
    seven_d_reset = (oldest_7d + timedelta(days=7)).isoformat() if oldest_7d else None

    def _build_breakdown(acc: dict[str, dict]) -> list[ModelTokens]:
        return sorted(
            [
                ModelTokens(
                    model=model,
                    input_tokens=v["input"],
                    output_tokens=v["output"],
                    cache_read_tokens=v["cache_read"],
                    cache_creation_tokens=v["cache_create"],
                )
                for model, v in acc.items()
            ],
            key=lambda m: m.input_tokens + m.output_tokens + m.cache_read_tokens + m.cache_creation_tokens,
            reverse=True,
        )

    return [
        RateLimit(
            name="5h window",
            used_percent=0,
            window_minutes=300,
            resets_at=five_h_reset,
            used_tokens=tokens_5h,
            model_breakdown=_build_breakdown(models_5h),
        ),
        RateLimit(
            name="7d window",
            used_percent=0,
            window_minutes=10080,
            resets_at=seven_d_reset,
            used_tokens=tokens_7d,
            model_breakdown=_build_breakdown(models_7d),
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

    # Merge live API utilization with JSONL-computed token data
    jsonl_limits = _compute_window_usage()
    api_limits = _query_usage_api()

    if api_limits:
        api_by_name = {rl.name: rl for rl in api_limits}
        merged: list[RateLimit] = []
        seen_names: set[str] = set()
        for jrl in jsonl_limits:
            if jrl.name in api_by_name:
                arl = api_by_name[jrl.name]
                merged.append(RateLimit(
                    name=jrl.name,
                    used_percent=arl.used_percent,
                    window_minutes=jrl.window_minutes,
                    resets_at=arl.resets_at,
                    used_tokens=jrl.used_tokens,
                    model_breakdown=jrl.model_breakdown,
                ))
            else:
                merged.append(jrl)
            seen_names.add(jrl.name)
        # Add API-only windows (e.g. opus/sonnet-specific)
        for arl in api_limits:
            if arl.name not in seen_names:
                merged.append(arl)
        rate_limits = merged
    else:
        rate_limits = jsonl_limits

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
