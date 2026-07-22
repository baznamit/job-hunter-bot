import os

import requests

_TIMEOUT = 30
_MAX_MESSAGE_LEN = 4096


class TelegramNotifier:

    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

    def send_message(self, message: str) -> None:
        if not self.token or not self.chat_id:
            raise RuntimeError(
                "TELEGRAM_TOKEN and TELEGRAM_CHAT_ID environment variables must be set."
            )

        # Telegram hard limit is 4096 chars; truncate with a notice rather than fail.
        if len(message) > _MAX_MESSAGE_LEN:
            truncated = message[: _MAX_MESSAGE_LEN - 32]
            message = truncated + "\n\n[message truncated]"

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        response = requests.post(
            url,
            json={"chat_id": self.chat_id, "text": message},
            timeout=_TIMEOUT,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Telegram API error {response.status_code}: {response.text}"
            )