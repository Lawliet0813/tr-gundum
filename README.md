# 臺鐵小鋼彈 LINE Bot

台鐵員工專用 LINE Bot，支援即時時刻查詢、列車編組速查、乘務查詢，以及 AI 知識問答。

## 功能

| 功能 | 指令格式 | 說明 |
|------|---------|------|
| OD 時刻查詢 | `台北 高雄` | 今天起訖站班次 |
| OD 時刻查詢（指定日） | `台北 高雄 明天` / `台北 高雄 0530` | 明天或指定月日 |
| 車次查詢 | `105` / `105 明天` | 車次時刻 + 停靠站 + 編組 |
| 完整編組查詢 | `##105` | 僅查編組（授權員工） |
| 乘務查詢（機務） | 關鍵字含「機務」 | 司機員 / 機班資訊 |
| 乘務查詢（運務） | 關鍵字含「運務」 | 車長資訊 |
| 說明 | `說明` / `?` / `help` | 顯示使用說明 |
| 查我的 ID | `/myid` | 回傳自己的 LINE User ID |
| AI 問答 | 自然語言 | Gemma 4 fallback，可呼叫 TDX 工具 |

### 管理員指令（需 ADMIN_USER_IDS 設定）

| 功能 | 指令 |
|------|------|
| 新增授權用戶 | `+auth Uxxxxxxxxxx` |
| 移除授權用戶 | `-auth Uxxxxxxxxxx` |
| 查看授權清單 | `auth list` |

## 技術架構

```
LINE Webhook
    │
    ▼
main.py (FastAPI)
    ├── services/parser.py    查詢意圖解析
    ├── services/tdx.py       TDX API 時刻查詢
    ├── services/consist.py   本地編組資料庫
    ├── services/formatter.py Flex Message 組裝
    ├── services/auth.py      授權管理
    ├── services/invite.py    邀請碼（LIFF）
    └── services/ai.py        Gemma AI fallback
```

## 環境設定

複製 `.env.example` 為 `.env`：

```
LINE_CHANNEL_SECRET=      # LINE Developer Console 取得
LINE_CHANNEL_ACCESS_TOKEN=
TDX_CLIENT_ID=            # 選填，有效時解鎖完整 TDX 功能
TDX_CLIENT_SECRET=
ADMIN_USER_IDS=           # 逗號分隔，可多人
STATIC_BASE_URL=          # 部署後的公開網址（用於列車圖片）
LIFF_ID=                  # LINE LIFF App ID
GEMINI_API_KEY=           # 選填，啟用 Gemma AI 問答
ADMIN_PASSWORD=           # 後台管理員密碼
```

## 本地開發

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

測試 webhook 時需搭配 ngrok 或類似工具。

## 部署（Railway.app）

已設定 `railway.toml`，推送到 GitHub 後 Railway 自動部署：

```
Start: uvicorn main:app --host 0.0.0.0 --port $PORT
Health: GET /health
```

在 Railway 環境變數頁填入上述所有必要金鑰。

## 列車圖片對應

圖片存放於 `TRAIN_png/`，由 `services/formatter.py` 的 `_TYPE_IMAGE_MAP` 對應：

| 車種關鍵字 | 圖片檔 | 備註 |
|-----------|-------|------|
| 太魯閣 | TEMU1000.png | |
| 普悠瑪 | TEMU2000.png | |
| EMU3000 | EMU3000.png | |
| 優化EMU500 | EMU500_A.png | 須比 EMU500 優先匹配 |
| EMU900 | EMU900.png | |
| EMU800 | EMU800.png | |
| EMU700 | EMU700.png | |
| EMU500 | EMU500.png | |
| E1000 | E1000.png | |
| E500 | E500.png | |
| DRC / DMU | DMU3100.png | |
| R200 | R200-L.png | |
| R180 | R180-190-R_Later.png | |

> 對應順序即優先順序，越具體的關鍵字排越前。
