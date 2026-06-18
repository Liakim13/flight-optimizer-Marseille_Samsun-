"""Envoi d'e-mails HTML via SMTP."""

from __future__ import annotations

import logging
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from src.config import Config

logger = logging.getLogger(__name__)


class EmailSender:
    """Envoie le rapport quotidien par e-mail HTML."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def send_report(
        self,
        html_body: str,
        scan_date: Optional[date] = None,
        subject_prefix: str = "✈ Vols MRS-SZF",
    ) -> None:
        """
        Envoie un e-mail HTML au destinataire configuré.

        Raises:
            smtplib.SMTPException: En cas d'échec SMTP.
            ValueError: Si la configuration e-mail est incomplète.
        """
        cfg = self._config
        if not cfg.email_to or not cfg.smtp_user or not cfg.smtp_password:
            raise ValueError("Configuration SMTP incomplète (EMAIL_TO, SMTP_USER, SMTP_PASSWORD).")

        scan_date = scan_date or date.today()
        subject = f"{subject_prefix} — Rapport du {scan_date.strftime('%d/%m/%Y')}"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg.email_from or cfg.smtp_user
        msg["To"] = cfg.email_to

        plain_fallback = (
            f"Rapport vols MRS-SZF du {scan_date.strftime('%d/%m/%Y')}.\n"
            "Ouvrez cet e-mail dans un client compatible HTML pour voir le détail."
        )
        msg.attach(MIMEText(plain_fallback, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            logger.info("Envoi du rapport à %s via %s:%s", cfg.email_to, cfg.smtp_host, cfg.smtp_port)
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(cfg.smtp_user, cfg.smtp_password)
                server.sendmail(msg["From"], [cfg.email_to], msg.as_string())
            logger.info("E-mail envoyé avec succès.")
        except smtplib.SMTPAuthenticationError as exc:
            logger.error("Authentification SMTP échouée : %s", exc)
            raise
        except smtplib.SMTPException as exc:
            logger.error("Erreur SMTP : %s", exc)
            raise
        except OSError as exc:
            logger.error("Erreur réseau lors de l'envoi : %s", exc)
            raise
