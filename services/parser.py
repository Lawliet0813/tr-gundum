"""Parse incoming LINE message text into query intents."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Union

TW_TZ = timezone(timedelta(hours=8))


@dataclass
class ODQuery:
    origin_raw: str
    dest_raw: str
    date: str  # YYYY-MM-DD


@dataclass
class TrainQuery:
    train_no: str  # padded to 4 digits
    date: str  # YYYY-MM-DD


@dataclass
class ConsistOnlyQuery:
    """##車次：只查編組，不查 TDX 時刻。"""
    train_no: str  # 原始輸入（無前導零）


@dataclass
class HelpQuery:
    pass


@dataclass
class MyIdQuery:
    """用戶查詢自己的 LINE User ID。"""
    pass


@dataclass
class AuthAddQuery:
    """管理員新增授權用戶。"""
    target_user_id: str


@dataclass
class AuthRemoveQuery:
    """管理員移除授權用戶。"""
    target_user_id: str


@dataclass
class AuthListQuery:
    """管理員查看授權清單。"""
    pass


@dataclass
class CrewQuery:
    """乘務查詢：機務（司機員/機班）或運務（車長）。"""
    train_no: str
    crew_type: str  # "mech" 或 "ops"


@dataclass
class RichMenuGuideQuery:
    """圖文選單按鈕觸發的使用提示。"""
    keyword: str
    guide_text: str


@dataclass
class UnknownQuery:
    text: str


QueryIntent = Union[
    ODQuery, TrainQuery, ConsistOnlyQuery, HelpQuery,
    MyIdQuery, AuthAddQuery, AuthRemoveQuery, AuthListQuery,
    CrewQuery, RichMenuGuideQuery, UnknownQuery,
]

_RICHMENU_GUIDES: dict[str, str] = {
    "查時刻": (
        "🕐 時刻表查詢\n\n"
        "請輸入起站和終站，例如：\n\n"
        "  台北 高雄        ← 今天\n"
        "  台北 高雄 明天   ← 明天\n"
        "  台北 高雄 0530   ← 5/30\n\n"
        "支援分隔符：空格 / → / ->"
    ),
    "查車次": (
        "🚞 車次查詢\n\n"
        "請輸入車次號碼，例如：\n\n"
        "  105          ← 今天 105 次\n"
        "  105 明天     ← 明天 105 次\n"
        "  ##105        ← 完整編組（授權員工）"
    ),
    "查編組": (
        "🔧 編組查詢\n\n"
        "請直接輸入車次號碼：\n\n"
        "  105\n"
        "  1035\n\n"
        "⚠️ 此功能僅限授權員工使用"
    ),
}

_HELP_WORDS = {"help", "幫助", "說明", "使用說明", "指令", "?", "？", "#說明", "##說明"}
_MYID_WORDS = {"/myid", "myid", "/我的id", "我的id"}
_DATE_ALIASES = {"今天": 0, "今日": 0, "明天": 1, "明日": 1, "後天": 2, "後日": 2}


def _today() -> datetime:
    return datetime.now(TW_TZ)


def _parse_date(token: str) -> str | None:
    token = token.strip()
    if token in _DATE_ALIASES:
        d = _today() + timedelta(days=_DATE_ALIASES[token])
        return d.strftime("%Y-%m-%d")

    # MMDD 四位數字
    if re.fullmatch(r"\d{4}", token):
        try:
            return datetime(_today().year, int(token[:2]), int(token[2:])).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # MM/DD 或 MM-DD
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})", token)
    if m:
        try:
            return datetime(_today().year, int(m.group(1)), int(m.group(2))).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # YYYY-MM-DD
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
        return token

    return None


def parse_query(text: str) -> QueryIntent:
    text = text.strip()

    if text in _RICHMENU_GUIDES:
        return RichMenuGuideQuery(keyword=text, guide_text=_RICHMENU_GUIDES[text])

    if text.lower() in _HELP_WORDS:
        return HelpQuery()

    if text.lower() in _MYID_WORDS:
        return MyIdQuery()

    # 管理指令 /auth add Uxxxxx / /auth remove Uxxxxx / /auth list
    m = re.fullmatch(r"/auth\s+(add|remove)\s+(U[a-fA-F0-9]+)", text, re.IGNORECASE)
    if m:
        action, uid = m.group(1).lower(), m.group(2)
        return AuthAddQuery(uid) if action == "add" else AuthRemoveQuery(uid)

    if re.fullmatch(r"/auth\s+list", text, re.IGNORECASE):
        return AuthListQuery()

    # 格式錯誤的 /auth 指令（早期捕捉，避免落入 OD parser）
    if re.match(r"/auth\b", text, re.IGNORECASE):
        return UnknownQuery(text=text)

    # ## 前綴 → 純編組查詢（不接日期，因為資料是靜態的）
    if text.startswith("##"):
        no = text[2:].strip()
        if no and (re.fullmatch(r"\d+", no) or re.fullmatch(r"\d+[AB]", no)):
            return ConsistOnlyQuery(train_no=no)
        return UnknownQuery(text=text)

    # 純數字（或數字+A/B尾綴）→ 車次查詢（時刻＋編組）
    if re.fullmatch(r"\d{1,4}", text):
        return TrainQuery(train_no=text.zfill(4), date=_today().strftime("%Y-%m-%d"))

    if re.fullmatch(r"\d+[AB]", text):
        return TrainQuery(train_no=text, date=_today().strftime("%Y-%m-%d"))

    # "車次 日期"
    m = re.fullmatch(r"(\d{1,4}[AB]?)\s+(\S+)", text)
    if m:
        date = _parse_date(m.group(2))
        if date:
            return TrainQuery(train_no=m.group(1).zfill(4) if m.group(1).isdigit() else m.group(1),
                              date=date)

    # 乘務查詢：車次 + 機務/運務關鍵字（或反序）
    _CREW_MECH = r"(?:司機員|司機|機班|誰開|機務乘務|機務)"
    _CREW_OPS  = r"(?:列車長|車長|車班|運務乘務|運務)"
    _TRAIN_PAT = r"(\d{1,4}[AB]?)"

    def _norm_no(s: str) -> str:
        return s.zfill(4) if s.isdigit() else s

    for pat, ctype in [
        (rf"{_TRAIN_PAT}(?:的|[\s　])*{_CREW_MECH}", "mech"),
        (rf"{_CREW_MECH}(?:[\s　]*){_TRAIN_PAT}", "mech"),
        (rf"{_TRAIN_PAT}(?:的|[\s　])*{_CREW_OPS}", "ops"),
        (rf"{_CREW_OPS}(?:[\s　]*){_TRAIN_PAT}", "ops"),
    ]:
        m = re.fullmatch(pat, text)
        if m:
            return CrewQuery(train_no=_norm_no(m.group(1)), crew_type=ctype)

    # OD 查詢：用空格、→、-> 分隔
    parts = re.split(r"[\s→\->]+", text)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) >= 3:
        date = _parse_date(parts[-1])
        if date:
            return ODQuery(origin_raw=parts[0], dest_raw=parts[1], date=date)
        return ODQuery(origin_raw=parts[0], dest_raw=parts[1], date=_today().strftime("%Y-%m-%d"))

    if len(parts) == 2:
        date = _parse_date(parts[-1])
        if not date:
            return ODQuery(origin_raw=parts[0], dest_raw=parts[1], date=_today().strftime("%Y-%m-%d"))

    return UnknownQuery(text=text)
