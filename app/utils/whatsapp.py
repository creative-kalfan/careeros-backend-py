"""WhatsApp notification client for sending alert messages via Twilio or Meta WhatsApp Business API."""

from __future__ import annotations

import logging
from typing import Optional
import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def send_whatsapp_message(to_number: str, text: str) -> bool:
    """Send a WhatsApp message using configured provider (Twilio or Meta).

    to_number should be formatted with country code (e.g. '+919876543210' or 'whatsapp:+919876543210').
    """
    settings = get_settings()
    provider = getattr(settings, "whatsapp_provider", "twilio").lower()

    if not to_number:
        logger.warning("No recipient number provided for WhatsApp message.")
        return False

    # Normalize number prefix
    formatted_to = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"

    if provider == "twilio":
        sid = settings.twilio_account_sid
        token = settings.twilio_auth_token
        from_number = settings.twilio_whatsapp_from

        if not sid or not token:
            logger.info("Twilio WhatsApp credentials not configured; logging message only: %s -> %s", formatted_to, text)
            return True

        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        data = {
            "From": from_number,
            "To": formatted_to,
            "Body": text,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, data=data, auth=(sid, token))
                if resp.status_code in (200, 201):
                    logger.info("Successfully sent Twilio WhatsApp message to %s", formatted_to)
                    return True
                else:
                    logger.warning("Twilio WhatsApp API returned %s: %s", resp.status_code, resp.text)
                    return False
        except Exception as exc:
            logger.exception("Failed to send Twilio WhatsApp message: %s", exc)
            return False

    elif provider == "meta":
        meta_token = settings.meta_whatsapp_token
        phone_id = settings.meta_whatsapp_phone_number_id
        if not meta_token or not phone_id:
            logger.info("Meta WhatsApp credentials not configured; logging message only: %s -> %s", formatted_to, text)
            return True

        clean_number = to_number.replace("whatsapp:", "").replace("+", "").strip()
        url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {meta_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_number,
            "type": "text",
            "text": {"body": text},
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code in (200, 201):
                    logger.info("Successfully sent Meta WhatsApp message to %s", clean_number)
                    return True
                else:
                    logger.warning("Meta WhatsApp API returned %s: %s", resp.status_code, resp.text)
                    return False
        except Exception as exc:
            logger.exception("Failed to send Meta WhatsApp message: %s", exc)
            return False

    return True
