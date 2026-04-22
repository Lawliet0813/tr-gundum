import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
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
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)

from services.tdx import TDXClient
from services.consist import ConsistService
from services.auth import AuthService
from services.parser import (
    parse_query,
    ODQuery, TrainQuery, ConsistOnlyQuery, HelpQuery,
    MyIdQuery, AuthAddQuery, AuthRemoveQuery, AuthListQuery,
    UnknownQuery,
)
from services.ai import GeminiService
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

_tdx: Optional[TDXClient] = None
_consist_svc: Optional[ConsistService] = None
_auth_svc: Optional[AuthService] = None
_ai_svc: Optional[GeminiService] = None
_webhook_parser: Optional[WebhookParser] = None
_line_config: Optional[Configuration] = None


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _tdx, _consist_svc, _auth_svc, _ai_svc, _webhook_parser, _line_config

    _line_config = Configuration(access_token=_require_env("LINE_CHANNEL_ACCESS_TOKEN"))
    _webhook_parser = WebhookParser(_require_env("LINE_CHANNEL_SECRET"))
    _consist_svc = ConsistService()
    _auth_svc = AuthService()
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        _ai_svc = GeminiService(api_key=gemini_key)
        logger.info("Gemini AI service initialized.")

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


# ── Query handlers ─────────────────────────────────────────────────────────────

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
    await _reply(reply_token, [
        FlexMessage(
            alt_text=f"{train['type_name']} {no_disp} 次 {date}",
            contents=FlexBubble.from_dict(bubble_dict),
        )
    ])


async def handle_consist_only(reply_token: str, train_no: str, user_id: str) -> None:
    if not _auth_svc.is_authorized(user_id):
        await _reply(reply_token, [TextMessage(
            text="⛔ 編組查詢為員工授權功能。\n\n請將您的 LINE ID 傳給管理員申請授權：\n"
                 f"`/myid` 可查詢您的 ID"
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
        text=f"您的 LINE User ID：\n{user_id}\n\n將此 ID 傳給管理員，即可申請編組查詢權限。"
    )])


async def handle_auth_add(reply_token: str, sender_id: str, target_id: str) -> None:
    if not _auth_svc.is_admin(sender_id):
        await _reply(reply_token, [TextMessage(text="⛔ 僅管理員可執行此指令。")])
        return
    added = _auth_svc.add(target_id)
    msg = f"✅ 已授權 {target_id}" if added else f"ℹ️ {target_id} 已在授權清單中"
    await _reply(reply_token, [TextMessage(text=msg)])


async def handle_auth_remove(reply_token: str, sender_id: str, target_id: str) -> None:
    if not _auth_svc.is_admin(sender_id):
        await _reply(reply_token, [TextMessage(text="⛔ 僅管理員可執行此指令。")])
        return
    removed = _auth_svc.remove(target_id)
    msg = f"✅ 已移除 {target_id}" if removed else f"ℹ️ {target_id} 不在授權清單中"
    await _reply(reply_token, [TextMessage(text=msg)])


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
            if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
                text = event.message.text.strip()
                user_id = event.source.user_id
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

                elif isinstance(intent, UnknownQuery):
                    if _ai_svc:
                        ai_text = await _ai_svc.reply(intent.text)
                    else:
                        ai_text = "輸入「幫助」查看使用說明。\n\n範例：台北 高雄　/　105　/　##105"
                    await _reply(event.reply_token, [TextMessage(text=ai_text)])

            elif isinstance(event, PostbackEvent):
                data = event.postback.data
                if data.startswith("schedule:"):
                    _, origin_raw, dest_raw, date, page_str = data.split(":", 4)
                    pb_user_id = event.source.user_id if event.source else ""
                    await handle_od_query(
                        event.reply_token, origin_raw, dest_raw, date, int(page_str),
                        user_id=pb_user_id,
                    )

        except Exception as exc:
            logger.error("Error handling event: %s", exc, exc_info=True)

    return PlainTextResponse("OK")
