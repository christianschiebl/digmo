import json
import logging
import os
from typing import Any, Dict, Optional

import requests


logger = logging.getLogger(__name__)


class BrevoEmailProviderError(Exception):
    """Fehler beim Versand über die Brevo API."""


class BrevoEmailProvider:
    """
    Einfacher Wrapper um die Brevo SMTP API.

    Nutzt:
    - BREVO_API_KEY
    - BREVO_SENDER_EMAIL (optional, sonst DEFAULT_FROM_EMAIL oder Fallback)
    - BREVO_SENDER_NAME (optional)
    """

    def __init__(self) -> None:
        self.api_key = os.environ.get("BREVO_API_KEY")
        self.base_url = os.environ.get("BREVO_BASE_URL", "https://api.brevo.com/v3")
        self.sender_email = os.environ.get(
            "BREVO_SENDER_EMAIL",
            os.environ.get("DEFAULT_FROM_EMAIL", "no-reply@example.com"),
        )
        self.sender_name = os.environ.get("BREVO_SENDER_NAME", "DigifyNow")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _build_headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise BrevoEmailProviderError("BREVO_API_KEY ist nicht gesetzt.")
        return {
            "api-key": self.api_key,
            "Content-Type": "application/json",
            "accept": "application/json",
        }

    def send_email(
        self,
        *,
        to_email: str,
        to_name: Optional[str] = None,
        subject: str = "",
        html_content: Optional[str] = None,
        text_content: Optional[str] = None,
        template_id: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Sendet eine E-Mail über Brevo.

        - Wenn template_id gesetzt ist, wird das Template verwendet.
        - Sonst werden subject + html/text verwendet.
        Gibt eine provider_response_id zurück (z. B. Brevo messageId).
        """
        url = f"{self.base_url}/smtp/email"
        headers = self._build_headers()

        payload: Dict[str, Any] = {
            "sender": {"email": self.sender_email, "name": self.sender_name},
            "to": [{"email": to_email, "name": to_name or to_email}],
        }

        if template_id is not None:
            payload["templateId"] = template_id
            if params:
                payload["params"] = params
        else:
            payload["subject"] = subject
            if html_content:
                payload["htmlContent"] = html_content
            elif text_content:
                payload["textContent"] = text_content
            else:
                payload["textContent"] = ""

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
        except requests.RequestException as exc:  # type: ignore[attr-defined]
            logger.exception("Brevo API Request fehlgeschlagen: %s", exc)
            raise BrevoEmailProviderError(str(exc)) from exc

        if not response.ok:
            logger.error(
                "Brevo API Fehler: status=%s body=%s",
                response.status_code,
                response.text,
            )
            raise BrevoEmailProviderError(
                f"Brevo API Fehler: HTTP {response.status_code}"
            )

        try:
            data = response.json()
        except json.JSONDecodeError:
            logger.warning("Brevo Antwort ist kein JSON: %s", response.text)
            return ""

        # Laut Brevo Doku wird häufig 'messageId' zurückgegeben.
        return str(data.get("messageId", ""))  # type: ignore[no-any-return]



