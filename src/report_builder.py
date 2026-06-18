"""Génération du rapport HTML pour l'e-mail quotidien."""

from __future__ import annotations

from datetime import date
from html import escape
from typing import Optional

from src.config import Config
from src.models import FlightOffer, ScanResult, StayProfile


def _format_price(price: float, currency: str = "EUR") -> str:
    symbol = "€" if currency == "EUR" else currency
    return f"{price:,.0f} {symbol}".replace(",", " ")


def _format_duration(minutes: int) -> str:
    hours, mins = divmod(max(minutes, 0), 60)
    return f"{hours}h{mins:02d}"


def _render_offer_rows(offers: list[FlightOffer], currency: str) -> str:
    if not offers:
        return (
            '<tr><td colspan="7" style="padding:12px;text-align:center;color:#666;">'
            "Aucune offre valide trouvée pour ce profil.</td></tr>"
        )

    rows: list[str] = []
    for rank, offer in enumerate(offers, start=1):
        offset_label = ""
        if offer.departure_offset != 0:
            sign = "+" if offer.departure_offset > 0 else ""
            offset_label = f" <small>(décalage {sign}{offer.departure_offset}j)</small>"

        rows.append(
            f"""
            <tr>
                <td style="padding:10px;border-bottom:1px solid #e0e0e0;text-align:center;">#{rank}</td>
                <td style="padding:10px;border-bottom:1px solid #e0e0e0;">{escape(offer.outbound_date.strftime('%d/%m/%Y'))}{offset_label}</td>
                <td style="padding:10px;border-bottom:1px solid #e0e0e0;">{escape(offer.return_date.strftime('%d/%m/%Y'))}</td>
                <td style="padding:10px;border-bottom:1px solid #e0e0e0;font-weight:bold;color:#1a73e8;">{_format_price(offer.price_eur, currency)}</td>
                <td style="padding:10px;border-bottom:1px solid #e0e0e0;">{escape(offer.all_airlines)}</td>
                <td style="padding:10px;border-bottom:1px solid #e0e0e0;font-size:13px;">{escape(offer.outbound.departure_time.split(' ')[-1] if ' ' in offer.outbound.departure_time else offer.outbound.departure_time)} → {escape(offer.outbound.arrival_time.split(' ')[-1] if ' ' in offer.outbound.arrival_time else offer.outbound.arrival_time)}<br><small>Retour : {escape(offer.return_leg.departure_time.split(' ')[-1] if ' ' in offer.return_leg.departure_time else offer.return_leg.departure_time)} → {escape(offer.return_leg.arrival_time.split(' ')[-1] if ' ' in offer.return_leg.arrival_time else offer.return_leg.arrival_time)}</small></td>
                <td style="padding:10px;border-bottom:1px solid #e0e0e0;">{_format_duration(offer.total_duration_minutes)}<br><small>A/R incl. escales</small></td>
            </tr>
            """
        )
    return "\n".join(rows)


def _render_opportunities(opportunities: list[dict], currency: str) -> str:
    if not opportunities:
        return """
        <p style="color:#666;margin:0;">Aucune baisse significative détectée par rapport à hier.</p>
        """

    items: list[str] = []
    for opp in opportunities:
        items.append(
            f"""
            <li style="margin-bottom:8px;">
                <strong>{escape(opp['outbound_date'])} → {escape(opp['return_date'])}</strong>
                ({opp['stay_days']} jours, {escape(opp['airlines'])}) :
                <span style="text-decoration:line-through;color:#999;">{_format_price(opp['old_price'], currency)}</span>
                → <strong style="color:#0d904f;">{_format_price(opp['new_price'], currency)}</strong>
                <span style="color:#0d904f;">(−{opp['drop_eur']} € / −{opp['drop_pct']}%)</span>
            </li>
            """
        )

    return f'<ul style="padding-left:20px;margin:0;">{"".join(items)}</ul>'


