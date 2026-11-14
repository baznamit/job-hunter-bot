import os

import requests

_TIMEOUT = 30
MAX_MESSAGE_LEN = 4096
_MAX_MESSAGE_LEN = MAX_MESSAGE_LEN


def message_length(message: str) -> int:
    """Measure Telegram text conservatively in UTF-16 code units."""
    return len(message.encode("utf-16-le")) // 2


class TelegramNotifier:

    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

    def send_message(self, message: str) -> None:
        if not self.token or not self.chat_id:
            raise RuntimeError(
                "TELEGRAM_TOKEN and TELEGRAM_CHAT_ID environment variables must be set."
            )

        if message_length(message) > MAX_MESSAGE_LEN:
            raise ValueError(
                f"Telegram message exceeds {MAX_MESSAGE_LEN} measured characters"
            )

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            response = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": message},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Telegram transport failure: {type(exc).__name__}"
            ) from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(
                f"Telegram API HTTP failure: status={response.status_code}"
            )

        try:
            payload = response.json()
        except (AttributeError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "Telegram API returned a malformed response"
            ) from exc

        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError(
                "Telegram API did not acknowledge the message"
            )
