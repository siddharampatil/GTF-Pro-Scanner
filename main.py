import requests

import os
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

print("Starting Telegram test...")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

response = requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": "✅ GitHub Actions test successful!"
    }
)

print("Status Code:", response.status_code)
print("Response:", response.text)