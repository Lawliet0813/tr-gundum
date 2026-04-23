# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概覽

臺鐵員工專用 LINE Bot（`tr_gundum`）。FastAPI + LINE Bot SDK v3，部署在 Railway.app。
主要功能：OD 時刻查詢、車次詳情、編組速查、機務 / 運務乘務查詢、Gemma AI 自然語言問答。

## 常用指令

```bash
# 建立虛擬環境與安裝依賴
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 本地啟動（reload mode）
uvicorn main:app --reload --port 8000

# 本地對 LINE Platform 測 webhook：搭配 ngrok 之類工具

# 建立 / 更新 Rich Menu（首次部署後、richmenu_*.png 有變更時執行）
python scripts/setup_richmenu.py

# 匯入 / 重建編組資料（把 xlsx 轉成 data/consist.json 的 formation/crew 欄位）
python scripts/import_consist.py

# 重建時刻表（讀 data/timetables/*.ods → 產生 full_timetables.json + train_list.json）
python scripts/build_timetables.py

# 從 PDF 抽取機車運用資訊（depot、運用碼、flags、ㄏㄙ 回送標記等）→ consist_from_pdf.json
.venv/bin/python3 scripts/parse_consist_pdf.py

# 合併 PDF + xlsx + ODS → 最終 consist.json（schema v2）
.venv/bin/python3 scripts/merge_consist.py

# 產生 / 推播 bot 頭像
python scripts/make_avatar.py
python scripts/send_avatar.py
```

無測試套件與 linter。改動後以本地啟動 + LINE LIFF / ngrok 端對端驗證為主。

## 目錄結構

```
tr_gundum/
├── main.py                  # FastAPI 入口：lifespan init、webhook、postback、admin 路由
├── railway.toml             # Railway 部署設定（Nixpacks + healthcheck /health）
├── requirements.txt
├── .env / .env.example      # 環境變數
├── services/
│   ├── parser.py            # 文字訊息 → QueryIntent（dataclass union，純函數無副作用）
│   ├── tdx.py               # TDX API 封裝 + 本地 full_timetables.json 快取層
│   ├── consist.py           # 本地編組資料庫（data/consist.json）
│   ├── formatter.py         # Flex Message 組裝、列車圖片對應表 _TYPE_IMAGE_MAP
│   ├── auth.py              # 授權用戶管理（data/authorized_users.json）
│   ├── invite.py            # 邀請碼系統（LIFF 相關）
│   └── ai.py                # Gemma 4 AI fallback（google-genai function calling）
├── data/
│   ├── consist.json         # 編組資料庫（schema v2，載入於 ConsistService）。由 scripts/merge_consist.py 從 PDF + ODS + train_list 三源合併
│   ├── authorized_users.json
│   ├── stations_cache.json  # TDX 車站快取（混雜 13 個真正 TRA StationID + 184 個從 ODS 抽出的衍生 999* 項，部分為 ODS 簡寫；有 TDX 憑證時重抓才乾淨）
│   ├── full_timetables.json # 本地時刻表快取（services/tdx.py 啟動時載入），由 scripts/build_timetables.py 產生
│   ├── train_list.json      # 每車次的營運區間（origin/destination/route）；tdx.py 用它提供正確的「起訖站」而非 stops 首末
│   ├── timetables/          # 臺鐵官方 ODS 原檔，下載來源見 scripts/build_timetables.py 頂部註解
│   ├── richmenu_general.png     # 一般使用者 Rich Menu 圖
│   └── richmenu_authorized.png  # 授權員工 Rich Menu 圖
├── scripts/
│   ├── setup_richmenu.py    # 建立兩份 Rich Menu、與上面兩張 PNG 綁定
│   ├── import_consist.py    # xlsx → consist.json
│   ├── build_timetables.py  # data/timetables/*.ods → full_timetables.json + train_list.json
│   ├── parse_consist_pdf.py # 從 PDF 抽機車運用（pdfplumber，獨立產物 data/consist_from_pdf.json）
│   ├── merge_consist.py     # PDF + xlsx + ODS 合併 → data/consist.json（schema v2）
│   ├── make_avatar.py / send_avatar.py
│   └── extract_from_new_py.py
├── templates/
│   ├── admin.html           # 後台管理介面（HTTP Basic Auth）
│   └── liff.html            # LIFF 邀請頁面
└── TRAIN_png/               # 列車圖片（PNG），由 /static/trains/ 提供
```

## 關鍵設計

### FastAPI 生命週期（main.py `lifespan`）

啟動時建立 `TDXClient` → `ConsistService` → `GemmaAIService`（若 `GEMINI_API_KEY` 有值），掛到 `app.state`。
`TDXClient` 於初始化同步載入 `data/full_timetables.json` 作為本地快取；若檔案不存在或損毀仍可啟動，只是完整時刻會 miss。

