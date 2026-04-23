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
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return WEEKDAY_ZH[d.weekday()]
    except: return ""

def _duration(dep: str, arr: str) -> str:
    try:
        d = datetime.strptime(dep, "%H:%M")
        a = datetime.strptime(arr, "%H:%M")
        diff = (a - d).seconds // 60
        h, m = divmod(diff, 60)
        return f"{h}h {m:02d}m" if h else f"{m}m"
    except Exception: return ""

def _info_row(label: str, value: str, wrap: bool = False) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "spacing": "xs",
        "contents": [
            {"type": "text", "text": label, "size": "xs", "color": "#888888"},
            {"type": "text", "text": value or "—", "size": "sm", "color": "#112a4d", "weight": "bold", "wrap": wrap},
        ],
    }

def _crew_route_body(crew_text: str) -> list:
    if not crew_text or crew_text == "—": return [{"type": "text", "text": "—", "size": "sm", "color": "#999999"}]
    segments_raw = [s.strip() for s in crew_text.split("，") if s.strip()]
    contents = []
    for seg_idx, seg_text in enumerate(segments_raw):
        if seg_idx > 0:
            contents.append({"type": "separator", "margin": "sm"})
        if "=" in seg_text:
            parts = [p.strip() for p in seg_text.split("=") if p.strip()]
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    contents.append({
                        "type": "box",
                        "layout": "horizontal",
                        "spacing": "sm",
                        "contents": [
                            {"type": "text", "text": "●", "color": "#1a73e8", "size": "xs", "flex": 0},
                            {"type": "text", "text": part, "size": "sm", "weight": "bold", "color": "#112a4d", "flex": 1},
                        ],
                    })
                else:
                    seg = part.strip("()")
                    contents.append({
                        "type": "box",
                        "layout": "horizontal",
                        "spacing": "sm",
                        "paddingStart": "4px",
                        "contents": [
                            {"type": "text", "text": "│", "color": "#c0c8d8", "size": "xs", "flex": 0},
                            {"type": "text", "text": seg, "size": "xs", "color": "#555577", "flex": 1},
                        ],
                    })
        else:
            contents.append({
                "type": "text",
                "text": seg_text,
                "size": "sm",
                "color": "#112a4d",
                "wrap": True,
            })
    return contents

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
                        {"type": "text", "text": f"{t['type_name']} {train_no_disp}", "size": "sm", "weight": "bold", "color": "#000000"},
                        {"type": "text", "text": formation or "—", "size": "xs", "color": "#666666"}
                    ]
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 3,
                    "contents": [
                        {"type": "text", "text": f"{t['departure']} → {t['arrival']}", "size": "sm", "align": "end", "weight": "bold", "color": "#1a73e8"},
                        {"type": "text", "text": _duration(t['departure'], t['arrival']), "size": "xs", "align": "end", "color": "#999999"}
                    ]
                }
            ],
            "paddingTop": "10px",
            "paddingBottom": "10px"
        })
        rows.append({"type": "separator", "color": "#f0f0f0"})

    if rows: rows.pop()

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#112a4d",
            "contents": [
                {"type": "text", "text": f"{origin_name}  ⇥  {dest_name}", "color": "#ffffff", "weight": "bold", "size": "md"},
                {"type": "text", "text": f"{date_short} ({wd})  {page + 1}/{total_pages} 頁", "color": "#a0b4d0", "size": "xs"}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": rows or [{"type": "text", "text": "查無資料"}]
        }
    }

# ── 車次詳細 Flex (專業電子車票版) ────────────────────────────────────────────────

