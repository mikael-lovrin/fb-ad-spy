# -*- coding: utf-8 -*-
"""
Database persistence layer — supports both SQLite (local) and PostgreSQL (Supabase cloud).

Switch via environment variable:
  DATABASE_URL=postgresql://...  →  PostgreSQL  (Supabase / any Postgres)
  (not set)                      →  SQLite       (local file at data/ads.db)

Interface is identical for callers — all functions work with either backend.
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from core.config import DATABASE_URL, DB_PATH

logger = logging.getLogger(__name__)

_USE_POSTGRES = bool(DATABASE_URL)

if _USE_POSTGRES:
    import psycopg2
    import psycopg2.extras


# ---------------------------------------------------------------------------
# Schema — kept identical for both backends except the primary key type.
# PostgreSQL uses BIGSERIAL; SQLite uses INTEGER PRIMARY KEY AUTOINCREMENT.
# ---------------------------------------------------------------------------

_SCHEMA_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS keyword_snapshots (
    id              {pk},
    keyword         TEXT NOT NULL,
    niche           TEXT,
    country         TEXT DEFAULT 'US',
    active_ad_count INTEGER,
    video_count     INTEGER DEFAULT 0,
    image_count     INTEGER DEFAULT 0,
    top_pages       TEXT,
    snapshot_at     TEXT NOT NULL,
    fb_library_url  TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap_keyword ON keyword_snapshots(keyword);
CREATE INDEX IF NOT EXISTS idx_snap_at      ON keyword_snapshots(snapshot_at);
"""

_SCHEMA_ADS = """
CREATE TABLE IF NOT EXISTS ads (
    id                  {pk},
    ad_archive_id       TEXT UNIQUE,
    page_id             TEXT,
    page_name           TEXT,
    ad_snapshot_url     TEXT,
    ad_body             TEXT,
    ad_title            TEXT,
    ad_description      TEXT,
    ad_link_url         TEXT,
    start_date          TEXT,
    stop_date           TEXT,
    days_running        INTEGER,
    active_status       TEXT DEFAULT 'ACTIVE',
    impressions_min     TEXT,
    impressions_max     TEXT,
    spend_min           TEXT,
    spend_max           TEXT,
    currency            TEXT,
    publisher_platforms TEXT,
    keyword_found       TEXT,
    collected_at        TEXT,
    ad_type             TEXT,
    industry            TEXT,
    hook                TEXT,
    text_summary        TEXT,
    pain_points         TEXT,
    benefits            TEXT,
    cta                 TEXT,
    format              TEXT,
    image_analysis      TEXT,
    video_transcript    TEXT,
    video_analysis      TEXT,
    swipe_score         INTEGER,
    collation_count     INTEGER,
    image_url           TEXT,
    video_url           TEXT,
    ad_format           TEXT,
    card_count          INTEGER DEFAULT 0,
    analyzed_at         TEXT,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_page_id      ON ads(page_id);
CREATE INDEX IF NOT EXISTS idx_industry     ON ads(industry);
CREATE INDEX IF NOT EXISTS idx_swipe_score  ON ads(swipe_score);
CREATE INDEX IF NOT EXISTS idx_days_running ON ads(days_running);
CREATE INDEX IF NOT EXISTS idx_collected_at ON ads(collected_at);
CREATE INDEX IF NOT EXISTS idx_active_status ON ads(active_status);
"""

_SCHEMA_REPORTS = """
CREATE TABLE IF NOT EXISTS benchmark_reports (
    id              {pk},
    niche           TEXT NOT NULL,
    generated_at    TEXT NOT NULL,
    report_md       TEXT,
    data_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_report_niche ON benchmark_reports(niche);
CREATE INDEX IF NOT EXISTS idx_report_at    ON benchmark_reports(generated_at);
"""


def _build_schemas() -> list[str]:
    """Return individual CREATE TABLE/INDEX statements for the active backend."""
    pk = "BIGSERIAL PRIMARY KEY" if _USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    stmts = []
    for block in [_SCHEMA_SNAPSHOTS, _SCHEMA_ADS, _SCHEMA_REPORTS]:
        for stmt in block.format(pk=pk).split(";"):
            s = stmt.strip()
            if s:
                stmts.append(s)
    return stmts


# ---------------------------------------------------------------------------
# Connection abstraction
# Wraps both sqlite3 and psycopg2 behind a uniform execute() / fetchall() API.
# ---------------------------------------------------------------------------

class _Conn:
    """
    Thin wrapper that normalises sqlite3 and psycopg2 connections.

    Callers use:  conn.execute(sql, params).fetchall()  — identical to sqlite3.
    Differences handled internally:
      - placeholder: sqlite3 uses ?, psycopg2 uses %s
      - row type:    sqlite3 Row  vs  psycopg2 RealDictRow  (both support dict())
    """

    def __init__(self, raw_conn):
        self._conn = raw_conn
        if _USE_POSTGRES:
            self._cur = raw_conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            )
        else:
            raw_conn.row_factory = sqlite3.Row
            self._cur = raw_conn

    def execute(self, sql: str, params=None):
        if _USE_POSTGRES:
            # psycopg2 uses %s placeholders; convert from sqlite3's ?
            sql = sql.replace("?", "%s")
            self._cur.execute(sql, params or ())
            return self._cur
        else:
            # sqlite3: execute on connection returns a cursor directly
            return self._conn.execute(sql, params or ())

    def executemany(self, sql: str, seq):
        if _USE_POSTGRES:
            sql = sql.replace("?", "%s")
            self._cur.executemany(sql, seq)
        else:
            self._conn.executemany(sql, seq)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


