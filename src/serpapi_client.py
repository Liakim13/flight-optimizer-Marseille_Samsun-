"""Client SerpApi pour l'engine Google Flights."""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Optional

from serpapi import GoogleSearch

from src.config import Config

logger = logging.getLogger(__name__)


class SerpApiError(Exception):
    """Erreur levée lors d'un échec d'appel SerpApi."""


class SerpApiClient:
    """Encapsule les requêtes Google Flights via SerpApi."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def _base_params(self) -> dict[str, Any]:
        return {
            "api_key": self._config.serpapi_api_key,
            "engine": "google_flights",
            "departure_id": self._config.departure_airport,
            "arrival_id": self._config.arrival_airport,
            "currency": self._config.currency,
            "gl": self._config.gl,
            "hl": self._config.hl,
            "type": "1",
            "adults": 1,
            "stops": "3",
            "include_airlines": ",".join(self._config.target_airlines),
            "deep_search": "true",
        }

    def _execute_search(self, params: dict[str, Any]) -> dict[str, Any]:
        """Exécute une recherche avec gestion d'erreurs et limitation."""
        if self._call_count >= self._config.max_api_calls_per_run:
            raise SerpApiError(
                f"Limite d'appels API atteinte ({self._config.max_api_calls_per_run})."
            )

        try:
            logger.debug("SerpApi request: %s", {k: v for k, v in params.items() if k != "api_key"})
            results = GoogleSearch(params).get_dict()
            self._call_count += 1
        except Exception as exc:
            logger.exception("Échec de la requête SerpApi")
            raise SerpApiError(f"Requête SerpApi échouée : {exc}") from exc

        if "error" in results:
            raise SerpApiError(f"SerpApi a renvoyé une erreur : {results['error']}")

        time.sleep(self._config.api_delay_seconds)
        return results

    def search_round_trip(
        self,
        outbound_date: date,
        return_date: date,
    ) -> dict[str, Any]:
        """
        Recherche aller-retour MRS <-> SZF.

        Retourne la réponse brute incluant best_flights et other_flights (aller).
        """
        params = self._base_params()
        params["outbound_date"] = outbound_date.isoformat()
        params["return_date"] = return_date.isoformat()
        return self._execute_search(params)

    def fetch_return_leg(self, departure_token: str) -> dict[str, Any]:
        """
        Récupère les vols retour associés à un departure_token.

        Nécessaire pour obtenir le détail complet du retour sur un A/R.
        """
        params = self._base_params()
        params["departure_token"] = departure_token
        params.pop("departure_id", None)
        params.pop("arrival_id", None)
        params.pop("outbound_date", None)
        params.pop("return_date", None)
        return self._execute_search(params)

    def collect_flight_options(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """Fusionne best_flights et other_flights en une seule liste."""
        options: list[dict[str, Any]] = []
        for key in ("best_flights", "other_flights"):
            chunk = response.get(key)
            if isinstance(chunk, list):
                options.extend(chunk)
        return options

    @staticmethod
    def extract_return_option(response: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Extrait la meilleure option retour d'une réponse departure_token."""
        options = []
        for key in ("best_flights", "other_flights"):
            chunk = response.get(key)
            if isinstance(chunk, list):
                options.extend(chunk)
        return options[0] if options else None
