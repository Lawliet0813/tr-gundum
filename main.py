import os
import re
import time
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import PlainTextResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    FlexMessage,
    FlexBubble,
    QuickReply,
    QuickReplyItem,
    PostbackAction,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    FollowEvent,
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)
from pydantic import BaseModel

from services.tdx import TDXClient
from services.consist import ConsistService
from services.auth import AuthService
from services.invite import InviteService
from services.parser import (
    parse_query,
    ODQuery, TrainQuery, ConsistOnlyQuery, HelpQuery,
    MyIdQuery, AuthAddQuery, AuthRemoveQuery, AuthListQuery,
    RichMenuGuideQuery, UnknownQuery,
)
from services.ai import GemmaAIService
from services.formatter import (
    PAGE_SIZE,
    build_schedule_flex,
    build_train_detail_flex,
    build_consist_flex,
    build_help_text,
    train_image_url,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_BASE_URL = os.getenv("STATIC_BASE_URL", "")
LIFF_ID = os.getenv("LIFF_ID", "")

_tdx: Optional[TDXClient] = None
_consist_svc: Optional[ConsistService] = None
_auth_svc: Optional[AuthService] = None
_invite_svc: Optional[InviteService] = None
_ai_svc: Optional[GemmaAIService] = None
_webhook_parser: Optional[WebhookParser] = None
_line_config: Optional[Configuration] = None

_http_security = HTTPBasic()

# user_id → timestamp，記錄正在等待輸入車次的用戶（查編組對話流程）
_pending_consist: dict[str, float] = {}
_PENDING_TTL = 300  # 5 分鐘內有效

_bot_user_id: Optional[str] = None  # 啟動時從 LINE API 取得


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _tdx, _consist_svc, _auth_svc, _invite_svc, _ai_svc, _webhook_parser, _line_config

    _line_config = Configuration(access_token=_require_env("LINE_CHANNEL_ACCESS_TOKEN"))
    _webhook_parser = WebhookParser(_require_env("LINE_CHANNEL_SECRET"))
    _consist_svc = ConsistService()
    _auth_svc = AuthService()
    _invite_svc = InviteService()

    _tdx = TDXClient(
        client_id=os.getenv("TDX_CLIENT_ID", ""),
        client_secret=os.getenv("TDX_CLIENT_SECRET", ""),
    )
    logger.info("Initialising TDX client…")
    await _tdx.init()
    logger.info(
        "TDX ready — %d stations loaded. Consist DB: %d trains (ver %s).",
        len(_tdx._stations),
        _consist_svc.train_count,
        _consist_svc.version,
    )

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        _ai_svc = GemmaAIService(api_key=gemini_key, tdx=_tdx, consist=_consist_svc)
        logger.info("Gemma AI service initialized (gemma-4-31b-it, tool use).")

    global _bot_user_id
    try:
        async with AsyncApiClient(_line_config) as api_client:
            api = AsyncMessagingApi(api_client)
            bot_info = await api.get_bot_info()
            _bot_user_id = bot_info.user_id
            logger.info("Bot user ID: %s", _bot_user_id)
    except Exception as exc:
        logger.warning("Failed to get bot user ID: %s", exc)

    yield


app = FastAPI(lifespan=lifespan)

_train_png_dir = os.path.join(os.path.dirname(__file__), "TRAIN_png")
if os.path.isdir(_train_png_dir):
    app.mount("/static/trains", StaticFiles(directory=_train_png_dir), name="trains")


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _reply(reply_token: str, messages: list) -> None:
    async with AsyncApiClient(_line_config) as api_client:
        api = AsyncMessagingApi(api_client)
        await api.reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=messages)
        )


async def _push(user_id: str, messages: list) -> None:
    async with AsyncApiClient(_line_config) as api_client:
        api = AsyncMessagingApi(api_client)
        await api.push_message(PushMessageRequest(to=user_id, messages=messages))


def _schedule_quick_reply(
    origin: str, dest: str, date: str, page: int, total: int
) -> Optional[QuickReply]:
    items = []
    if page > 0:
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=f"◀ 前{PAGE_SIZE}班",
                    data=f"schedule:{origin}:{dest}:{date}:{page - 1}",
                )
            )
        )
    if (page + 1) * PAGE_SIZE < total:
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=f"後{PAGE_SIZE}班 ▶",
                    data=f"schedule:{origin}:{dest}:{date}:{page + 1}",
                )
            )
        )
    return QuickReply(items=items) if items else None


