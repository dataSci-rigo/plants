import requests

# Replace with your actual Telegram Bot Token from @BotFather
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe"

print("Testing connection to Telegram...")

try:
    response = requests.get(url, timeout=10)
    
    if response.status_code == 200:
        data = response.json()
        bot_info = data.get("result", {})
        print("\n✅ Successfully connected to Telegram!")
        print(f"🤖 Bot Name: {bot_info.get('first_name')}")
        print(f"🔗 Username: @{bot_info.get('username')}")
    elif response.status_code == 401:
        print("\n❌ Unauthorized: Your Telegram Bot Token is invalid.")
    else:
        print(f"\n❌ Error response from Telegram (Status {response.status_code}):")
        print(response.text)

except requests.exceptions.Timeout:
    print("\n❌ Connection timed out. Check your network or firewall rules.")
except requests.exceptions.ConnectionError:
    print("\n❌ Connection error. Could not reach api.telegram.org.")
except Exception as e:
    print(f"\n❌ An unexpected error occurred: {e}")