@contextmanager
def get_conn():
    """Yield a normalised _Conn for the active database backend."""
    if _USE_POSTGRES:
        raw = psycopg2.connect(DATABASE_URL)
    else:
        raw = sqlite3.connect(DB_PATH)
        raw.execute("PRAGMA journal_mode=WAL")

    conn = _Conn(raw)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema init + migrations
# ---------------------------------------------------------------------------

def _migrate(conn: _Conn, table: str, column: str, definition: str) -> None:
    """Add a column if it doesn't exist (idempotent)."""
    if _USE_POSTGRES:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? AND column_name = ?",
            (table, column),
        ).fetchall()
        exists = len(rows) > 0
    else:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        exists = any(dict(r)["name"] == column for r in rows)

    if not exists:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        logger.info(f"Migration: added {table}.{column}")


def init_db() -> None:
    """Create tables and run any pending column migrations."""
    with get_conn() as conn:
        for stmt in _build_schemas():
            conn.execute(stmt)
        # Migrations for columns added after initial deployment
        _migrate(conn, "keyword_snapshots", "video_count", "INTEGER DEFAULT 0")
        _migrate(conn, "keyword_snapshots", "image_count", "INTEGER DEFAULT 0")
        _migrate(conn, "ads", "collation_count", "INTEGER")
        _migrate(conn, "ads", "image_url",        "TEXT")
        _migrate(conn, "ads", "video_url",         "TEXT")
        _migrate(conn, "ads", "ad_format",         "TEXT")
        _migrate(conn, "ads", "card_count",        "INTEGER DEFAULT 0")

    backend = "PostgreSQL (Supabase)" if _USE_POSTGRES else f"SQLite ({DB_PATH})"
    logger.info(f"DB initialized: {backend}")


# ---------------------------------------------------------------------------
# Ad CRUD
# ---------------------------------------------------------------------------

_AD_FIELDS = [
    "ad_archive_id", "page_id", "page_name", "ad_snapshot_url",
    "ad_body", "ad_title", "ad_description", "ad_link_url",
    "start_date", "stop_date", "days_running", "active_status",
    "impressions_min", "impressions_max", "spend_min", "spend_max",
    "currency", "publisher_platforms", "keyword_found", "collected_at",
    "ad_type", "industry", "hook", "text_summary", "pain_points",
    "benefits", "cta", "format", "image_analysis", "video_transcript",
    "video_analysis", "swipe_score", "collation_count", "image_url", "video_url",
    "ad_format", "card_count", "analyzed_at", "notes",
]


def upsert_ad(ad: dict) -> bool:
    """Insert or update a single ad. Returns True on success."""
    if isinstance(ad.get("publisher_platforms"), list):
        ad = {**ad, "publisher_platforms": json.dumps(ad["publisher_platforms"])}

    filtered = {k: ad.get(k) for k in _AD_FIELDS}
    cols         = ", ".join(filtered.keys())
    placeholders = ", ".join(["?" for _ in filtered])
    updates      = ", ".join(
        [f"{k}=excluded.{k}" for k in filtered if k != "ad_archive_id"]
    )

    sql = (
        f"INSERT INTO ads ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(ad_archive_id) DO UPDATE SET {updates}"
    )

    with get_conn() as conn:
        conn.execute(sql, list(filtered.values()))
    return True


def bulk_upsert(ads: list[dict]) -> dict:
    """Upsert multiple ads. Returns stats."""
    stats = {"inserted": 0, "errors": 0}
    for ad in ads:
        try:
            upsert_ad(ad)
            stats["inserted"] += 1
        except Exception as e:
            logger.error(f"Failed to save ad {ad.get('ad_archive_id')}: {e}")
            stats["errors"] += 1
    return stats


