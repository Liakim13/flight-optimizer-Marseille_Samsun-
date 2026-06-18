"""Modèles de données pour l'optimiseur de vols."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class FlightSegment:
    """Un segment de vol individuel."""

    departure_airport: str
    arrival_airport: str
    departure_time: str
    arrival_time: str
    duration_minutes: int
    airline: str
    flight_number: str = ""


@dataclass(frozen=True)
class Layover:
    """Escale entre deux segments."""

    airport_code: str
    airport_name: str
    duration_minutes: int
    overnight: bool = False


@dataclass
class FlightLeg:
    """Aller ou retour avec segments et escales."""

    segments: list[FlightSegment] = field(default_factory=list)
    layovers: list[Layover] = field(default_factory=list)
    total_duration_minutes: int = 0

    @property
    def airlines(self) -> list[str]:
        """Liste unique des compagnies sur ce tronçon."""
        seen: set[str] = set()
        result: list[str] = []
        for seg in self.segments:
            if seg.airline not in seen:
                seen.add(seg.airline)
                result.append(seg.airline)
        return result

    @property
    def departure_time(self) -> str:
        return self.segments[0].departure_time if self.segments else "N/A"

    @property
    def arrival_time(self) -> str:
        return self.segments[-1].arrival_time if self.segments else "N/A"


@dataclass
class FlightOffer:
    """Offre aller-retour complète."""

    outbound_date: date
    return_date: date
    stay_days: int
    price_eur: float
    outbound: FlightLeg
    return_leg: FlightLeg
    departure_offset: int = 0
    score: float = 0.0
    penalty_reason: str = ""

    @property
    def total_duration_minutes(self) -> int:
        return self.outbound.total_duration_minutes + self.return_leg.total_duration_minutes

    @property
    def all_airlines(self) -> str:
        airlines = self.outbound.airlines + [
            a for a in self.return_leg.airlines if a not in self.outbound.airlines
        ]
        return " + ".join(airlines)

    @property
    def route_key(self) -> str:
        """Clé unique pour le suivi historique des prix."""
        return f"{self.outbound_date.isoformat()}_{self.return_date.isoformat()}_{self.stay_days}"


@dataclass
class StayProfile:
    """Profil de durée de séjour."""

    name: str
    days: int


@dataclass
class ScanResult:
    """Résultat agrégé d'un scan complet."""

    scan_date: date
    offers_by_profile: dict[int, list[FlightOffer]]
    total_api_calls: int
    errors: list[str] = field(default_factory=list)
    opportunities: list[dict] = field(default_factory=list)
