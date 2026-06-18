"""
Point d'entrée — Optimiseur de vols MRS ↔ SZF.

Exécution locale ou GitHub Actions :
    python main.py

Test sans envoi d'e-mail :
    python main.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Config
from src.email_sender import EmailSender
from src.optimizer import FlightOptimizer
from src.report_builder import build_html_report
from src.storage import PriceStorage

_log_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
_log_file = PROJECT_ROOT / "flight_optimizer.log"
try:
    _log_handlers.append(logging.FileHandler(_log_file, encoding="utf-8"))
except OSError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_log_handlers,
)
logger = logging.getLogger("main")


def run_daily_job(config: Config, dry_run: bool = False) -> None:
    """Exécute le scan, génère le rapport et envoie l'e-mail."""
    errors = config.validate()
    if errors:
        for err in errors:
            logger.error("Configuration : %s", err)
        if not dry_run:
            sys.exit(1)

    storage = PriceStorage(config.database_path)
    optimizer = FlightOptimizer(config, storage)

    logger.info("=== Démarrage du job quotidien (%s) ===", date.today().isoformat())

    try:
        result = optimizer.run_scan()
    except Exception as exc:
        logger.exception("Échec critique du scan : %s", exc)
        raise

    html = build_html_report(result, config)

    report_dir = PROJECT_ROOT / "data"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "dernier_rapport.html"
    report_path.write_text(html, encoding="utf-8")

    if dry_run:
        logger.info("Mode dry-run : rapport sauvegardé dans %s", report_path)
        return

    try:
        sender = EmailSender(config)
        sender.send_report(html, scan_date=result.scan_date)
    except Exception as exc:
        logger.exception("Échec de l'envoi e-mail : %s", exc)
        logger.info("Rapport disponible localement : %s", report_path)
        raise

    logger.info("=== Job terminé avec succès ===")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Optimiseur de vols Marseille → Samsun via Istanbul"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan sans envoi d'e-mail (sauvegarde HTML local)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = Config.from_env()
    run_daily_job(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
