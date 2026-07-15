import os
import requests


class TelegramNotifier:

    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

    def send_message(self, message):

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        payload = {
            "chat_id": self.chat_id,
            "text": message
        }

        response = requests.post(url, json=payload)

        if response.status_code != 200:
            print("Telegram Error")
            print(response.text)