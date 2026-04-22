"""Build LINE Flex Messages for train schedule query results."""

from datetime import datetime
from typing import Optional

PAGE_SIZE = 10
WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]


def _weekday(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return WEEKDAY_ZH[d.weekday()]


def _duration(dep: str, arr: str) -> str:
    try:
        d = datetime.strptime(dep, "%H:%M")
        a = datetime.strptime(arr, "%H:%M")
        diff = (a - d).seconds // 60
        if diff < 0:
            diff += 1440
        h, m = divmod(diff, 60)
        return f"{h}時{m:02d}分" if h else f"{m}分"
    except Exception:
        return ""


def _consist_summary(consist: Optional[dict]) -> str:
    """單行摘要，用於時刻列表顯示。"""
    if not consist:
        return ""
    parts = []
    if consist.get("type_name"):
        parts.append(consist["type_name"])
    if consist.get("formation"):
        parts.append(consist["formation"])
    return "　".join(parts)


# ── 時刻列表 Flex ─────────────────────────────────────────────────────────────

def build_schedule_flex(
    trains: list[dict],
    origin_name: str,
    dest_name: str,
    date: str,
    page: int,
    consists: dict[str, Optional[dict]],
) -> dict:
    start = page * PAGE_SIZE
    page_trains = trains[start : start + PAGE_SIZE]
    total = len(trains)
    wd = _weekday(date)
    date_short = date[5:].replace("-", "/")
    total_pages = (total - 1) // PAGE_SIZE + 1

    rows = []
    for t in page_trains:
        train_no_disp = t["train_no"].lstrip("0") or "0"
        consist = consists.get(t["train_no"])
        consist_text = _consist_summary(consist)
        dur = _duration(t["departure"], t["arrival"])

        name_row = {
            "type": "text",
            "text": f"{t['type_name']} {train_no_disp}",
            "weight": "bold",
            "size": "sm",
            "color": "#1a1a2e",
        }
        sub_contents = [name_row]
        if consist_text:
            sub_contents.append({
                "type": "text",
                "text": consist_text,
                "size": "xs",
                "color": "#888888",
                "wrap": True,
            })

        rows.append({
            "type": "box",
            "layout": "horizontal",
            "spacing": "md",
            "paddingTop": "8px",
            "paddingBottom": "8px",
            "contents": [
                {"type": "box", "layout": "vertical", "flex": 3, "contents": sub_contents},
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 2,
                    "contents": [
                        {
                            "type": "text",
                            "text": f"{t['departure']}→{t['arrival']}",
                            "size": "sm",
                            "align": "end",
                            "color": "#1a73e8",
                        },
                        {
                            "type": "text",
                            "text": dur,
                            "size": "xs",
                            "align": "end",
                            "color": "#888888",
                        },
                    ],
                },
            ],
        })
        rows.append({"type": "separator", "color": "#eeeeee"})

    if rows and rows[-1]["type"] == "separator":
        rows.pop()

    page_info = f"第 {page + 1}/{total_pages} 頁（共 {total} 班）"

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1a73e8",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "text",
                    "text": f"{origin_name}  →  {dest_name}",
                    "color": "#ffffff",
                    "weight": "bold",
                    "size": "md",
                },
                {
                    "type": "text",
                    "text": f"{date_short}（{wd}）　{page_info}",
                    "color": "#d0e4ff",
                    "size": "xs",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "none",
            "paddingAll": "12px",
            "contents": rows or [
                {"type": "text", "text": "此頁無班次資料", "color": "#888888", "size": "sm"}
            ],
        },
    }


# ── 車次詳細 Flex ─────────────────────────────────────────────────────────────

