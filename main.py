import requests

import os
BOT_TOKEN = os.environ["8600535028:AAG1DqnJt66Uj034SBhpEfWgUjHFBSrOiwA"]
CHAT_ID = "902764304"

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