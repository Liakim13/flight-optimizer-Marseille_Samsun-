"""Filtrage et scoring des offres de vol."""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.config import Config
from src.models import FlightLeg, FlightOffer, FlightSegment, Layover

logger = logging.getLogger(__name__)

AIRLINE_CODES = {
    "Turkish Airlines": "TK",
    "Pegasus": "PC",
    "Pegasus Airlines": "PC",
}

ALLOWED_AIRLINE_NAMES = {
    "turkish airlines",
    "pegasus",
    "pegasus airlines",
}


def _parse_leg(raw: dict[str, Any]) -> FlightLeg:
    """Convertit une option SerpApi en FlightLeg."""
    segments: list[FlightSegment] = []
    for flight in raw.get("flights", []):
        dep = flight.get("departure_airport", {})
        arr = flight.get("arrival_airport", {})
        segments.append(
            FlightSegment(
                departure_airport=dep.get("id", ""),
                arrival_airport=arr.get("id", ""),
                departure_time=dep.get("time", ""),
                arrival_time=arr.get("time", ""),
                duration_minutes=int(flight.get("duration", 0)),
                airline=flight.get("airline", "Inconnue"),
                flight_number=flight.get("flight_number", ""),
            )
        )

    layovers: list[Layover] = []
    for lay in raw.get("layovers", []):
        layovers.append(
            Layover(
                airport_code=lay.get("id", ""),
                airport_name=lay.get("name", ""),
                duration_minutes=int(lay.get("duration", 0)),
                overnight=bool(lay.get("overnight", False)),
            )
        )

    return FlightLeg(
        segments=segments,
        layovers=layovers,
        total_duration_minutes=int(raw.get("total_duration", 0)),
    )


def _is_target_airline(airline_name: str, target_codes: list[str]) -> bool:
    """Vérifie si la compagnie correspond à TK ou PC."""
    normalized = airline_name.strip().lower()
    if normalized in ALLOWED_AIRLINE_NAMES:
        return True
    code = AIRLINE_CODES.get(airline_name.strip())
    return code in target_codes if code else False


def _hub_layovers(leg: FlightLeg, hub_airports: list[str]) -> list[Layover]:
    """Retourne les escales situées à Istanbul (IST ou SAW)."""
    hubs = {h.upper() for h in hub_airports}
    return [lo for lo in leg.layovers if lo.airport_code.upper() in hubs]


def _route_touches_hub(leg: FlightLeg, hub_airports: list[str]) -> bool:
    """Vérifie que le tronçon passe par un hub istanbulien."""
    hubs = {h.upper() for h in hub_airports}
    airport_ids = set()
    for seg in leg.segments:
        airport_ids.add(seg.departure_airport.upper())
        airport_ids.add(seg.arrival_airport.upper())
    for lo in leg.layovers:
        airport_ids.add(lo.airport_code.upper())
    return bool(airport_ids & hubs)


def _format_duration(minutes: int) -> str:
    """Formate une durée en heures et minutes."""
    hours, mins = divmod(max(minutes, 0), 60)
    return f"{hours}h{mins:02d}"


