import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from models import ServiceUsage, UsageSummary
from collectors import claude, codex, antigravity

DB_PATH = Path(__file__).parent / "usage.db"

_COLLECTORS = {
    "claude": claude.collect,
    "codex": codex.collect,
    "antigravity": antigravity.collect,
}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            service TEXT NOT NULL,
            data TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (service)
        )
    """)
    conn.commit()
    return conn


def refresh_all() -> UsageSummary:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    services = []
    for name, collect_fn in _COLLECTORS.items():
        usage = collect_fn()
        conn.execute(
            "INSERT OR REPLACE INTO snapshots (service, data, updated_at) VALUES (?, ?, ?)",
            (name, usage.model_dump_json(), now),
        )
        services.append(usage)
    conn.commit()
    conn.close()
    return UsageSummary(services=services, last_refreshed=now)


def get_summary() -> UsageSummary:
    conn = _get_conn()
    rows = conn.execute("SELECT service, data, updated_at FROM snapshots").fetchall()
    conn.close()
    if not rows:
        return refresh_all()
    services = [ServiceUsage.model_validate_json(row[1]) for row in rows]
    last = max(row[2] for row in rows)
    return UsageSummary(services=services, last_refreshed=last)


def get_service(name: str) -> ServiceUsage | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT data FROM snapshots WHERE service = ?", (name,)
    ).fetchone()
    conn.close()
    if row:
        return ServiceUsage.model_validate_json(row[0])
    # Try collecting fresh
    if name in _COLLECTORS:
        return _COLLECTORS[name]()
    return None
