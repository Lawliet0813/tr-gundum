"""Build LINE Flex Messages for train schedule query results."""

from datetime import datetime
from typing import Optional

PAGE_SIZE = 10
WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]

# type_name keyword → image filename
_TYPE_IMAGE_MAP = [
    ("太魯閣",      "TEMU1000.png"),
    ("普悠瑪",      "TEMU2000.png"),
    ("EMU3000",     "EMU3000.png"),
    ("優化EMU500",  "EMU500_A.png"),
    ("EMU900",      "EMU900.png"),
    ("EMU800",      "EMU800.png"),
    ("EMU700",      "EMU700.png"),
    ("EMU500",      "EMU500.png"),
    ("E1000",       "E1000.png"),
    ("E500",        "E500.png"),
    ("DRC",         "DMU3100.png"),
    ("DMU",         "DMU3100.png"),
    ("R200",        "R200-L.png"),
    ("R180",        "R180-190-R_Later.png"),
]

def train_image_url(type_name: str, base_url: str) -> Optional[str]:
    if not base_url: return None
    for keyword, filename in _TYPE_IMAGE_MAP:
        if keyword in (type_name or ""):
            return f"{base_url.rstrip('/')}/static/trains/{filename}"
    return None

def _weekday(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return WEEKDAY_ZH[d.weekday()]

def _duration(dep: str, arr: str) -> str:
    try:
        d = datetime.strptime(dep, "%H:%M")
        a = datetime.strptime(arr, "%H:%M")
        diff = (a - d).seconds // 60
        h, m = divmod(diff, 60)
        return f"{h}h {m:02d}m" if h else f"{m}m"
    except Exception: return ""

# ── 時刻列表 Flex (專業簡約風) ──────────────────────────────────────────────────

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
        formation = consist.get("formation", "") if consist else ""
        
        rows.append({
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 4,
                    "contents": [
                        {
                            "type": "text",
                            "text": f"{t['type_name']} {train_no_disp}",
                            "size": "sm",
                            "weight": "bold",
                            "color": "#000000"
                        },
                        {
                            "type": "text",
                            "text": formation or "—",
                            "size": "xs",
                            "color": "#666666"
                        }
                    ]
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 3,
                    "contents": [
                        {
                            "type": "text",
                            "text": f"{t['departure']} → {t['arrival']}",
                            "size": "sm",
                            "align": "end",
                            "weight": "bold",
                            "color": "#1a73e8"
                        },
                        {
                            "type": "text",
                            "text": _duration(t['departure'], t['arrival']),
                            "size": "xs",
                            "align": "end",
                            "color": "#999999"
                        }
                    ]
                }
            ],
            "paddingTop": "10px",
            "paddingBottom": "10px"
        })
        rows.append({"type": "separator", "color": "#f0f0f0"})

    if rows: rows.pop() # 移除最後一個 separator

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#112a4d",
            "contents": [
                {
                    "type": "text",
                    "text": f"{origin_name}  ⇥  {dest_name}",
                    "color": "#ffffff",
                    "weight": "bold",
                    "size": "md"
                },
                {
                    "type": "text",
                    "text": f"{date_short} ({wd})  {page + 1}/{total_pages} 頁",
                    "color": "#a0b4d0",
                    "size": "xs"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": rows or [{"type": "text", "text": "查無資料"}]
        }
    }

# ── 車次詳細 Flex (極精簡專業風：僅起訖站) ───────────────────────────────────────

def build_train_detail_flex(
    train: dict,
    consist: Optional[dict],
    date: str,
    authorized: bool = False,
    image_url: Optional[str] = None,
) -> dict:
    train_no_disp = train["train_no"].lstrip("0") or "0"
    wd = _weekday(date)
    
    # 只取第一站跟最後一站
    stops = train.get("stops", [])
    origin_stop = stops[0] if stops else {"station_name": train.get("start_name", ""), "departure": ""}
    dest_stop = stops[-1] if stops else {"station_name": train.get("end_name", ""), "arrival": ""}

    body_contents = [
        {
            "type": "box",
            "layout": "horizontal",
            "spacing": "xl",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": origin_stop["station_name"], "size": "xl", "weight": "bold", "align": "center"},
                        {"type": "text", "text": origin_stop.get("departure", ""), "size": "sm", "align": "center", "color": "#666666"}
                    ]
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "paddingTop": "10px",
                    "contents": [
                        {"type": "text", "text": "→", "size": "lg", "align": "center", "color": "#1a73e8"}
                    ]
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": dest_stop["station_name"], "size": "xl", "weight": "bold", "align": "center"},
                        {"type": "text", "text": dest_stop.get("arrival", ""), "size": "sm", "align": "center", "color": "#666666"}
                    ]
                }
            ]
        },
        {"type": "separator", "margin": "lg"}
    ]

    if consist:
        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "contents": [
                {"type": "text", "text": "編組運用", "size": "xs", "color": "#888888", "weight": "bold"},
                {"type": "text", "text": consist.get("formation", "—"), "size": "md", "weight": "bold", "color": "#112a4d", "margin": "xs"},
                {"type": "text", "text": f"區間：{consist.get('route', '—')}", "size": "xs", "color": "#444444", "margin": "xs", "wrap": True}
            ]
        })

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#112a4d",
            "contents": [
                {
                    "type": "text",
                    "text": f"{train['type_name']} {train_no_disp}次",
                    "color": "#ffffff",
                    "weight": "bold",
                    "size": "md"
                }
            ]
        },
        "hero": {
            "type": "image",
            "url": image_url or "https://placeholder.com", # 確保有圖或佔位
            "size": "full",
            "aspectRatio": "17:4",
            "aspectMode": "fit"
        } if image_url else None,
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"日期：{date} ({wd})", "size": "xxs", "color": "#aaaaaa", "align": "center"}
            ]
        }
    }

# ── 其餘方法 (Consist/Help) 保持風格一致或維持現狀 ───────────────────────────────

def build_help_text() -> str:
    return (
        "🚂 臺鐵小鋼彈 專業版說明\n"
        "────────────────\n"
        "🕐 時刻查詢\n"
        "  輸入 [起點] [終點] [日期]\n"
        "  例：台北 高雄 明天\n\n"
        "🚞 車次查詢 (精簡版)\n"
        "  直接輸入 [車次]\n"
        "  例：111\n\n"
        "🤖 AI 位置推算 (Gemma 4)\n"
        "  詢問車次目前位置\n"
        "  例：4191現在在哪\n"
        "────────────────"
    )

def build_consist_flex(train_no: str, consist: dict, version_date: str, image_url: Optional[str] = None) -> dict:
    # 這裡維持原本邏輯但微調視覺...
    return {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": f"{train_no} 次編組: {consist.get('formation', '—')}"}]}}