class FlightFilter:
    """Applique les critères métier sur les offres brutes SerpApi."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def parse_outbound(self, raw: dict[str, Any]) -> FlightLeg:
        return _parse_leg(raw)

    def parse_return(self, raw: dict[str, Any]) -> FlightLeg:
        return _parse_leg(raw)

    def is_valid_outbound_leg(self, outbound: FlightLeg) -> tuple[bool, str]:
        """
        Pré-validation de l'aller seul — évite un appel API retour inutile.
        """
        cfg = self._config
        if not outbound.segments:
            return False, "Segments aller manquants"

        if outbound.segments[0].departure_airport.upper() != cfg.departure_airport:
            return False, f"Départ aller incorrect ({outbound.segments[0].departure_airport})"

        if outbound.segments[-1].arrival_airport.upper() != cfg.arrival_airport:
            return False, f"Arrivée aller incorrecte ({outbound.segments[-1].arrival_airport})"

        if not _route_touches_hub(outbound, cfg.hub_airports):
            return False, "L'aller ne passe pas par Istanbul (IST/SAW)"

        for seg in outbound.segments:
            if not _is_target_airline(seg.airline, cfg.target_airlines):
                return False, f"Compagnie non autorisée sur l'aller : {seg.airline}"

        for hub_lay in _hub_layovers(outbound, cfg.hub_airports):
            if hub_lay.duration_minutes < cfg.min_layover_minutes:
                return False, f"Escale Istanbul trop courte ({hub_lay.duration_minutes} min)"
            if hub_lay.duration_minutes > cfg.max_layover_minutes:
                return False, f"Escale Istanbul trop longue ({hub_lay.duration_minutes} min)"

        return True, ""

    def is_valid_offer(
        self,
        outbound: FlightLeg,
        return_leg: FlightLeg,
    ) -> tuple[bool, str]:
        """
        Valide qu'une offre respecte l'itinéraire MRS-IST-SZF.

        Returns:
            (valide, raison_du_rejet)
        """
        cfg = self._config

        if not outbound.segments or not return_leg.segments:
            return False, "Segments de vol manquants"

        if outbound.segments[0].departure_airport.upper() != cfg.departure_airport:
            return False, f"Départ aller incorrect ({outbound.segments[0].departure_airport})"

        if outbound.segments[-1].arrival_airport.upper() != cfg.arrival_airport:
            return False, f"Arrivée aller incorrecte ({outbound.segments[-1].arrival_airport})"

        if return_leg.segments[0].departure_airport.upper() != cfg.arrival_airport:
            return False, f"Départ retour incorrect ({return_leg.segments[0].departure_airport})"

        if return_leg.segments[-1].arrival_airport.upper() != cfg.departure_airport:
            return False, f"Arrivée retour incorrecte ({return_leg.segments[-1].arrival_airport})"

        if not _route_touches_hub(outbound, cfg.hub_airports):
            return False, "L'aller ne passe pas par Istanbul (IST/SAW)"

        if not _route_touches_hub(return_leg, cfg.hub_airports):
            return False, "Le retour ne passe pas par Istanbul (IST/SAW)"

        for leg_name, leg in (("aller", outbound), ("retour", return_leg)):
            for seg in leg.segments:
                if not _is_target_airline(seg.airline, cfg.target_airlines):
                    return False, f"Compagnie non autorisée sur {leg_name} : {seg.airline}"

            for hub_lay in _hub_layovers(leg, cfg.hub_airports):
                if hub_lay.duration_minutes < cfg.min_layover_minutes:
                    return (
                        False,
                        f"Escale Istanbul trop courte ({hub_lay.duration_minutes} min)",
                    )
                if hub_lay.duration_minutes > cfg.max_layover_minutes:
                    return (
                        False,
                        f"Escale Istanbul trop longue ({hub_lay.duration_minutes} min)",
                    )

        return True, ""

    def compute_score(self, offer: FlightOffer) -> float:
        """
        Score composite : prix prioritaire, pénalités sur escales.

        Score plus bas = meilleure offre.
        """
        score = float(offer.price_eur)

        for leg in (offer.outbound, offer.return_leg):
            for hub_lay in _hub_layovers(leg, self._config.hub_airports):
                if hub_lay.duration_minutes < 60:
                    score += 25
                elif hub_lay.duration_minutes > 240:
                    score += 15
                if hub_lay.overnight:
                    score += 10

            if leg.total_duration_minutes > 1440:
                score += 20

        return score

    @staticmethod
    def format_leg_summary(leg: FlightLeg) -> str:
        """Résumé lisible d'un tronçon pour le rapport."""
        if not leg.segments:
            return "N/A"

        parts = [
            f"{leg.departure_time} → {leg.arrival_time}",
            f"durée {_format_duration(leg.total_duration_minutes)}",
        ]
        if leg.layovers:
            layover_txt = ", ".join(
                f"{lo.airport_code} ({_format_duration(lo.duration_minutes)})"
                for lo in leg.layovers
            )
            parts.append(f"escales : {layover_txt}")
        return " | ".join(parts)

    @staticmethod
    def extract_price(raw: dict[str, Any]) -> Optional[float]:
        """Extrait le prix d'une option SerpApi."""
        price = raw.get("price")
        if price is None:
            return None
        try:
            return float(price)
        except (TypeError, ValueError):
            return None