def get_unanalyzed_ads(limit: int = 100) -> list[dict]:
    """Return ads not yet processed by analyze_agent."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ads WHERE analyzed_at IS NULL "
            "ORDER BY collation_count DESC NULLS LAST LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_analysis(ad_archive_id: str, analysis: dict) -> None:
    """Write analysis fields back to an ad row."""
    analysis["analyzed_at"] = datetime.now().isoformat()
    fields = ", ".join([f"{k}=?" for k in analysis])
    values = list(analysis.values()) + [ad_archive_id]
    with get_conn() as conn:
        conn.execute(
            f"UPDATE ads SET {fields} WHERE ad_archive_id=?", values
        )


def query_ads(
    niche: str = None,
    min_days: int = None,
    min_score: int = None,
    active_only: bool = True,
    limit: int = 200,
) -> list[dict]:
    """Flexible query used by the dashboard and exports."""
    clauses: list[str] = []
    params:  list      = []

    if active_only:
        clauses.append("active_status='ACTIVE'")
    if niche:
        clauses.append("industry LIKE ?")
        params.append(f"%{niche}%")
    if min_days is not None:
        clauses.append("days_running >= ?")
        params.append(min_days)
    if min_score is not None:
        clauses.append("swipe_score >= ?")
        params.append(min_score)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM ads {where} ORDER BY swipe_score DESC, days_running DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def get_stats() -> dict:
    """Overall DB statistics."""
    with get_conn() as conn:
        total    = dict(conn.execute("SELECT COUNT(*) AS n FROM ads").fetchone())["n"]
        active   = dict(conn.execute("SELECT COUNT(*) AS n FROM ads WHERE active_status='ACTIVE'").fetchone())["n"]
        analyzed = dict(conn.execute("SELECT COUNT(*) AS n FROM ads WHERE analyzed_at IS NOT NULL").fetchone())["n"]
        by_ind   = conn.execute(
            "SELECT industry, COUNT(*) as n FROM ads "
            "WHERE industry IS NOT NULL GROUP BY industry ORDER BY n DESC"
        ).fetchall()
    return {
        "total": total, "active": active, "analyzed": analyzed,
        "by_industry": [dict(r) for r in by_ind],
    }


# ---------------------------------------------------------------------------
# Keyword snapshots
# ---------------------------------------------------------------------------

def save_snapshot(
    keyword: str,
    niche: str,
    active_ad_count: int,
    top_pages: list[dict],
    video_count: int = 0,
    image_count: int = 0,
    country: str = "US",
    fb_library_url: str = "",
) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO keyword_snapshots "
            "(keyword, niche, country, active_ad_count, video_count, image_count, "
            " top_pages, snapshot_at, fb_library_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                keyword, niche, country, active_ad_count, video_count, image_count,
                json.dumps(top_pages, ensure_ascii=False),
                datetime.now().isoformat(),
                fb_library_url,
            ),
        )


def update_snapshot_media_counts(keyword: str, country: str = "US") -> None:
    """Recompute video/image counts from actual ad_type values in the ads table."""
    with get_conn() as conn:
        video_count = dict(conn.execute(
            "SELECT COUNT(*) AS n FROM ads WHERE keyword_found=? AND ad_type='video' AND active_status='ACTIVE'",
            (keyword,),
        ).fetchone())["n"]
        image_count = dict(conn.execute(
            "SELECT COUNT(*) AS n FROM ads WHERE keyword_found=? AND ad_type='image' AND active_status='ACTIVE'",
            (keyword,),
        ).fetchone())["n"]
        conn.execute(
            "UPDATE keyword_snapshots SET video_count=?, image_count=? "
            "WHERE keyword=? AND country=? "
            "AND id=(SELECT MAX(id) FROM keyword_snapshots WHERE keyword=? AND country=?)",
            (video_count, image_count, keyword, country, keyword, country),
        )


def get_keyword_trend(keyword: str, days: int = 30) -> list[dict]:
    """Return snapshots for a keyword over the last N days."""
    since = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    since -= timedelta(days=days)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM keyword_snapshots WHERE keyword=? AND snapshot_at>=? "
            "ORDER BY snapshot_at ASC",
            (keyword, since.isoformat()),
        ).fetchall()
        return [dict(r) for r in rows]


def get_latest_snapshots(niche: str = None, country: str = "US") -> list[dict]:
    """Latest snapshot per keyword — used by dashboard and min-ads filtering."""
    niche_filter = "AND niche=?" if niche else ""
    params: list = [country]
    if niche:
        params.append(niche)
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT s.* FROM keyword_snapshots s
               INNER JOIN (
                   SELECT keyword, MAX(snapshot_at) AS latest
                   FROM keyword_snapshots
                   WHERE country=? {niche_filter}
                   GROUP BY keyword
               ) m ON s.keyword=m.keyword AND s.snapshot_at=m.latest
               ORDER BY s.active_ad_count DESC""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Benchmark reports (agents/benchmark_agent.py)
# ---------------------------------------------------------------------------

def save_benchmark_report(niche: str, report_md: str, data: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO benchmark_reports (niche, generated_at, report_md, data_json) "
            "VALUES (?, ?, ?, ?)",
            (niche, datetime.now().isoformat(), report_md, json.dumps(data, ensure_ascii=False, default=str)),
        )


def get_latest_benchmark_report(niche: str) -> dict | None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM benchmark_reports WHERE niche=? ORDER BY generated_at DESC LIMIT 1",
            (niche,),
        ).fetchall()
        return dict(rows[0]) if rows else None


def get_benchmark_history(niche: str, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, niche, generated_at, report_md FROM benchmark_reports "
            "WHERE niche=? ORDER BY generated_at DESC LIMIT ?",
            (niche, limit),
        ).fetchall()
        return [dict(r) for r in rows]
