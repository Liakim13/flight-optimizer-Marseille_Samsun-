"""Moteur d'optimisation des dates et scan des prix."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta
from typing import Optional

from src.config import Config
from src.flight_filter import FlightFilter
from src.models import FlightOffer, ScanResult, StayProfile
from src.serpapi_client import SerpApiClient, SerpApiError
from src.storage import PriceStorage

logger = logging.getLogger(__name__)


class FlightOptimizer:
    """
    Scanne une fenêtre glissante de 3 mois et optimise les combinaisons
    de dates avec un décalage configurable (+/- N jours).

    Optimisations SerpApi (SCAN_STEP_DAYS=7 par défaut) :
    - Une date de référence tous les 7 jours (~13 ancres sur 3 mois)
    - 1 seule option analysée par recherche (meilleur vol)
    - Pré-validation de l'aller avant l'appel retour
    - Cache SQLite 7 jours (réponses identiques = 0 appel)
    """

    def __init__(self, config: Config, storage: PriceStorage) -> None:
        self._config = config
        self._storage = storage
        self._client = SerpApiClient(config)
        self._filter = FlightFilter(config)
        self._cache_hits = 0
        self._cache_misses = 0

    def _generate_anchor_dates(self, start: date) -> list[date]:
        """
        Génère les dates de départ de référence sur la fenêtre de scan.

        SCAN_STEP_DAYS=7 → ~1 ancre par semaine au lieu de 1 par jour,
        soit ~7× moins de requêtes SerpApi.
        """
        end = start + timedelta(days=self._config.scan_months * 30)
        anchors: list[date] = []
        current = start
        while current <= end:
            anchors.append(current)
            current += timedelta(days=self._config.scan_step_days)
        return anchors

    def _date_offsets(self) -> range:
        """Plage de décalage autour de la date de référence."""
        n = self._config.date_offset_days
        return range(-n, n + 1)

    @staticmethod
    def _search_cache_key(outbound: date, return_date: date) -> str:
        return f"search_{outbound.isoformat()}_{return_date.isoformat()}"

    @staticmethod
    def _return_cache_key(departure_token: str) -> str:
        digest = hashlib.sha256(departure_token.encode()).hexdigest()[:16]
        return f"return_{digest}"

    def _api_budget_remaining(self) -> int:
        return self._config.max_api_calls_per_run - self._client.call_count

    def _get_cached(self, cache_key: str) -> Optional[dict]:
        cached = self._storage.get_cached_response(cache_key, self._config.api_cache_hours)
        if cached:
            self._cache_hits += 1
            return cached
        self._cache_misses += 1
        return None

    def _search_round_trip_cached(self, outbound: date, return_date: date) -> Optional[dict]:
        """Recherche A/R avec cache SQLite pour limiter les appels SerpApi."""
        if self._api_budget_remaining() <= 0:
            raise SerpApiError(
                f"Limite d'appels API atteinte ({self._config.max_api_calls_per_run})."
            )

        key = self._search_cache_key(outbound, return_date)
        cached = self._get_cached(key)
        if cached:
            logger.debug("Cache hit recherche %s", key)
            return cached

        try:
            response = self._client.search_round_trip(outbound, return_date)
            self._storage.set_cached_response(key, response)
            return response
        except SerpApiError as exc:
            logger.warning("Recherche échouée %s -> %s : %s", outbound, return_date, exc)
            return None

    def _fetch_return_option(self, outbound_raw: dict) -> Optional[dict]:
        """Récupère l'option retour via departure_token (avec cache)."""
        if self._api_budget_remaining() <= 0:
            raise SerpApiError(
                f"Limite d'appels API atteinte ({self._config.max_api_calls_per_run})."
            )

        token = outbound_raw.get("departure_token")
        if not token:
            return None

        key = self._return_cache_key(token)
        cached = self._get_cached(key)
        if cached:
            logger.debug("Cache hit retour %s", key)
            return cached

        try:
            ret_response = self._client.fetch_return_leg(token)
            option = self._client.extract_return_option(ret_response)
            if option:
                self._storage.set_cached_response(key, option)
            return option
        except SerpApiError as exc:
            logger.debug("Impossible de récupérer le retour : %s", exc)
            return None

    def _build_offer(
        self,
        outbound_raw: dict,
        return_raw: Optional[dict],
        outbound_date: date,
        return_date: date,
        stay_days: int,
        offset: int,
    ) -> Optional[FlightOffer]:
        """Construit une FlightOffer validée à partir des réponses brutes."""
        outbound_leg = self._filter.parse_outbound(outbound_raw)
        valid_out, reason_out = self._filter.is_valid_outbound_leg(outbound_leg)
        if not valid_out:
            logger.debug("Aller rejeté (%s -> %s) : %s", outbound_date, return_date, reason_out)
            return None

        if return_raw is None:
            return_raw = self._fetch_return_option(outbound_raw)
        if return_raw is None:
            return None

        price = self._filter.extract_price(return_raw) or self._filter.extract_price(outbound_raw)
        if price is None:
            return None

        return_leg = self._filter.parse_return(return_raw)
        valid, reason = self._filter.is_valid_offer(outbound_leg, return_leg)
        if not valid:
            logger.debug("Offre rejetée (%s -> %s) : %s", outbound_date, return_date, reason)
            return None

        offer = FlightOffer(
            outbound_date=outbound_date,
            return_date=return_date,
            stay_days=stay_days,
            price_eur=price,
            outbound=outbound_leg,
            return_leg=return_leg,
            departure_offset=offset,
        )
        offer.score = self._filter.compute_score(offer)
        return offer

    def _find_best_for_combo(
        self,
        anchor: date,
        profile: StayProfile,
    ) -> list[FlightOffer]:
        """
        Pour une date de référence et un profil, teste les décalages ±N jours.

        Ne retient que la meilleure option SerpApi par recherche (MAX_OPTIONS_PER_SEARCH=1).
        """
        offers: list[FlightOffer] = []
        max_options = max(1, self._config.max_options_per_search)

        for offset in self._date_offsets():
            outbound_date = anchor + timedelta(days=offset)
            return_date = outbound_date + timedelta(days=profile.days)

            if outbound_date < date.today():
                continue

            response = self._search_round_trip_cached(outbound_date, return_date)
            if not response:
                continue

            options = self._client.collect_flight_options(response)
            if not options:
                continue

            for option in options[:max_options]:
                offer = self._build_offer(
                    option, None, outbound_date, return_date, profile.days, offset
                )
                if offer:
                    offers.append(offer)
                    break

        offers.sort(key=lambda o: (o.score, o.price_eur))
        return offers

    def _detect_opportunities(self, scan_date: date, offers: list[FlightOffer]) -> list[dict]:
        """Détecte les baisses de prix significatives vs la veille."""
        opportunities: list[dict] = []
        cfg = self._config

        for offer in offers:
            yesterday_price = self._storage.get_yesterday_price(offer.route_key, scan_date)
            if yesterday_price is None:
                continue

            drop_eur = yesterday_price - offer.price_eur
            drop_pct = (drop_eur / yesterday_price) * 100 if yesterday_price > 0 else 0

            if drop_eur >= cfg.price_drop_threshold_eur or drop_pct >= cfg.price_drop_threshold_percent:
                opportunities.append(
                    {
                        "route_key": offer.route_key,
                        "outbound_date": offer.outbound_date.isoformat(),
                        "return_date": offer.return_date.isoformat(),
                        "stay_days": offer.stay_days,
                        "old_price": yesterday_price,
                        "new_price": offer.price_eur,
                        "drop_eur": round(drop_eur, 2),
                        "drop_pct": round(drop_pct, 1),
                        "airlines": offer.all_airlines,
                    }
                )

        return opportunities

    def run_scan(self, scan_date: Optional[date] = None) -> ScanResult:
        """
        Lance le scan complet sur la fenêtre configurée.

        Returns:
            ScanResult avec les 3 meilleures offres par profil de séjour.
        """
        scan_date = scan_date or date.today()
        cfg = self._config
        anchors = self._generate_anchor_dates(scan_date)
        offers_by_profile: dict[int, list[FlightOffer]] = {p.days: [] for p in cfg.stay_profiles}
        all_valid_offers: list[FlightOffer] = []
        errors: list[str] = []
        api_limit_hit = False

        estimated = cfg.estimate_max_api_calls()
        logger.info(
            "Scan optimisé — step=%dj, %d ancres, %d combinaisons, "
            "budget max=%d appels (estimation sans cache=%d), cache=%dh",
            cfg.scan_step_days,
            len(anchors),
            cfg.count_date_combinations(),
            cfg.max_api_calls_per_run,
            estimated,
            cfg.api_cache_hours,
        )
        logger.info(
            "Entrées cache existantes : %d (les combinaisons déjà vues ne consomment pas SerpApi)",
            self._storage.count_cache_entries(),
        )

        for anchor in anchors:
            if api_limit_hit:
                break
            for profile in cfg.stay_profiles:
                try:
                    combo_offers = self._find_best_for_combo(anchor, profile)
                    if combo_offers:
                        best = combo_offers[0]
                        offers_by_profile[profile.days].append(best)
                        all_valid_offers.append(best)

                        self._storage.save_offer(
                            scan_date,
                            best,
                            self._filter.format_leg_summary(best.outbound),
                            self._filter.format_leg_summary(best.return_leg),
                        )
                except SerpApiError as exc:
                    msg = f"Limite API atteinte ({anchor} / profil {profile.days}j) : {exc}"
                    logger.warning(msg)
                    errors.append(msg)
                    api_limit_hit = True
                    break
                except Exception as exc:
                    msg = f"Erreur inattendue {anchor} / {profile.days}j : {exc}"
                    logger.exception(msg)
                    errors.append(msg)

        for stay_days in offers_by_profile:
            offers_by_profile[stay_days].sort(key=lambda o: (o.score, o.price_eur))
            offers_by_profile[stay_days] = offers_by_profile[stay_days][:3]

        opportunities = self._detect_opportunities(scan_date, all_valid_offers)

        result = ScanResult(
            scan_date=scan_date,
            offers_by_profile=offers_by_profile,
            total_api_calls=self._client.call_count,
            errors=errors,
            opportunities=opportunities,
        )

        self._storage.log_scan_run(
            scan_date,
            total_offers=len(all_valid_offers),
            api_calls=self._client.call_count,
            errors=errors,
        )

        logger.info(
            "Scan terminé — appels SerpApi=%d, cache hits=%d, misses=%d, opportunités=%d",
            result.total_api_calls,
            self._cache_hits,
            self._cache_misses,
            len(result.opportunities),
        )
        return result

    @staticmethod
    def get_top_offers_by_profile(result: ScanResult, top_n: int = 3) -> dict[int, list[FlightOffer]]:
        """Retourne les N meilleures offres par profil depuis un ScanResult."""
        return {
            stay_days: offers[:top_n]
            for stay_days, offers in result.offers_by_profile.items()
        }