def _check_admin_auth(credentials: HTTPBasicCredentials = Depends(_http_security)):
    password = os.getenv("ADMIN_PASSWORD", "")
    if not password:
        raise HTTPException(status_code=503, detail="ADMIN_PASSWORD not configured")
    ok = secrets.compare_digest(credentials.password.encode(), password.encode())
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Incorrect password",
            headers={"WWW-Authenticate": "Basic"},
        )


# ── Group mention helpers ──────────────────────────────────────────────────────

def _is_bot_mentioned(event: MessageEvent) -> bool:
    if not event.source or event.source.type not in ("group", "room"):
        return False
    if not _bot_user_id:
        return False
    mention = getattr(event.message, "mention", None)
    if mention and mention.mentionees:
        return any(getattr(m, "user_id", None) == _bot_user_id for m in mention.mentionees)
    return False


def _strip_bot_mention(text: str, message) -> str:
    mention = getattr(message, "mention", None)
    if not mention or not mention.mentionees:
        return text
    spans = sorted(
        [
            (m.index, m.index + m.length)
            for m in mention.mentionees
            if getattr(m, "user_id", None) == _bot_user_id
        ],
        reverse=True,
    )
    result = text
    for start, end in spans:
        result = result[:start] + result[end:]
    return result.strip()


# ── Query handlers ─────────────────────────────────────────────────────────────

async def handle_follow(reply_token: str, user_id: str) -> None:
    liff_hint = f"\n🔐 有員工邀請碼？\n點選單的「輸入邀請碼」按鈕即可啟用完整功能。" if LIFF_ID else ""
    text = (
        "🚂 歡迎使用臺鐵小鋼彈！\n\n"
        "我可以幫你：\n"
        "• 查詢台鐵時刻表（輸入：台北 高雄）\n"
        "• 查詢特定車次資訊（輸入：105）\n"
        "• 回答台鐵相關問題\n\n"
        "點下方選單按鈕開始使用。"
        + liff_hint
    )
    await _reply(reply_token, [TextMessage(text=text)])


async def handle_od_query(
    reply_token: str, origin_raw: str, dest_raw: str, date: str, page: int = 0,
    user_id: str = "",
) -> None:
    origin = _tdx.find_station(origin_raw)
    dest = _tdx.find_station(dest_raw)

    if not origin:
        await _reply(reply_token, [TextMessage(text=f"找不到車站「{origin_raw}」，請確認站名。")])
        return
    if not dest:
        await _reply(reply_token, [TextMessage(text=f"找不到車站「{dest_raw}」，請確認站名。")])
        return

    origin_id, origin_name = origin
    dest_id, dest_name = dest

    trains = await _tdx.query_od(origin_id, dest_id, date)
    if not trains:
        await _reply(reply_token, [TextMessage(text=f"{date} {origin_name}→{dest_name} 無班次資料。")])
        return

    authorized = _auth_svc.is_authorized(user_id)
    consists = (
        {t["train_no"]: _consist_svc.get(t["train_no"]) for t in trains}
        if authorized
        else {}
    )
    bubble_dict = build_schedule_flex(trains, origin_name, dest_name, date, page, consists)
    quick_reply = _schedule_quick_reply(origin_raw, dest_raw, date, page, len(trains))

    await _reply(reply_token, [
        FlexMessage(
            alt_text=f"{origin_name}→{dest_name} {date} 時刻表",
            contents=FlexBubble.from_dict(bubble_dict),
            quick_reply=quick_reply,
        )
    ])


async def handle_train_query(reply_token: str, train_no: str, date: str, user_id: str = "") -> None:
    authorized = _auth_svc.is_authorized(user_id)
    no_disp = train_no.lstrip("0") or train_no

    try:
        is_freight = int(no_disp) >= 7000
    except ValueError:
        is_freight = False

    if is_freight and not authorized:
        await _reply(reply_token, [TextMessage(text="此車次資訊不對外開放。")])
        return

    if is_freight:
        consist = _consist_svc.get(train_no)
        if not consist:
            await _reply(reply_token, [TextMessage(text=f"查無 {no_disp} 次的編組資料。\n資料版本：{_consist_svc.updated_at}")])
            return
        img_url = train_image_url(consist.get("type_name", ""), STATIC_BASE_URL)
        bubble_dict = build_consist_flex(no_disp, consist, _consist_svc.updated_at, image_url=img_url)
        await _reply(reply_token, [
            FlexMessage(
                alt_text=f"{no_disp} 次編組運用",
                contents=FlexBubble.from_dict(bubble_dict),
            )
        ])
        return

    train = await _tdx.query_train(train_no, date)
    consist = _consist_svc.get(train_no)

    if not train:
        if consist:
            await handle_consist_only(reply_token, no_disp, user_id)
        else:
            await _reply(reply_token, [TextMessage(text=f"{date} 查無 {no_disp} 次資料。")])
        return

    img_url = train_image_url(train.get("type_name", ""), STATIC_BASE_URL)
    bubble_dict = build_train_detail_flex(
        train, consist, date,
        authorized=authorized,
        image_url=img_url,
    )
    consist_qr = None
    if authorized:
        consist_qr = QuickReply(items=[
            QuickReplyItem(
                action=PostbackAction(
                    label="🔧 查編組",
                    data=f"consist:{no_disp}",
                    display_text=f"查 {no_disp} 次編組",
                )
            )
        ])
    await _reply(reply_token, [
        FlexMessage(
            alt_text=f"{train['type_name']} {no_disp} 次 {date}",
            contents=FlexBubble.from_dict(bubble_dict),
            quick_reply=consist_qr,
        )
    ])


