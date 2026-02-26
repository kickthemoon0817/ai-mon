import json
from collections import defaultdict
from pathlib import Path

from datetime import datetime, timezone

from models import DailyUsage, ModelTokens, RateLimit, ServiceUsage

SESSIONS_DIR = Path.home() / ".codex" / "sessions"


def collect() -> ServiceUsage:
    if not SESSIONS_DIR.exists():
        return ServiceUsage(service="codex")

    daily: dict[str, DailyUsage] = {}
    total_messages = 0
    total_sessions = 0
    total_input = 0
    total_output = 0
    model_token_map: dict[str, dict[str, int]] = defaultdict(lambda: {"input": 0, "output": 0})
    hour_counts: dict[str, int] = defaultdict(int)
    latest_rate_limits: dict | None = None
    latest_rate_ts = ""

    for session_file in sorted(SESSIONS_DIR.rglob("*.jsonl")):
        # Extract date from path: sessions/YYYY/MM/DD/file.jsonl
        parts = session_file.relative_to(SESSIONS_DIR).parts
        if len(parts) >= 3:
            date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
        else:
            continue

        if date_str not in daily:
            daily[date_str] = DailyUsage(date=date_str)

        session_messages = 0
        session_tokens = 0
        total_sessions += 1
        model_name = None

        for line in session_file.read_text(errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")

            if entry_type == "session_meta":
                ts = entry.get("payload", {}).get("timestamp", "")
                if ts and len(ts) >= 13:
                    try:
                        hour = ts[11:13]
                        hour_counts[str(int(hour))] += 1
                    except (ValueError, IndexError):
                        pass

            if entry_type == "turn_context":
                m = entry.get("payload", {}).get("model", "")
                if m:
                    model_name = m

            if entry_type == "event_msg":
                payload = entry.get("payload", {})
                if payload.get("type") == "user_message":
                    session_messages += 1
                if payload.get("type") == "token_count":
                    info = payload.get("info") or {}
                    last = info.get("last_token_usage", {})
                    inp = last.get("input_tokens", 0)
                    out = last.get("output_tokens", 0)
                    session_tokens += inp + out
                    total_input += inp
                    total_output += out
                    if model_name:
                        model_token_map[model_name]["input"] += inp
                        model_token_map[model_name]["output"] += out
                    # Track latest rate limits
                    rl = payload.get("rate_limits")
                    ts = entry.get("timestamp", "")
                    if rl and ts > latest_rate_ts:
                        latest_rate_ts = ts
                        latest_rate_limits = rl

        total_messages += session_messages
        daily[date_str].message_count += session_messages
        daily[date_str].session_count += 1
        daily[date_str].token_count += session_tokens

    daily_usage = sorted(daily.values(), key=lambda d: d.date)

    model_tokens = [
        ModelTokens(model=m, input_tokens=v["input"], output_tokens=v["output"])
        for m, v in model_token_map.items()
    ]

    # Build rate limits from latest data
    rate_limits = []
    if latest_rate_limits:
        for key, label in [("primary", "5h window"), ("secondary", "7d window")]:
            rl = latest_rate_limits.get(key, {})
            if rl:
                resets = rl.get("resets_at")
                resets_iso = None
                if resets:
                    resets_iso = datetime.fromtimestamp(resets, tz=timezone.utc).isoformat()
                rate_limits.append(RateLimit(
                    name=label,
                    used_percent=rl.get("used_percent", 0),
                    window_minutes=rl.get("window_minutes", 0),
                    resets_at=resets_iso,
                ))

    dates = [d.date for d in daily_usage]
    return ServiceUsage(
        service="codex",
        daily_usage=daily_usage,
        model_tokens=model_tokens,
        total_messages=total_messages,
        total_sessions=total_sessions,
        total_tokens=total_input + total_output,
        hour_counts=dict(hour_counts),
        first_date=min(dates) if dates else None,
        last_date=max(dates) if dates else None,
        rate_limits=rate_limits,
    )
