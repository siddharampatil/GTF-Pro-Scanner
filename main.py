  
import requests

BOT_TOKEN = "8600535028:AAG1DqnJt66Uj034SBhpEfWgUjHFBSrOiwA"
CHAT_ID = "902764304"

def send_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        }
    )

if __name__ == "__main__":
    send_message("✅ GTF Pro Swing Scanner is running from GitHub Actions!")
    print("Message sent successfully.")

