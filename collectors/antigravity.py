from collections import defaultdict
from datetime import datetime
from pathlib import Path

from models import DailyUsage, ServiceUsage

BASE_DIR = Path.home() / ".gemini" / "antigravity"
CONV_DIR = BASE_DIR / "conversations"
IMPLICIT_DIR = BASE_DIR / "implicit"


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

    daily_usage = sorted(daily.values(), key=lambda d: d.date)
    dates = [d.date for d in daily_usage]

    return ServiceUsage(
        service="antigravity",
        daily_usage=daily_usage,
        total_messages=total_conversations,
        total_sessions=total_conversations,
        total_tokens=total_size,  # use file size as proxy
        hour_counts=dict(hour_counts),
        first_date=min(dates) if dates else None,
        last_date=max(dates) if dates else None,
    )
