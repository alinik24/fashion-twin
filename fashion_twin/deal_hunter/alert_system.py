"""Alert and notification system for deals.

Supports multiple notification channels:
- Discord webhooks
- Telegram bot
- Email
- Console logging
"""

import logging
from datetime import datetime
from typing import Optional

import requests

from config import get_settings
from .deal_scorer import DealScore

logger = logging.getLogger(__name__)


class AlertSystem:
    """
    Multi-channel notification system for deal alerts.

    Supports:
    - Discord webhooks
    - Telegram bot messages
    - Email (via SMTP)
    - Console logging
    """

    def __init__(self):
        self.cfg = get_settings()

    def send_deal_alert(
        self,
        item_id: str,
        deal_score: DealScore,
        item_data: dict,
        channels: Optional[list[str]] = None,
    ):
        """
        Send deal alert to configured channels.

        Args:
            item_id: Item identifier
            deal_score: DealScore object
            item_data: Full item data (title, url, price, etc.)
            channels: List of channels to use (discord, telegram, email, console)
                     If None, uses all configured channels
        """
        if channels is None:
            channels = self._get_enabled_channels()

        message = self._format_message(item_id, deal_score, item_data)

        for channel in channels:
            try:
                if channel == "discord":
                    self._send_discord(message, item_data)
                elif channel == "telegram":
                    self._send_telegram(message)
                elif channel == "email":
                    self._send_email(message, item_data)
                elif channel == "console":
                    self._send_console(message)
                else:
                    logger.warning("Unknown notification channel: %s", channel)
            except Exception as e:
                logger.error("Failed to send alert via %s: %s", channel, e)

    def _get_enabled_channels(self) -> list[str]:
        """Determine which notification channels are configured."""
        channels = ["console"]  # Always enabled

        if self.cfg.deal_alert_discord_webhook:
            channels.append("discord")

        if self.cfg.deal_alert_telegram_bot_token and self.cfg.deal_alert_telegram_chat_id:
            channels.append("telegram")

        if self.cfg.deal_alert_email:
            channels.append("email")

        return channels

    def _format_message(self, item_id: str, deal_score: DealScore, item_data: dict) -> str:
        """Format alert message text."""
        title = item_data.get("title", "Unknown Item")
        price = item_data.get("price", 0.0)
        currency = item_data.get("currency", "EUR")
        brand = item_data.get("brand", "Unknown")
        condition = item_data.get("condition", "")
        url = item_data.get("url", "")

        message = f"""
🔥 DEAL ALERT - {deal_score.quality.upper()}

**{title}**

💰 Price: {price} {currency}
🏷️ Brand: {brand}
📦 Condition: {condition}

📊 Deal Score: {deal_score.total_score:.1f}/100
• Price: {deal_score.price_score:.1f}
• History: {deal_score.history_score:.1f}
• Condition: {deal_score.condition_score:.1f}
• Urgency: {deal_score.time_score:.1f}

🔗 Link: {url}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """.strip()

        return message

    def _send_discord(self, message: str, item_data: dict):
        """Send notification to Discord via webhook."""
        webhook_url = self.cfg.deal_alert_discord_webhook

        if not webhook_url:
            return

        # Format as Discord embed
        embed = {
            "title": f"🔥 {item_data.get('title', 'Deal Alert')}",
            "description": message,
            "color": self._get_quality_color(item_data.get("deal_quality", "fair")),
            "thumbnail": {"url": item_data.get("image_url", "")},
            "url": item_data.get("url", ""),
            "timestamp": datetime.now().isoformat(),
            "footer": {"text": "Fashion Twin Deal Hunter"},
        }

        payload = {
            "embeds": [embed],
            "username": "Deal Hunter",
        }

        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Discord alert sent for item %s", item_data.get("id"))

    def _send_telegram(self, message: str):
        """Send notification to Telegram."""
        bot_token = self.cfg.deal_alert_telegram_bot_token
        chat_id = self.cfg.deal_alert_telegram_chat_id

        if not bot_token or not chat_id:
            return

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }

        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Telegram alert sent")

    def _send_email(self, message: str, item_data: dict):
        """Send notification via email."""
        # Placeholder - implement with your preferred email service
        # Options: SendGrid, Mailgun, AWS SES, SMTP
        email = self.cfg.deal_alert_email

        if not email:
            return

        # Example using smtplib (requires additional config)
        logger.warning("Email notifications not yet implemented")
        # TODO: Implement email sending
        pass

    def _send_console(self, message: str):
        """Log alert to console."""
        logger.info("DEAL ALERT:\n%s", message)

    def _get_quality_color(self, quality: str) -> int:
        """Get Discord embed color based on deal quality."""
        colors = {
            "excellent": 0x00FF00,  # Green
            "good": 0x00BFFF,       # Blue
            "fair": 0xFFD700,       # Gold
            "poor": 0xFF4500,       # Red
        }
        return colors.get(quality, 0x808080)  # Gray default

    def send_price_drop_alert(self, item_id: str, alert_data: dict, item_data: dict):
        """Send specific alert for price drops."""
        old_price = alert_data["old_price"]
        new_price = alert_data["new_price"]
        drop_pct = alert_data["drop_percentage"]

        title = item_data.get("title", "Unknown Item")
        url = item_data.get("url", "")
        currency = item_data.get("currency", "EUR")

        message = f"""
📉 PRICE DROP ALERT

**{title}**

Was: {old_price} {currency}
Now: {new_price} {currency}
Drop: -{drop_pct:.1f}%

🔗 {url}
        """.strip()

        channels = self._get_enabled_channels()
        for channel in channels:
            try:
                if channel == "discord":
                    embed = {
                        "title": f"📉 Price Drop: {title}",
                        "description": message,
                        "color": 0xFF4500,  # Orange/Red
                        "url": url,
                    }
                    requests.post(
                        self.cfg.deal_alert_discord_webhook,
                        json={"embeds": [embed]},
                        timeout=10,
                    )
                elif channel == "telegram":
                    self._send_telegram(message)
                elif channel == "console":
                    logger.info("PRICE DROP:\n%s", message)
            except Exception as e:
                logger.error("Failed to send price drop alert via %s: %s", channel, e)