async def handle_consist_only(reply_token: str, train_no: str, user_id: str) -> None:
    if not _auth_svc.is_authorized(user_id):
        await _reply(reply_token, [TextMessage(
            text="⛔ 編組查詢為員工授權功能。\n\n持有邀請碼者請點選單的「輸入邀請碼」按鈕啟用。"
        )])
        return

    consist = _consist_svc.get(train_no)
    if not consist:
        await _reply(reply_token, [TextMessage(text=f"查無 {train_no} 次的編組資料。\n資料版本：{_consist_svc.updated_at}")])
        return

    img_url = train_image_url(consist.get("type_name", ""), STATIC_BASE_URL)
    bubble_dict = build_consist_flex(train_no, consist, _consist_svc.updated_at, image_url=img_url)
    await _reply(reply_token, [
        FlexMessage(
            alt_text=f"{train_no} 次編組運用",
            contents=FlexBubble.from_dict(bubble_dict),
        )
    ])


async def handle_my_id(reply_token: str, user_id: str) -> None:
    await _reply(reply_token, [TextMessage(
        text=f"您的 LINE User ID：\n{user_id}"
    )])


async def _switch_rich_menu(user_id: str, authorized: bool) -> None:
    menu_id = os.getenv(
        "RICHMENU_AUTHORIZED_ID" if authorized else "RICHMENU_GENERAL_ID", ""
    )
    if not menu_id:
        return
    try:
        async with AsyncApiClient(_line_config) as api_client:
            api = AsyncMessagingApi(api_client)
            await api.link_rich_menu_id_to_user(user_id, menu_id)
    except Exception as exc:
        logger.warning("Rich menu switch failed for %s: %s", user_id, exc)


async def handle_auth_add(reply_token: str, sender_id: str, target_id: str) -> None:
    if not _auth_svc.is_admin(sender_id):
        await _reply(reply_token, [TextMessage(text="⛔ 僅管理員可執行此指令。")])
        return
    added = _auth_svc.add(target_id)
    msg = f"✅ 已授權 {target_id}" if added else f"ℹ️ {target_id} 已在授權清單中"
    await _reply(reply_token, [TextMessage(text=msg)])
    if added:
        await _switch_rich_menu(target_id, authorized=True)


async def handle_auth_remove(reply_token: str, sender_id: str, target_id: str) -> None:
    if not _auth_svc.is_admin(sender_id):
        await _reply(reply_token, [TextMessage(text="⛔ 僅管理員可執行此指令。")])
        return
    removed = _auth_svc.remove(target_id)
    msg = f"✅ 已移除 {target_id}" if removed else f"ℹ️ {target_id} 不在授權清單中"
    await _reply(reply_token, [TextMessage(text=msg)])
    if removed:
        await _switch_rich_menu(target_id, authorized=False)


async def handle_auth_list(reply_token: str, sender_id: str) -> None:
    if not _auth_svc.is_admin(sender_id):
        await _reply(reply_token, [TextMessage(text="⛔ 僅管理員可執行此指令。")])
        return
    users = _auth_svc.list_authorized()
    if not users:
        await _reply(reply_token, [TextMessage(text="授權清單目前為空。")])
    else:
        lines = "\n".join(f"• {uid}" for uid in users)
        await _reply(reply_token, [TextMessage(text=f"授權清單（{len(users)} 人）：\n{lines}")])


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "stations": len(_tdx._stations) if _tdx else 0,
        "consist_trains": _consist_svc.train_count if _consist_svc else 0,
        "consist_version": _consist_svc.version if _consist_svc else "",
    }


