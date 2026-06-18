"""Persistance SQLite des prix et cache de recherche."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Generator, Optional

from src.models import FlightOffer

logger = logging.getLogger(__name__)


class PriceStorage:
    """Stocke l'historique des prix et un cache de requêtes API."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_date TEXT NOT NULL,
                    route_key TEXT NOT NULL,
                    outbound_date TEXT NOT NULL,
                    return_date TEXT NOT NULL,
                    stay_days INTEGER NOT NULL,
                    price_eur REAL NOT NULL,
                    airlines TEXT,
                    outbound_summary TEXT,
                    return_summary TEXT,
                    total_duration_min INTEGER,
                    created_at TEXT NOT NULL,
                    UNIQUE(scan_date, route_key)
                );

                CREATE TABLE IF NOT EXISTS api_cache (
                    cache_key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scan_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_date TEXT NOT NULL,
                    total_offers INTEGER,
                    api_calls INTEGER,
                    errors TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_price_route ON price_history(route_key, scan_date);
                """
            )

    def save_offer(self, scan_date: date, offer: FlightOffer, outbound_summary: str, return_summary: str) -> None:
        """Enregistre ou met à jour une offre pour la date de scan."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO price_history (
                    scan_date, route_key, outbound_date, return_date, stay_days,
                    price_eur, airlines, outbound_summary, return_summary,
                    total_duration_min, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scan_date, route_key) DO UPDATE SET
                    price_eur = excluded.price_eur,
                    airlines = excluded.airlines,
                    outbound_summary = excluded.outbound_summary,
                    return_summary = excluded.return_summary,
                    total_duration_min = excluded.total_duration_min,
                    created_at = excluded.created_at
                """,
                (
                    scan_date.isoformat(),
                    offer.route_key,
                    offer.outbound_date.isoformat(),
                    offer.return_date.isoformat(),
                    offer.stay_days,
                    offer.price_eur,
                    offer.all_airlines,
                    outbound_summary,
                    return_summary,
                    offer.total_duration_minutes,
                    now,
                ),
            )

    def get_cached_response(self, cache_key: str, max_age_hours: int = 168) -> Optional[dict]:
        """Retourne une réponse API en cache si encore valide."""
        cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT response_json FROM api_cache WHERE cache_key = ? AND created_at >= ?",
                (cache_key, cutoff),
            ).fetchone()
        if row:
            try:
                return json.loads(row["response_json"])
            except json.JSONDecodeError:
                logger.warning("Cache corrompu pour %s", cache_key)
        return None

    def set_cached_response(self, cache_key: str, response: dict) -> None:
        """Met en cache une réponse API."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_cache (cache_key, response_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    response_json = excluded.response_json,
                    created_at = excluded.created_at
                """,
                (cache_key, json.dumps(response), now),
            )

    def get_yesterday_price(self, route_key: str, today: date) -> Optional[float]:
        """Récupère le prix enregistré la veille pour une route donnée."""
        yesterday = (today - timedelta(days=1)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT price_eur FROM price_history
                WHERE route_key = ? AND scan_date = ?
                ORDER BY price_eur ASC LIMIT 1
                """,
                (route_key, yesterday),
            ).fetchone()
        return float(row["price_eur"]) if row else None

    def get_best_offers_for_scan(self, scan_date: date, stay_days: int, limit: int = 3) -> list[sqlite3.Row]:
        """Retourne les N meilleures offres pour un profil et une date de scan."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM price_history
                WHERE scan_date = ? AND stay_days = ?
                ORDER BY price_eur ASC
                LIMIT ?
                """,
                (scan_date.isoformat(), stay_days, limit),
            ).fetchall()
        return list(rows)

    def count_cache_entries(self) -> int:
        """Nombre d'entrées présentes dans le cache API."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM api_cache").fetchone()
        return int(row["n"]) if row else 0

    def log_scan_run(self, scan_date: date, total_offers: int, api_calls: int, errors: list[str]) -> None:
        """Journalise une exécution de scan."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scan_runs (scan_date, total_offers, api_calls, errors, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    scan_date.isoformat(),
                    total_offers,
                    api_calls,
                    json.dumps(errors, ensure_ascii=False),
                    datetime.utcnow().isoformat(),
                ),
            )