def build_train_detail_flex(
    train: dict,
    consist: Optional[dict],
    date: str,
) -> dict:
    train_no_disp = train["train_no"].lstrip("0") or "0"
    wd = _weekday(date)
    date_short = date[5:].replace("-", "/")

    header_contents = [
        {
            "type": "text",
            "text": f"{train['type_name']}　{train_no_disp} 次",
            "color": "#ffffff",
            "weight": "bold",
            "size": "md",
        },
        {
            "type": "text",
            "text": f"{train['start_name']} → {train['end_name']}",
            "color": "#d0e4ff",
            "size": "xs",
        },
        {
            "type": "text",
            "text": f"{date_short}（{wd}）",
            "color": "#d0e4ff",
            "size": "xs",
        },
    ]

    if consist:
        if consist.get("formation"):
            header_contents.append({
                "type": "text",
                "text": f"編組：{consist['formation']}",
                "color": "#ffe082",
                "size": "xs",
            })
        if consist.get("route"):
            header_contents.append({
                "type": "text",
                "text": f"區間：{consist['route']}",
                "color": "#ffe082",
                "size": "xs",
                "wrap": True,
            })

    stop_rows = []
    stops = train.get("stops", [])
    for i, s in enumerate(stops):
        is_first = i == 0
        is_last = i == len(stops) - 1
        time_text = s["departure"] if is_first else s["arrival"]
        color = "#1a73e8" if (is_first or is_last) else "#333333"
        weight = "bold" if (is_first or is_last) else "regular"

        stop_rows.append({
            "type": "box",
            "layout": "horizontal",
            "spacing": "md",
            "paddingTop": "4px",
            "paddingBottom": "4px",
            "contents": [
                {
                    "type": "text",
                    "text": s["station_name"],
                    "flex": 2,
                    "size": "sm",
                    "color": color,
                    "weight": weight,
                },
                {
                    "type": "text",
                    "text": time_text,
                    "flex": 1,
                    "size": "sm",
                    "align": "end",
                    "color": color,
                    "weight": weight,
                },
            ],
        })
        if not is_last:
            stop_rows.append({"type": "separator", "color": "#eeeeee"})

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1a3a6b",
            "paddingAll": "12px",
            "contents": header_contents,
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "none",
            "paddingAll": "12px",
            "contents": stop_rows or [
                {"type": "text", "text": "無停靠資料", "color": "#888888", "size": "sm"}
            ],
        },
    }


# ── 編組詳細 Flex（純編組查詢，無需 TDX）─────────────────────────────────────

def build_consist_flex(train_no: str, consist: dict, version_date: str) -> dict:
    """給 ## 指令用，顯示完整編組運用資訊。"""
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#37474f",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "text",
                    "text": f"{train_no} 次　編組運用",
                    "color": "#ffffff",
                    "weight": "bold",
                    "size": "md",
                },
                {
                    "type": "text",
                    "text": f"資料日期：{version_date}",
                    "color": "#b0bec5",
                    "size": "xs",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "12px",
            "contents": [
                _info_row("車型",   consist.get("type_name", "—")),
                _info_row("編組",   consist.get("formation", "—")),
                _info_row("區間",   consist.get("route", "—")),
                _info_row("機務乘務", consist.get("crew_mech", "—"), wrap=True),
                _info_row("運務乘務", consist.get("crew_ops", "—"), wrap=True),
            ],
        },
    }


def _info_row(label: str, value: str, wrap: bool = False) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "spacing": "xs",
        "contents": [
            {"type": "text", "text": label, "size": "xs", "color": "#888888"},
            {"type": "text", "text": value or "—", "size": "sm", "color": "#1a1a2e", "wrap": wrap},
        ],
    }


# ── 純文字 ─────────────────────────────────────────────────────────────────────

def build_help_text() -> str:
    return (
        "🚂 台鐵小鋼彈 使用說明\n\n"
        "【時刻查詢】\n"
        "  台北 高雄          → 今天班表\n"
        "  台北 高雄 明天     → 明天班表\n"
        "  台北 高雄 0425     → 4/25 班表\n\n"
        "【車次查詢（時刻＋編組）】\n"
        "  105               → 今天 105 次\n"
        "  0105 明天         → 明天 105 次\n\n"
        "【編組運用查詢（授權員工）】\n"
        "  ##105             → 105 次完整編組資訊\n\n"
        "【其他】\n"
        "  /myid             → 查詢您的 LINE ID\n\n"
        "分隔符：空格 / → / ->\n"
        "日期：今天 / 明天 / 後天 / MMDD / MM/DD"
    )
