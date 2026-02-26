import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from models import DailyUsage, ModelTokens, ServiceUsage

BASE_DIR = Path.home() / ".gemini" / "antigravity"
CONV_DIR = BASE_DIR / "conversations"
IMPLICIT_DIR = BASE_DIR / "implicit"
DAEMON_DIR = BASE_DIR / "daemon"

# Matches log lines like: I0226 16:12:47.537729 96613 planner_generator.go:288]
# and error lines referencing model names
_LOG_TS_RE = re.compile(r"^[IE](\d{4}) (\d{2}:\d{2}:\d{2})")
_MODEL_RE = re.compile(r"model (gemini-[a-z0-9._-]+)")
_PLANNER_RE = re.compile(r"Requesting planner with (\d+) chat messages")


def _parse_daemon_logs() -> tuple[dict[str, int], dict[str, int]]:
    """Parse daemon logs to extract per-model request counts and daily request counts."""
    model_requests: dict[str, int] = defaultdict(int)
    daily_requests: dict[str, int] = defaultdict(int)

    if not DAEMON_DIR.exists():
        return dict(model_requests), dict(daily_requests)

    current_year = datetime.now().year

    for log_file in DAEMON_DIR.glob("*.log"):
        current_model = None
        for line in log_file.read_text(errors="replace").splitlines():
            # Track model mentions (from errors or capacity messages)
            model_match = _MODEL_RE.search(line)
            if model_match:
                current_model = model_match.group(1)

            # Count planner requests (each = one AI request)
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

    # Parse daemon logs for model usage
    model_requests, daily_requests = _parse_daemon_logs()

    # Merge daily request counts into daily usage
    for date_str, count in daily_requests.items():
        if date_str not in daily:
            daily[date_str] = DailyUsage(date=date_str)
        daily[date_str].message_count += count

    model_tokens = [
        ModelTokens(model=model, input_tokens=count, output_tokens=0)
        for model, count in sorted(model_requests.items())
    ]

    total_model_requests = sum(model_requests.values())

    daily_usage = sorted(daily.values(), key=lambda d: d.date)
    dates = [d.date for d in daily_usage]

    return ServiceUsage(
        service="antigravity",
        daily_usage=daily_usage,
        model_tokens=model_tokens,
        total_messages=total_conversations,
        total_sessions=total_conversations,
        total_tokens=total_model_requests,
        hour_counts=dict(hour_counts),
        first_date=min(dates) if dates else None,
        last_date=max(dates) if dates else None,
    )