### 意圖解析（parser.py）

`parse_query(text: str) -> QueryIntent`。純函數，不帶 `user_id` / `is_admin`（授權檢查是在 `main.py` 的 handler 內另做）。

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
| `AuthListQuery` | `/auth list`（admin） |
| `RichMenuGuideQuery` | 圖文選單按鈕 |
| `UnknownQuery` | 其他，交給 AI fallback |

> README 的 `+auth` / `-auth` 寫法是舊版，parser 實際只認 `/auth <add|remove|list>`。

### 列車圖片（formatter.py `_TYPE_IMAGE_MAP`）

順序即優先順序。「優化EMU500」必須比「EMU500」早，否則會錯誤匹配。
- 太魯閣 → TEMU1000（不是 TEMU2000）
- 普悠瑪 → TEMU2000（不是 TEMU1000）

### AI Fallback（ai.py — `GemmaAIService`）

使用 Gemma 4（預設 `gemma-4-31b-it`）+ google-genai function calling。
工具：`query_schedule`（OD 查詢）、`query_consist`（車種摘要）、`query_location`（由車次 + 現在時間推算「目前大約位置」）。
System prompt 強制繁中、禁 Markdown、箭頭用 Unicode `→`。Chain-of-thought `<think>...</think>` 在送到 LINE 前要剝除。

### 群組 @mention

群組 / 房間只有 @bot 的訊息才觸發（`_is_bot_mentioned` + `_strip_bot_mention`）；私聊所有訊息都觸發。

### Rich Menu 雙版本

授權狀態變更（`handle_auth_add` / `handle_auth_remove`）時會呼叫 `_switch_rich_menu` 把使用者切到對應 menu。
`setup_richmenu.py` 會建立 general / authorized 兩份 menu、分別綁到 `data/richmenu_general.png` 和 `data/richmenu_authorized.png`。新增 menu 按鈕時兩份都要更新。

### 分頁（Postback）

OD 查詢結果以 10 班為一頁，透過 postback `schedule:origin:dest:date:page` 翻頁。

### 編組對話流程（in-memory state）

`main.py` 頂部維護 `user_id → timestamp` 的 dict，記錄「按了編組速查、正在等輸入車次」的使用者。這是 **process-local state**，多個 worker 或重啟後會失效——這是目前設計上刻意接受的取捨（流程只維持幾秒）。

### 授權層級

- **一般用戶**：OD 查詢、車次查詢、幫助、/myid
- **授權員工**：額外開放 `##車次` 完整編組、乘務查詢
- **管理員**（`ADMIN_USER_IDS`）：授權名單管理、`/admin` 後台介面

## 環境變數

| 變數 | 必填 | 說明 |
|------|------|------|
| `LINE_CHANNEL_SECRET` | ✅ | |
| `LINE_CHANNEL_ACCESS_TOKEN` | ✅ | |
| `ADMIN_USER_IDS` | ✅ | 逗號分隔 LINE User ID |
| `STATIC_BASE_URL` | ✅ | 部署網址，用於列車圖片 URL |
| `TDX_CLIENT_ID` | 選填 | 無值時使用公開端點（有速率限制） |
| `TDX_CLIENT_SECRET` | 選填 | |
| `GEMINI_API_KEY` | 選填 | 無值時停用 AI fallback（lifespan 跳過建立 `GemmaAIService`） |
| `LIFF_ID` | 選填 | 邀請頁面 LIFF ID |
| `ADMIN_PASSWORD` | 選填 | `/admin` 後台 HTTP Basic Auth 密碼 |

## 部署

Railway.app + Nixpacks 自動偵測。推 `main` 即觸發重部署。
Health check endpoint：`GET /health`。

## 常見陷阱

- `STATIC_BASE_URL` 若未設定，所有列車圖片 URL 為 None，卡片不顯示圖片。
- `consist.json` 是手動維護的靜態檔，車種對應若有誤需直接改檔案並重新部署。
- `_TYPE_IMAGE_MAP` 匹配順序很重要，新增車種時注意放置位置。
- `data/full_timetables.json` 是 TDX 快取兼 offline fallback，若重新產生的檔 schema 不符 `TDXClient._load_full_timetables` 的預期會整份載不進來但不中斷啟動。
- TDX API 有每日呼叫配額，無憑證時使用公開端點，流量大時可能觸發限速。
- 編組對話流程是 in-memory dict；若改成多 worker 部署會壞掉，需先換成外部 state。
- Parser 只認 `/auth <add|remove|list>`，舊文件中的 `+auth` / `-auth` 已無效。