@app.get("/liff", response_class=HTMLResponse)
async def liff_page():
    template_path = Path(__file__).parent / "templates" / "liff.html"
    html = template_path.read_text(encoding="utf-8").replace("{{LIFF_ID}}", LIFF_ID)
    return HTMLResponse(content=html)


class RedeemRequest(BaseModel):
    code: str
    user_id: str


@app.post("/api/redeem")
async def api_redeem(body: RedeemRequest):
    if not _invite_svc or not _auth_svc:
        return JSONResponse({"ok": False, "message": "服務尚未初始化，請稍後再試。"}, status_code=503)

    ok = _invite_svc.redeem(body.code, body.user_id)
    if not ok:
        return JSONResponse({"ok": False, "message": "邀請碼無效或已使用。"})

    _auth_svc.add(body.user_id)
    try:
        await _switch_rich_menu(body.user_id, authorized=True)
        await _push(body.user_id, [TextMessage(text="✅ 授權成功！現在可以使用完整的員工功能了。")])
    except Exception as exc:
        logger.warning("Post-redeem push/menu failed for %s: %s", body.user_id, exc)

    return JSONResponse({"ok": True})


def _admin_html(codes: dict, auth_users: list) -> str:
    unused_count = sum(1 for v in codes.values() if v is None)
    used_count = sum(1 for v in codes.values() if v is not None)

    rows = ""
    for code, uid in sorted(codes.items(), key=lambda x: (x[1] is not None, x[0])):
        if uid is None:
            badge = '<span class="badge unused">未使用</span>'
            uid_cell = ""
        else:
            badge = '<span class="badge used">已使用</span>'
            uid_cell = f'<span class="uid">{uid}</span>'
        rows += f"<tr><td><strong>{code}</strong></td><td>{badge}</td><td>{uid_cell}</td></tr>\n"

    codes_table = (
        f"<table><tr><th>邀請碼</th><th>狀態</th><th>使用者 ID</th></tr>{rows}</table>"
        if codes else
        '<div class="empty">尚無邀請碼，點上方按鈕產生。</div>'
    )

    auth_rows = "".join(f'<tr><td class="uid">{u}</td></tr>' for u in auth_users)
    auth_table = (
        f"<table><tr><th>User ID</th></tr>{auth_rows}</table>"
        if auth_users else
        '<div class="empty">目前無授權用戶。</div>'
    )

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>臺鐵小鋼彈 — 管理面板</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,"PingFang TC",sans-serif;background:#f0f4f8;padding:24px 16px;color:#222}}
header{{display:flex;align-items:center;gap:10px;margin-bottom:24px}}
header h1{{font-size:1.2rem;color:#1a3a6b}}
.section{{background:#fff;border-radius:14px;padding:20px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.section h2{{font-size:.95rem;color:#555;margin-bottom:14px}}
.row{{display:flex;gap:10px;align-items:center}}
input[type=number]{{width:70px;padding:8px 10px;border:1.5px solid #d0d8e8;border-radius:8px;font-size:1rem}}
button{{padding:9px 18px;background:#1a3a6b;color:#fff;border:none;border-radius:8px;font-size:.9rem;font-weight:600;cursor:pointer}}
button.danger{{background:#c0392b}}
.stats{{font-size:.85rem;color:#888;margin-top:6px}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}}
th{{text-align:left;padding:6px 8px;border-bottom:2px solid #e8edf3;color:#888;font-weight:600}}
td{{padding:8px;border-bottom:1px solid #f0f4f8}}
.badge{{display:inline-block;padding:2px 8px;border-radius:99px;font-size:.78rem;font-weight:600}}
.badge.unused{{background:#e8f5e9;color:#2e7d32}}
.badge.used{{background:#fce4ec;color:#c62828}}
.uid{{font-size:.75rem;color:#aaa;word-break:break-all}}
.empty{{color:#aaa;font-size:.9rem;padding:16px 0;text-align:center}}
.section-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}}
</style>
</head>
<body>
<header><span style="font-size:1.5rem">🚂</span><h1>臺鐵小鋼彈 — 管理面板</h1></header>

<div class="section">
  <h2>產生邀請碼</h2>
  <form method="POST" action="/admin/gencode">
    <div class="row">
      <input type="number" name="n" value="1" min="1" max="20">
      <button type="submit">產生</button>
    </div>
  </form>
  <div class="stats">未使用：{unused_count} 張 ／ 已使用：{used_count} 張</div>
</div>

<div class="section">
  <div class="section-header">
    <h2>邀請碼清單</h2>
    <form method="POST" action="/admin/delete_unused" onsubmit="return confirm('確定刪除所有未使用的碼？')">
      <button type="submit" class="danger" style="font-size:.8rem;padding:6px 12px">刪除未使用</button>
    </form>
  </div>
  {codes_table}
</div>

<div class="section">
  <h2>已授權用戶（{len(auth_users)} 人）</h2>
  {auth_table}
</div>
</body>
</html>"""


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(credentials: HTTPBasicCredentials = Depends(_check_admin_auth)):
    codes = _invite_svc.list_all() if _invite_svc else {}
    auth_users = _auth_svc.list_authorized() if _auth_svc else []
    return HTMLResponse(content=_admin_html(codes, auth_users))


@app.post("/admin/gencode")
async def admin_gencode(request: Request, credentials: HTTPBasicCredentials = Depends(_check_admin_auth)):
    form = await request.form()
    n = int(form.get("n", 1))
    n = max(1, min(n, 20))
    _invite_svc.generate(n)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/delete_unused")
async def admin_delete_unused(credentials: HTTPBasicCredentials = Depends(_check_admin_auth)):
    _invite_svc.delete_unused()
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode()

    try:
        events = _webhook_parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as exc:
        logger.warning("Webhook parse error: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))

    for event in events:
        try:
            if isinstance(event, FollowEvent):
                user_id = event.source.user_id if event.source else ""
                await handle_follow(event.reply_token, user_id)

            elif isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
                source_type = event.source.type if event.source else "user"
                if source_type in ("group", "room"):
                    if not _is_bot_mentioned(event):
                        continue
                    text = _strip_bot_mention(event.message.text, event.message)
                else:
                    text = event.message.text.strip()
                user_id = event.source.user_id

                # 待機狀態：用戶剛按「查編組」，等待輸入車次
                if user_id in _pending_consist:
                    if time.time() - _pending_consist[user_id] < _PENDING_TTL:
                        if re.fullmatch(r"\d{1,4}[AB]?", text):
                            del _pending_consist[user_id]
                            await handle_consist_only(event.reply_token, text, user_id)
                            continue
                    del _pending_consist[user_id]

                intent = parse_query(text)

                if isinstance(intent, HelpQuery):
                    await _reply(event.reply_token, [TextMessage(text=build_help_text())])

                elif isinstance(intent, MyIdQuery):
                    await handle_my_id(event.reply_token, user_id)

                elif isinstance(intent, AuthAddQuery):
                    await handle_auth_add(event.reply_token, user_id, intent.target_user_id)

                elif isinstance(intent, AuthRemoveQuery):
                    await handle_auth_remove(event.reply_token, user_id, intent.target_user_id)

                elif isinstance(intent, AuthListQuery):
                    await handle_auth_list(event.reply_token, user_id)

                elif isinstance(intent, ConsistOnlyQuery):
                    await handle_consist_only(event.reply_token, intent.train_no, user_id)

                elif isinstance(intent, ODQuery):
                    await handle_od_query(
                        event.reply_token, intent.origin_raw, intent.dest_raw, intent.date,
                        user_id=user_id,
                    )

                elif isinstance(intent, TrainQuery):
                    await handle_train_query(event.reply_token, intent.train_no, intent.date, user_id)

                elif isinstance(intent, RichMenuGuideQuery):
                    if intent.keyword == "查編組":
                        _pending_consist[user_id] = time.time()
                    await _reply(event.reply_token, [TextMessage(text=intent.guide_text)])

                elif isinstance(intent, UnknownQuery):
                    if _ai_svc:
                        ai_text = await _ai_svc.reply(intent.text)
                    else:
                        ai_text = "輸入「幫助」查看使用說明。\n\n範例：台北 高雄　/　105　/　##105"
                    await _reply(event.reply_token, [TextMessage(text=ai_text)])

            elif isinstance(event, PostbackEvent):
                data = event.postback.data
                pb_user_id = event.source.user_id if event.source else ""

                if data.startswith("schedule:"):
                    _, origin_raw, dest_raw, date, page_str = data.split(":", 4)
                    await handle_od_query(
                        event.reply_token, origin_raw, dest_raw, date, int(page_str),
                        user_id=pb_user_id,
                    )

                elif data.startswith("consist:"):
                    train_no = data.split(":", 1)[1]
                    await handle_consist_only(event.reply_token, train_no, pb_user_id)

        except Exception as exc:
            logger.error("Error handling event: %s", exc, exc_info=True)

    return PlainTextResponse("OK")