def build_train_detail_flex(
    train: dict,
    consist: Optional[dict],
    date: str,
    authorized: bool = False,
    image_url: Optional[str] = None,
) -> dict:
    train_no_disp = train["train_no"].lstrip("0") or "0"
    wd = _weekday(date)
    
    stops = train.get("stops", [])
    origin_stop = stops[0] if stops else {"station_name": train.get("start_name", ""), "departure": "—"}
    dest_stop = stops[-1] if stops else {"station_name": train.get("end_name", ""), "arrival": "—"}
    duration = _duration(origin_stop.get("departure", "00:00"), dest_stop.get("arrival", "00:00"))

    # 如果站名太長，稍微縮小字體
    o_name = origin_stop["station_name"]
    d_name = dest_stop["station_name"]
    o_size = "xxl" if len(o_name) <= 3 else "xl"
    d_size = "xxl" if len(d_name) <= 3 else "xl"

    body_contents = [
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 5,
                    "contents": [
                        {"type": "text", "text": o_name, "size": o_size, "weight": "bold", "align": "center", "color": "#112a4d"},
                        {"type": "text", "text": origin_stop.get("departure", ""), "size": "md", "align": "center", "color": "#666666", "weight": "bold"}
                    ]
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 2,
                    "paddingTop": "15px",
                    "contents": [
                        {"type": "text", "text": "▶", "size": "md", "align": "center", "color": "#1a73e8"},
                        {"type": "text", "text": duration, "size": "xxs", "align": "center", "color": "#aaaaaa"}
                    ]
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 5,
                    "contents": [
                        {"type": "text", "text": d_name, "size": d_size, "weight": "bold", "align": "center", "color": "#112a4d"},
                        {"type": "text", "text": dest_stop.get("arrival", ""), "size": "md", "align": "center", "color": "#666666", "weight": "bold"}
                    ]
                }
            ]
        },
        {"type": "separator", "margin": "lg"}
    ]

    if consist:
        # 基礎編組資訊
        info_box = {
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "contents": [
                {"type": "text", "text": "車型與編組", "size": "xs", "color": "#888888", "weight": "bold"},
                {"type": "text", "text": f"{train.get('type_name')} {consist.get('formation', '—')}", "size": "sm", "weight": "bold", "color": "#112a4d", "margin": "xs"},
                {"type": "text", "text": f"營運區間：{consist.get('route', '—')}", "size": "xs", "color": "#444444", "margin": "xs", "wrap": True}
            ]
        }
        body_contents.append(info_box)

        # 授權用戶專屬：顯示乘務資訊
        if authorized:
            body_contents.append({"type": "separator", "margin": "md"})
            body_contents.append({
                "type": "box",
                "layout": "vertical",
                "margin": "md",
                "contents": [
                    {"type": "text", "text": "機務乘務（司機員）", "size": "xs", "color": "#888888"},
                    {"type": "box", "layout": "vertical", "margin": "xs", "contents": _crew_route_body(consist.get("crew_mech", ""))},
                    {"type": "text", "text": "運務乘務（車長）", "size": "xs", "color": "#888888", "margin": "md"},
                    {"type": "box", "layout": "vertical", "margin": "xs", "contents": _crew_route_body(consist.get("crew_ops", ""))}
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
                {"type": "text", "text": f"{train['type_name']} {train_no_disp}次", "color": "#ffffff", "weight": "bold", "size": "md"}
            ]
        },
        "hero": {
            "type": "image",
            "url": image_url,
            "size": "full",
            "aspectRatio": "20:7",
            "aspectMode": "cover"
        } if image_url else None,
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "15px",
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

def build_consist_flex(
    train_no: str,
    consist: dict,
    version_date: str,
    image_url: Optional[str] = None,
) -> dict:
    type_name = consist.get("type_name", "—")
    info_items = [
        {"type": "text", "text": f"{train_no} 次", "weight": "bold", "size": "md", "color": "#112a4d"},
        {"type": "text", "text": type_name, "size": "xs", "color": "#555577", "wrap": True},
        {"type": "separator", "margin": "sm"},
        _info_row("編組", consist.get("formation", "—")),
        _info_row("區間", consist.get("route", "—"), wrap=True),
        {"type": "separator", "margin": "sm"},
        {"type": "text", "text": "機務乘務", "size": "xs", "color": "#888888"},
        {"type": "box", "layout": "vertical", "contents": _crew_route_body(consist.get("crew_mech", ""))},
        {"type": "separator", "margin": "sm"},
        {"type": "text", "text": "運務乘務", "size": "xs", "color": "#888888"},
        {"type": "box", "layout": "vertical", "contents": _crew_route_body(consist.get("crew_ops", ""))},
        {"type": "text", "text": version_date, "size": "xxs", "color": "#aaaaaa", "margin": "sm"},
    ]
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "contents": info_items
        },
        "hero": {
            "type": "image",
            "url": image_url,
            "size": "full",
            "aspectRatio": "20:7",
            "aspectMode": "cover"
        } if image_url else None
    }

def build_crew_route_flex(
    train_no: str,
    type_name: str,
    crew_type: str,
    crew_text: str,
    version_date: str,
) -> dict:
    label = "機務乘務" if crew_type == "mech" else "運務乘務"
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#112a4d",
            "contents": [
                {"type": "text", "text": f"{train_no} 次 {type_name}", "color": "#ffffff", "weight": "bold", "size": "md"},
                {"type": "text", "text": label, "color": "#b0bec5", "size": "xs"}
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "contents": _crew_route_body(crew_text),
        },
    }

def build_help_text() -> str:
    return (
        "🚂 臺鐵小鋼彈 專業版說明\n"
        "────────────────\n"
        "🕐 時刻查詢\n"
        "  輸入 [起點] [終點] [日期]\n\n"
        "🚞 車次查詢\n"
        "  直接輸入 [車次]\n\n"
        "🤖 AI 位置推算 (Gemma 4)\n"
        "  例：4191現在在哪\n"
        "────────────────"
    )
