from notifier import TelegramNotifier


def main():
    notifier = TelegramNotifier()

    notifier.send_message(
        "🚀 Job Hunter Bot Started Successfully!\n\nGitHub Actions is connected."
    )

    print("Notification sent.")


if __name__ == "__main__":
    main()