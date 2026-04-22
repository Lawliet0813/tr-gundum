"""
部署完成後執行：把 avatar_v2.png 透過 LINE Push API 送到管理員的 LINE
用法：python scripts/send_avatar.py
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
USER_ID = "Uac772d5246bb985dd40c5914b77af570"
BASE    = "https://tr-gundum-production.up.railway.app"
IMG_URL = f"{BASE}/static/trains/avatar_v2.png"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

payload = {
    "to": USER_ID,
    "messages": [
        {
            "type": "image",
            "originalContentUrl": IMG_URL,
            "previewImageUrl":    IMG_URL,
        },
        {
            "type": "text",
            "text": "🚄 台鐵小鋼彈 v2.0 頭像\n──────────────\n• 雲端 + 臺鐵徽章（品牌延續）\n• EMU900 車頭輪廓（FUTURE IS NOW）\n• 綠色速度線（EMU900 色帶）\n• v2.0 徽章（右下角）",
        },
    ],
}

resp = requests.post(
    "https://api.line.me/v2/bot/message/push",
    headers=headers,
    json=payload,
    timeout=10,
)

if resp.status_code == 200:
    print("✓ 已送出到 LINE")
else:
    print(f"✗ 失敗 {resp.status_code}: {resp.text}")
