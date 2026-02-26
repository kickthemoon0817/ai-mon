import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from models import DailyUsage, ModelTokens, ServiceUsage

BASE_DIR = Path.home() / ".gemini" / "antigravity"
CONV_DIR = BASE_DIR / "conversations"
IMPLICIT_DIR = BASE_DIR / "implicit"
DAEMON_DIR = BASE_DIR / "daemon"
TMP_DIR = Path.home() / ".gemini" / "tmp"

_PLANNER_RE = re.compile(r"Requesting planner with (\d+) chat messages")
_LOG_TS_RE = re.compile(r"^[IE](\d{4}) (\d{2}:\d{2}:\d{2})")
_MODEL_RE = re.compile(r"model (gemini-[a-z0-9._-]+)")


def _parse_session_jsons() -> dict[str, dict[str, int]]:
    """Parse ~/.gemini/tmp/*/chats/session-*.json for per-model token data."""
    model_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"input": 0, "output": 0, "cached": 0, "thoughts": 0, "requests": 0}
    )

    if not TMP_DIR.exists():
        return dict(model_stats)

    for session_file in TMP_DIR.rglob("session-*.json"):
        try:
            data = json.loads(session_file.read_text(errors="replace"))
            for msg in data.get("messages", []):
                model = msg.get("model")
                tokens = msg.get("tokens")
                if model and tokens:
                    model_stats[model]["input"] += tokens.get("input", 0)
                    model_stats[model]["output"] += tokens.get("output", 0)
                    model_stats[model]["cached"] += tokens.get("cached", 0)
                    model_stats[model]["thoughts"] += tokens.get("thoughts", 0)
                    model_stats[model]["requests"] += 1
        except (json.JSONDecodeError, OSError):
            continue

    return dict(model_stats)


def _parse_daemon_logs() -> tuple[dict[str, int], dict[str, int]]:
    """Parse daemon logs for per-model request counts and daily request counts."""
    model_requests: dict[str, int] = defaultdict(int)
    daily_requests: dict[str, int] = defaultdict(int)

    if not DAEMON_DIR.exists():
        return dict(model_requests), dict(daily_requests)

    current_year = datetime.now().year

    for log_file in DAEMON_DIR.glob("*.log"):
        current_model = None
        for line in log_file.read_text(errors="replace").splitlines():
            model_match = _MODEL_RE.search(line)
            if model_match:
                current_model = model_match.group(1)

            planner_match = _PLANNER_RE.search(line)
            if planner_match:
                ts_match = _LOG_TS_RE.match(line)
                if ts_match:
                    mmdd = ts_match.group(1)
                    date_str = f"{current_year}-{mmdd[:2]}-{mmdd[2:]}"
                    daily_requests[date_str] += 1
                if current_model:
                    model_requests[current_model] += 1

    return dict(model_requests), dict(daily_requests)


def collect() -> ServiceUsage:
    if not BASE_DIR.exists():
        return ServiceUsage(service="antigravity")

    daily: dict[str, DailyUsage] = {}
    total_conversations = 0
    total_size = 0
    hour_counts: dict[str, int] = defaultdict(int)

    dirs = []
    if CONV_DIR.exists():
        dirs.append(CONV_DIR)
    if IMPLICIT_DIR.exists():
        dirs.append(IMPLICIT_DIR)

    for scan_dir in dirs:
        for pb_file in scan_dir.glob("*.pb"):
            stat = pb_file.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime)
            date_str = mtime.strftime("%Y-%m-%d")
            size = stat.st_size

            if date_str not in daily:
                daily[date_str] = DailyUsage(date=date_str)

            daily[date_str].conversation_count += 1
            daily[date_str].file_size_bytes += size
            total_conversations += 1
            total_size += size
            hour_counts[str(mtime.hour)] += 1

    # Parse session JSONs for per-model token data
    session_model_stats = _parse_session_jsons()

    # Parse daemon logs for request counts
    daemon_model_requests, daily_requests = _parse_daemon_logs()

    # Merge daily request counts
    for date_str, count in daily_requests.items():
        if date_str not in daily:
            daily[date_str] = DailyUsage(date=date_str)
        daily[date_str].message_count += count

    # Build model tokens - prefer session data (has real tokens), fall back to daemon data
    model_tokens = []
    all_models = set(session_model_stats.keys()) | set(daemon_model_requests.keys())
    total_all_tokens = 0

    for model in sorted(all_models):
        sess = session_model_stats.get(model, {})
        daemon_reqs = daemon_model_requests.get(model, 0)
        inp = sess.get("input", 0)
        out = sess.get("output", 0)
        cached = sess.get("cached", 0)
        thoughts = sess.get("thoughts", 0)
        requests = sess.get("requests", 0) or daemon_reqs

        model_tokens.append(ModelTokens(
            model=model,
            input_tokens=inp,
            output_tokens=out,
            cache_read_tokens=cached,
            cache_creation_tokens=thoughts,
        ))
        total_all_tokens += inp + out

    daily_usage = sorted(daily.values(), key=lambda d: d.date)
    dates = [d.date for d in daily_usage]

    return ServiceUsage(
        service="antigravity",
        daily_usage=daily_usage,
        model_tokens=model_tokens,
        total_messages=total_conversations,
        total_sessions=total_conversations,
        total_tokens=total_all_tokens or sum(daemon_model_requests.values()),
        hour_counts=dict(hour_counts),
        first_date=min(dates) if dates else None,
        last_date=max(dates) if dates else None,
    )
