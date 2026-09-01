"""SQLite price history store with cabin and FX isolation.

Migration-only: never alters source JSON files. Uses WAL mode for
concurrent reads during GHA scans.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Mapping, Sequence


SCHEMA_VERSION = 6


@dataclass
class PriceObservation:
    """A single price observation for an itinerary."""
    run_id: str
    itinerary_fingerprint: str
    offer_fingerprint: str
    bucket: str
    cabin_class: str
    native_amount: float
    native_currency: str
    fx_rate_to_gbp: float
    airfare_gbp: float
    baggage_normalized_gbp: float
    d2d_cash_gbp: float
    business_premium_gbp: Optional[float]
    business_to_economy_ratio: Optional[float]
    upgrade_cost_per_business_hour: Optional[float]
    source_observed_at: str
    available: bool = True


class FlightPriceHistoryDB:
    """Migration-only SQLite history store.

    Never modifies external JSON files. Imports legacy data into
    quarantine tables on first run.
    """

    def __init__(
        self,
        db_path: Path,
        legacy_history_path: Optional[Path] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        if legacy_history_path and Path(legacy_history_path).exists():
            self.import_legacy_json(Path(legacy_history_path))

    def _init_schema(self) -> None:
        statements = [
            # Schema migrations
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """,
            # Current scan runs
            """
            CREATE TABLE IF NOT EXISTS scan_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                search_plan_json TEXT NOT NULL DEFAULT '[]',
                raw_observation_count INTEGER NOT NULL DEFAULT 0,
                eligible_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'COMPLETE'
            )
            """,
            # Legacy compatibility table
            """
            CREATE TABLE IF NOT EXISTS search_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                raw_observation_count INTEGER DEFAULT 0,
                eligible_count INTEGER DEFAULT 0
            )
            """,
            # Core fare observations with cabin/FX isolation
            """
            CREATE TABLE IF NOT EXISTS fare_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                itinerary_fingerprint TEXT NOT NULL,
                offer_fingerprint TEXT NOT NULL,
                bucket TEXT NOT NULL,
                cabin_class TEXT NOT NULL,
                native_amount REAL NOT NULL,
                native_currency TEXT NOT NULL,
                fx_rate_to_gbp REAL NOT NULL,
                airfare_gbp REAL NOT NULL,
                baggage_normalized_gbp REAL NOT NULL,
                d2d_cash_gbp REAL NOT NULL,
                business_premium_gbp REAL,
                business_to_economy_ratio REAL,
                upgrade_cost_per_business_hour REAL,
                available INTEGER NOT NULL DEFAULT 1,
                source_observed_at TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                UNIQUE(run_id, offer_fingerprint)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_fare_history
            ON fare_observations(itinerary_fingerprint, cabin_class, recorded_at)
            """,
            # Availability state tracking
            """
            CREATE TABLE IF NOT EXISTS offer_availability_state (
                offer_fingerprint TEXT PRIMARY KEY,
                itinerary_fingerprint TEXT NOT NULL,
                bucket TEXT NOT NULL,
                cabin_class TEXT NOT NULL,
                is_available INTEGER NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_run_id TEXT NOT NULL
            )
            """,
            # Availability events (appeared/disappeared)
            """
            CREATE TABLE IF NOT EXISTS availability_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                offer_fingerprint TEXT NOT NULL,
                run_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                observed_at TEXT NOT NULL
            )
            """,
            # Alert state
            """
            CREATE TABLE IF NOT EXISTS alert_state (
                offer_fingerprint TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 0,
                last_value REAL,
                last_emitted_at TEXT,
                PRIMARY KEY(offer_fingerprint, alert_type)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                offer_fingerprint TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                value REAL,
                threshold REAL,
                emitted_at TEXT NOT NULL
            )
            """,
            # Assumptions table
            """
            CREATE TABLE IF NOT EXISTS assumptions (
                assumption_key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                source TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                confidence TEXT NOT NULL
            )
            """,
            # Legacy import tracking
            """
            CREATE TABLE IF NOT EXISTS legacy_history_imports (
                source_sha256 TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                row_count INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS legacy_fare_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_sha256 TEXT NOT NULL,
                legacy_fingerprint TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                fare_gbp REAL NOT NULL,
                UNIQUE(source_sha256, legacy_fingerprint, observed_at, fare_gbp)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS legacy_fare_observations_raw (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_sha256 TEXT NOT NULL,
                legacy_fingerprint TEXT NOT NULL,
                point_index INTEGER NOT NULL,
                observed_at TEXT NOT NULL,
                fare_gbp REAL NOT NULL,
                UNIQUE(source_sha256, legacy_fingerprint, point_index)
            )
            """,
        ]

        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, now),
            )

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def import_legacy_json(self, source_path: Path) -> int:
        """Copy legacy JSON observations into quarantine tables.

        Never alters the source file. Returns number of rows imported.
        """
        source_bytes = source_path.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()

        with self.get_connection() as conn:
            prior = conn.execute(
                "SELECT row_count FROM legacy_history_imports WHERE source_sha256=?", (source_hash,)
            ).fetchone()
            if prior:
                raw_count = conn.execute(
                    "SELECT COUNT(*) FROM legacy_fare_observations_raw WHERE source_sha256=?",
                    (source_hash,),
                ).fetchone()[0]
                if raw_count == int(prior["row_count"]):
                    return int(prior["row_count"])

        payload = json.loads(source_bytes.decode("utf-8"))
        observations = payload.get("observations") if isinstance(payload, dict) else None
        if not isinstance(observations, dict):
            raise ValueError("Legacy history does not contain an observations mapping")

        rows: List[Tuple[str, int, str, float]] = []
        for fingerprint, points in observations.items():
            if not isinstance(points, list):
                continue
            for point_index, point in enumerate(points):
                if not isinstance(point, dict) or "timestamp" not in point or "fare" not in point:
                    continue
                rows.append((str(fingerprint), point_index, str(point["timestamp"]), float(point["fare"])))

        with self.get_connection() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO legacy_fare_observations(
                    source_sha256, legacy_fingerprint, observed_at, fare_gbp
                ) VALUES (?, ?, ?, ?)
                """,
                [(source_hash, fingerprint, timestamp, fare) for fingerprint, _, timestamp, fare in rows],
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO legacy_fare_observations_raw(
                    source_sha256, legacy_fingerprint, point_index, observed_at, fare_gbp
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (source_hash, fingerprint, point_index, timestamp, fare)
                    for fingerprint, point_index, timestamp, fare in rows
                ],
            )
            conn.execute(
                """
                INSERT INTO legacy_history_imports(source_sha256, source_path, imported_at, row_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_sha256) DO UPDATE SET
                    source_path=excluded.source_path,
                    imported_at=excluded.imported_at,
                    row_count=excluded.row_count
                """,
                (source_hash, str(source_path), datetime.now(timezone.utc).isoformat(), len(rows)),
            )
        return len(rows)

    def record_scan(
        self,
        run_id: str,
        snapshot: Mapping[str, Sequence[Dict[str, Any]]],
        search_plan: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Record a complete scan snapshot with all observations."""
        now = datetime.now(timezone.utc).isoformat()
        plan_json = "[]"
        if search_plan:
            plan_json = json.dumps(search_plan, sort_keys=True)

        all_options = [opt for opts in snapshot.values() for opt in opts]
        scanned_buckets = tuple(snapshot.keys())

        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO scan_runs(run_id, started_at, completed_at, search_plan_json,
                    raw_observation_count, eligible_count, status)
                VALUES (?, ?, ?, ?, ?, ?, 'COMPLETE')
                """,
                (run_id, now, now, plan_json, len(all_options),
                 sum(1 for opt in all_options if opt.get("is_eligible_deal", True))),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO search_runs(run_id, started_at, completed_at,
                    raw_observation_count, eligible_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, now, now, len(all_options),
                 sum(1 for opt in all_options if opt.get("is_eligible_deal", True))),
            )

            # Build current availability state
            current = {str(opt.get("offer_fingerprint", "")): opt for opt in all_options if opt.get("offer_fingerprint")}

            # Find previously seen offers that disappeared
            if scanned_buckets:
                placeholders = ",".join("?" for _ in scanned_buckets)
                known = conn.execute(
                    f"SELECT * FROM offer_availability_state WHERE bucket IN ({placeholders})",
                    scanned_buckets,
                ).fetchall()
            else:
                known = []

            for state in known:
                fingerprint = state["offer_fingerprint"]
                if state["is_available"] and fingerprint not in current:
                    conn.execute(
                        "INSERT INTO availability_events(offer_fingerprint, run_id, event_type, observed_at) VALUES (?, ?, 'DISAPPEARED', ?)",
                        (fingerprint, run_id, now),
                    )
                    conn.execute(
                        "UPDATE offer_availability_state SET is_available=0, last_run_id=? WHERE offer_fingerprint=?",
                        (run_id, fingerprint),
                    )

            # Update availability state for current offers
            for fingerprint, opt in current.items():
                state = conn.execute(
                    "SELECT * FROM offer_availability_state WHERE offer_fingerprint=?", (fingerprint,)
                ).fetchone()
                event_type = "FIRST_SEEN" if state is None else ("REAPPEARED" if not state["is_available"] else None)
                if event_type:
                    conn.execute(
                        "INSERT INTO availability_events(offer_fingerprint, run_id, event_type, observed_at) VALUES (?, ?, ?, ?)",
                        (fingerprint, run_id, event_type, now),
                    )
                conn.execute(
                    """
                    INSERT INTO offer_availability_state(
                        offer_fingerprint, itinerary_fingerprint, bucket, cabin_class,
                        is_available, first_seen_at, last_seen_at, last_run_id
                    ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                    ON CONFLICT(offer_fingerprint) DO UPDATE SET
                        itinerary_fingerprint=excluded.itinerary_fingerprint,
                        bucket=excluded.bucket,
                        cabin_class=excluded.cabin_class,
                        is_available=1,
                        last_seen_at=excluded.last_seen_at,
                        last_run_id=excluded.last_run_id
                    """,
                    (
                        fingerprint,
                        opt.get("itinerary_fingerprint", ""),
                        opt.get("bucket", ""),
                        opt.get("cabin_class", ""),
                        opt.get("first_seen_at", now),
                        now,
                        run_id,
                    ),
                )

    def record_observations(
        self,
        run_id: str,
        observations: Sequence[PriceObservation],
    ) -> None:
        """Record individual price observations."""
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            for obs in observations:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO fare_observations(
                        run_id, itinerary_fingerprint, offer_fingerprint, bucket,
                        cabin_class, native_amount, native_currency, fx_rate_to_gbp,
                        airfare_gbp, baggage_normalized_gbp, d2d_cash_gbp,
                        business_premium_gbp, business_to_economy_ratio,
                        upgrade_cost_per_business_hour, available,
                        source_observed_at, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        obs.run_id,
                        obs.itinerary_fingerprint,
                        obs.offer_fingerprint,
                        obs.bucket,
                        obs.cabin_class,
                        obs.native_amount,
                        obs.native_currency,
                        obs.fx_rate_to_gbp,
                        obs.airfare_gbp,
                        obs.baggage_normalized_gbp,
                        obs.d2d_cash_gbp,
                        obs.business_premium_gbp,
                        obs.business_to_economy_ratio,
                        obs.upgrade_cost_per_business_hour,
                        1 if obs.available else 0,
                        obs.source_observed_at,
                        now,
                    ),
                )

    def get_price_history(
        self,
        itinerary_fingerprint: str,
        cabin_class: str,
        limit: int = 100,
    ) -> List[sqlite3.Row]:
        """Get price history for an itinerary/fingerprint."""
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT * FROM fare_observations
                WHERE itinerary_fingerprint = ? AND cabin_class = ?
                ORDER BY recorded_at DESC
                LIMIT ?
                """,
                (itinerary_fingerprint, cabin_class, limit),
            ).fetchall()

    def get_latest_price(
        self,
        itinerary_fingerprint: str,
        cabin_class: str,
    ) -> Optional[sqlite3.Row]:
        """Get the most recent price observation."""
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT * FROM fare_observations
                WHERE itinerary_fingerprint = ? AND cabin_class = ?
                ORDER BY recorded_at DESC
                LIMIT 1
                """,
                (itinerary_fingerprint, cabin_class),
            ).fetchone()

    def get_historical_extremes(
        self,
        itinerary_fingerprint: str,
        cabin_class: str,
    ) -> Dict[str, Any]:
        """Get historical min/max for trend detection."""
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    MIN(airfare_gbp) as min_fare,
                    MAX(airfare_gbp) as max_fare,
                    MIN(d2d_cash_gbp) as min_d2d,
                    MAX(d2d_cash_gbp) as max_d2d,
                    COUNT(*) as observations
                FROM fare_observations
                WHERE itinerary_fingerprint = ? AND cabin_class = ?
                """,
                (itinerary_fingerprint, cabin_class),
            ).fetchone()
            return dict(row) if row else {}

    def close(self) -> None:
        """No-op for compatibility; connections are per-operation."""
        pass