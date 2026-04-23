# CLAUDE.md — 臺鐵小鋼彈 LINE Bot

## 專案概覽

臺鐵員工專用 LINE Bot（`tr_gundum`）。FastAPI + LINE Bot SDK v3，部署在 Railway.app。
主要功能：OD 時刻查詢、車次詳情、編組速查、機務 / 運務乘務查詢、Gemma AI 自然語言問答。

## 目錄結構

```
tr_gundum/
├── main.py                  # FastAPI 入口，所有 webhook 路由與 postback handler
├── railway.toml             # Railway 部署設定
├── requirements.txt
├── .env / .env.example      # 環境變數
├── services/
│   ├── parser.py            # LINE 訊息 → QueryIntent（意圖解析，無副作用）
│   ├── tdx.py               # TDX API 封裝（時刻表、車站清單）
│   ├── consist.py           # 本地編組資料庫（data/consist.json）
│   ├── formatter.py         # Flex Message 組裝，含列車圖片對應表
│   ├── auth.py              # 授權用戶管理（data/authorized_users.json）
│   ├── invite.py            # 邀請碼系統（LIFF）
│   └── ai.py                # Gemma 4 AI fallback（google-genai，function calling）
├── data/
│   ├── consist.json         # 編組資料庫（手動維護）
│   ├── authorized_users.json
│   └── stations_cache.json  # TDX 車站快取
├── scripts/
│   ├── setup_richmenu.py    # 建立 LINE Rich Menu
│   ├── import_consist.py    # 匯入編組資料
│   └── extract_from_new_py.py
├── templates/
│   ├── admin.html           # 後台管理介面（HTTP Basic Auth）
│   └── liff.html            # LIFF 邀請頁面
└── TRAIN_png/               # 列車圖片（PNG），由 /static/trains/ 提供
```

## 關鍵設計

### 意圖解析（parser.py）

`parse_query(text, user_id, is_admin)` → `QueryIntent`（dataclass union）

| Intent | 觸發條件 |
|--------|---------|
| `ODQuery` | `起站 終站 [日期]` |
| `TrainQuery` | 純數字車次 `[日期]` |
| `ConsistOnlyQuery` | `##車次` |
| `CrewQuery` | 含「機務」或「運務」關鍵字 |
| `HelpQuery` | `說明` / `?` / `help` 等 |
| `MyIdQuery` | `/myid` |
| `AuthAddQuery` | `/auth add Uxx...`（admin） |
| `AuthRemoveQuery` | `/auth remove Uxx...`（admin） |
| `RichMenuGuideQuery` | 圖文選單按鈕 |
| `UnknownQuery` | 其他，交給 AI fallback |

### 列車圖片（formatter.py `_TYPE_IMAGE_MAP`）

順序即優先順序。「優化EMU500」必須比「EMU500」早，否則會錯誤匹配。
- 太魯閣 → TEMU1000（不是 TEMU2000）
- 普悠瑪 → TEMU2000（不是 TEMU1000）

### AI Fallback（ai.py）

使用 Gemma 4（`gemma-4-31b-it`）+ google-genai function calling。
工具：`query_schedule`（OD 查詢）、`query_consist`（車種摘要）。
Chain-of-thought 思考過程在 LINE 回覆前需去除（`<think>...</think>` tag）。

### 群組 @mention

在群組 / 房間內，只有 @bot 的訊息才觸發。私聊所有訊息都觸發。

### 分頁（Postback）

OD 查詢結果以 10 班為一頁，透過 postback `schedule:origin:dest:date:page` 翻頁。

### 授權層級

- **一般用戶**：OD 查詢、車次查詢、幫助、/myid
- **授權員工**：額外開放 `##車次` 完整編組、乘務查詢
- **管理員**（`ADMIN_USER_IDS`）：授權名單管理、後台介面

## 環境變數

| 變數 | 必填 | 說明 |
|------|------|------|
| `LINE_CHANNEL_SECRET` | ✅ | |
| `LINE_CHANNEL_ACCESS_TOKEN` | ✅ | |
| `ADMIN_USER_IDS` | ✅ | 逗號分隔 LINE User ID |
| `STATIC_BASE_URL` | ✅ | 部署網址，用於列車圖片 URL |
| `TDX_CLIENT_ID` | 選填 | 無值時使用公開端點（有速率限制） |
| `TDX_CLIENT_SECRET` | 選填 | |
| `GEMINI_API_KEY` | 選填 | 無值時停用 AI fallback |
| `LIFF_ID` | 選填 | 邀請頁面 LIFF ID |
| `ADMIN_PASSWORD` | 選填 | 後台 HTTP Basic Auth 密碼 |

## 常用指令

```bash
# 本地啟動
uvicorn main:app --reload --port 8000

# 建立 Rich Menu（首次部署後執行一次）
python scripts/setup_richmenu.py

# 匯入編組資料
python scripts/import_consist.py
```

## 部署

Railway.app + Nixpacks 自動偵測。推 main branch 即觸發重部署。
Health check endpoint：`GET /health`

## 常見陷阱

- `STATIC_BASE_URL` 若未設定，所有列車圖片 URL 為 None，卡片不顯示圖片。
- `consist.json` 是手動維護的靜態檔，車種對應若有誤需直接改檔案並重新部署。
- `_TYPE_IMAGE_MAP` 匹配順序很重要，新增車種時注意放置位置。
- TDX API 有每日呼叫配額，無憑證時使用公開端點，流量大時可能觸發限速。