def build_html_report(
    result: ScanResult,
    config: Config,
    profiles: Optional[list[StayProfile]] = None,
) -> str:
    """
    Construit le corps HTML complet de l'e-mail quotidien.

    Args:
        result: Résultat du scan du jour.
        config: Configuration applicative.
        profiles: Profils de séjour (défaut : config.stay_profiles).

    Returns:
        Chaîne HTML prête à envoyer.
    """
    profiles = profiles or config.stay_profiles
    scan_date_str = result.scan_date.strftime("%d/%m/%Y")
    route = f"{config.departure_airport} ↔ {config.arrival_airport} (via {', '.join(config.hub_airports)})"

    profile_sections: list[str] = []
    for profile in profiles:
        offers = result.offers_by_profile.get(profile.days, [])
        section = f"""
        <h2 style="color:#333;font-size:18px;margin:24px 0 12px;border-bottom:2px solid #1a73e8;padding-bottom:6px;">
            Profil {escape(profile.name)}
        </h2>
        <table style="width:100%;border-collapse:collapse;font-size:14px;background:#fff;">
            <thead>
                <tr style="background:#f5f7fa;">
                    <th style="padding:10px;text-align:left;border-bottom:2px solid #ddd;">#</th>
                    <th style="padding:10px;text-align:left;border-bottom:2px solid #ddd;">Date Aller</th>
                    <th style="padding:10px;text-align:left;border-bottom:2px solid #ddd;">Date Retour</th>
                    <th style="padding:10px;text-align:left;border-bottom:2px solid #ddd;">Prix Total</th>
                    <th style="padding:10px;text-align:left;border-bottom:2px solid #ddd;">Compagnies</th>
                    <th style="padding:10px;text-align:left;border-bottom:2px solid #ddd;">Horaires</th>
                    <th style="padding:10px;text-align:left;border-bottom:2px solid #ddd;">Durée</th>
                </tr>
            </thead>
            <tbody>
                {_render_offer_rows(offers, config.currency)}
            </tbody>
        </table>
        """
        profile_sections.append(section)

    errors_block = ""
    if result.errors:
        error_items = "".join(f"<li>{escape(e)}</li>" for e in result.errors[:5])
        errors_block = f"""
        <div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:12px;margin-top:20px;">
            <strong>Avertissements ({len(result.errors)}) :</strong>
            <ul style="margin:8px 0 0;padding-left:20px;">{error_items}</ul>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rapport Vols MRS-SZF — {scan_date_str}</title>
</head>
<body style="font-family:'Segoe UI',Arial,sans-serif;background:#f0f2f5;margin:0;padding:20px;color:#333;">
    <div style="max-width:900px;margin:0 auto;background:#fff;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,0.08);padding:28px;">
        <h1 style="margin:0 0 8px;color:#1a73e8;font-size:24px;">
            ✈ Rapport quotidien — {escape(route)}
        </h1>
        <p style="margin:0 0 20px;color:#666;font-size:14px;">
            Scan du <strong>{scan_date_str}</strong> · Fenêtre : {config.scan_months} mois ·
            Compagnies : Turkish Airlines &amp; Pegasus · {result.total_api_calls} requêtes API
        </p>

        <div style="background:#e8f5e9;border-left:4px solid #0d904f;border-radius:4px;padding:16px;margin-bottom:24px;">
            <h2 style="margin:0 0 10px;font-size:16px;color:#0d904f;">Opportunité du jour</h2>
            {_render_opportunities(result.opportunities, config.currency)}
        </div>

        {''.join(profile_sections)}

        {errors_block}

        <p style="margin-top:28px;font-size:12px;color:#999;border-top:1px solid #eee;padding-top:16px;">
            Rapport généré automatiquement · Escales Istanbul filtrées ({config.min_layover_minutes}–{config.max_layover_minutes} min) ·
            Optimisation dates ±{config.date_offset_days} jours
        </p>
    </div>
</body>
</html>"""
    return html
