"""Configuration centralisée via variables d'environnement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from src.models import StayProfile

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _parse_int_list(value: str, default: list[int]) -> list[int]:
    if not value.strip():
        return default
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def _parse_str_list(value: str, default: list[str]) -> list[str]:
    if not value.strip():
        return default
    return [x.strip().upper() for x in value.split(",") if x.strip()]


@dataclass(frozen=True)
class Config:
    """Paramètres applicatifs chargés depuis .env."""

    serpapi_api_key: str
    departure_airport: str
    arrival_airport: str
    hub_airports: list[str]
    target_airlines: list[str]
    scan_months: int
    scan_step_days: int
    date_offset_days: int
    stay_profiles: list[StayProfile]
    min_layover_minutes: int
    max_layover_minutes: int
    api_delay_seconds: float
    max_api_calls_per_run: int
    max_options_per_search: int
    api_cache_hours: int
    price_drop_threshold_percent: float
    price_drop_threshold_eur: float
    currency: str
    gl: str
    hl: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_from: str
    email_to: str
    database_path: Path

    @classmethod
    def from_env(cls) -> "Config":
        """Charge et valide la configuration depuis l'environnement."""
        stay_days = _parse_int_list(os.getenv("STAY_PROFILES_DAYS", "14,21,28"), [14, 21, 28])
        profiles = [
            StayProfile(name=f"{d // 7} semaines ({d} j)", days=d) for d in stay_days
        ]

        db_path = os.getenv("DATABASE_PATH", "data/prices.db")
        if not Path(db_path).is_absolute():
            db_path = str(PROJECT_ROOT / db_path)

        return cls(
            serpapi_api_key=os.getenv("SERPAPI_API_KEY", ""),
            departure_airport=os.getenv("DEPARTURE_AIRPORT", "MRS").upper(),
            arrival_airport=os.getenv("ARRIVAL_AIRPORT", "SZF").upper(),
            hub_airports=_parse_str_list(os.getenv("HUB_AIRPORTS", "IST,SAW"), ["IST", "SAW"]),
            target_airlines=_parse_str_list(os.getenv("TARGET_AIRLINES", "TK,PC"), ["TK", "PC"]),
            scan_months=int(os.getenv("SCAN_MONTHS", "3")),
            scan_step_days=int(os.getenv("SCAN_STEP_DAYS", "7")),
            date_offset_days=int(os.getenv("DATE_OFFSET_DAYS", "2")),
            stay_profiles=profiles,
            min_layover_minutes=int(os.getenv("MIN_LAYOVER_MINUTES", "45")),
            max_layover_minutes=int(os.getenv("MAX_LAYOVER_MINUTES", "360")),
            api_delay_seconds=float(os.getenv("API_DELAY_SECONDS", "1.5")),
            max_api_calls_per_run=int(os.getenv("MAX_API_CALLS_PER_RUN", "200")),
            max_options_per_search=int(os.getenv("MAX_OPTIONS_PER_SEARCH", "1")),
            api_cache_hours=int(os.getenv("API_CACHE_HOURS", "168")),
            price_drop_threshold_percent=float(os.getenv("PRICE_DROP_THRESHOLD_PERCENT", "5")),
            price_drop_threshold_eur=float(os.getenv("PRICE_DROP_THRESHOLD_EUR", "30")),
            currency=os.getenv("CURRENCY", "EUR").upper(),
            gl=os.getenv("GL", "fr").lower(),
            hl=os.getenv("HL", "fr").lower(),
            smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            email_from=os.getenv("EMAIL_FROM", "") or os.getenv("SMTP_USER", ""),
            email_to=os.getenv("EMAIL_TO", ""),
            database_path=Path(db_path),
        )

    def validate(self) -> list[str]:
        """Retourne la liste des erreurs de configuration."""
        errors: list[str] = []
        if not self.serpapi_api_key:
            errors.append("SERPAPI_API_KEY est obligatoire.")
        if not self.smtp_user or not self.smtp_password:
            errors.append("SMTP_USER et SMTP_PASSWORD sont obligatoires pour l'envoi d'e-mails.")
        if not self.email_to:
            errors.append("EMAIL_TO est obligatoire.")
        if self.scan_step_days < 1:
            errors.append("SCAN_STEP_DAYS doit être >= 1.")
        return errors

    def count_anchor_dates(self, from_date: "date | None" = None) -> int:
        """Nombre de dates de référence sur la fenêtre de scan."""
        from datetime import date as date_cls, timedelta

        start = from_date or date_cls.today()
        end = start + timedelta(days=self.scan_months * 30)
        count = 0
        current = start
        while current <= end:
            count += 1
            current += timedelta(days=self.scan_step_days)
        return count

    def count_date_combinations(self) -> int:
        """
        Nombre total de couples (date aller, profil, décalage) à évaluer.

        Avec SCAN_STEP_DAYS=7, ~13 ancres × 3 profils × 5 décalages ≈ 195 combinaisons.
        """
        offsets = 2 * self.date_offset_days + 1
        return self.count_anchor_dates() * len(self.stay_profiles) * offsets

    def estimate_max_api_calls(self) -> int:
        """
        Estimation pessimiste d'appels SerpApi (sans cache).

        Chaque combinaison = 1 recherche A/R + 1 récupération retour max.
        """
        return self.count_date_combinations() * (1 + self.max_options_per_search)
