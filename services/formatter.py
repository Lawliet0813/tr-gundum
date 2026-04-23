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

# ── 車次詳細 Flex (時刻整合版) ───────────────────────────────────────────────────

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
    origin_name = train.get("start_name", "")
    dest_name = train.get("end_name", "")
    
    # 建立時刻表區塊
    stop_rows = []
    for i, s in enumerate(stops):
        is_first = (i == 0)
        is_last = (i == len(stops) - 1)
        dot_color = "#1a73e8" if (is_first or is_last) else "#cccccc"
        text_color = "#112a4d" if (is_first or is_last) else "#666666"
        weight = "bold" if (is_first or is_last) else "regular"

        stop_rows.append({
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 0,
                    "contents": [
                        {"type": "text", "text": "●", "size": "xxs", "color": dot_color, "align": "center"}
                    ],
                    "paddingTop": "2px"
                },
                {"type": "text", "text": s["station_name"], "size": "xs", "color": text_color, "weight": weight, "flex": 4},
                {"type": "text", "text": s["arrival"] or s["departure"], "size": "xs", "color": text_color, "weight": weight, "align": "end", "flex": 2}
            ]
        })

    body_contents = [
        # 頂部票頭
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 5,
                    "contents": [
                        {"type": "text", "text": origin_name, "size": "xl", "weight": "bold", "align": "center", "color": "#112a4d"},
                        {"type": "text", "text": stops[0]["departure"] if stops else "", "size": "sm", "align": "center", "color": "#666666"}
                    ]
                },
                {"type": "box", "layout": "vertical", "flex": 2, "paddingTop": "10px", "contents": [{"type": "text", "text": "▶", "size": "sm", "align": "center", "color": "#1a73e8"}]},
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 5,
                    "contents": [
                        {"type": "text", "text": dest_name, "size": "xl", "weight": "bold", "align": "center", "color": "#112a4d"},
                        {"type": "text", "text": stops[-1]["arrival"] if stops else "", "size": "sm", "align": "center", "color": "#666666"}
                    ]
                }
            ]
        },
        {"type": "separator", "margin": "lg"},
        
        # 時刻表區域
        {
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "spacing": "sm",
            "backgroundColor": "#f8f9fa",
            "paddingAll": "10px",
            "cornerRadius": "md",
            "contents": [
                {"type": "text", "text": "停靠站時刻表", "size": "xxs", "color": "#999999", "margin": "none"}
            ] + stop_rows
        }
    ]

    if consist:
        # 編組資訊
        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "contents": [
                {"type": "text", "text": "車型與編組", "size": "xs", "color": "#888888", "weight": "bold"},
                {"type": "text", "text": f"{train.get('type_name')} {consist.get('formation', '—')}", "size": "sm", "weight": "bold", "color": "#112a4d", "margin": "xs"},
                {"type": "text", "text": f"營運區間：{consist.get('route', '—')}", "size": "xs", "color": "#444444", "margin": "xs", "wrap": True}
            ]
        })

        if authorized:
            body_contents.append({"type": "separator", "margin": "md"})
            body_contents.append({
                "type": "box",
                "layout": "vertical",
                "margin": "md",
                "contents": [
                    {"type": "text", "text": "機務/運務乘務", "size": "xs", "color": "#888888"},
                    {"type": "box", "layout": "vertical", "margin": "xs", "contents": _crew_route_body(consist.get("crew_mech", "") + " / " + consist.get("crew_ops", ""))}
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

def build_consist_flex(train_no: str, consist: dict, version_date: str, image_url: Optional[str] = None) -> dict:
    type_name = consist.get("type_name", "—")
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": f"{train_no} 次", "weight": "bold", "size": "md", "color": "#112a4d"},
                _info_row("編組", consist.get("formation", "—")),
                _info_row("區間", consist.get("route", "—"), wrap=True)
            ]
        },
        "hero": {"type": "image", "url": image_url, "size": "full", "aspectRatio": "20:7", "aspectMode": "cover"} if image_url else None
    }

def build_crew_route_flex(train_no: str, type_name: str, crew_type: str, crew_text: str, version_date: str) -> dict:
    return {
        "type": "bubble",
        "header": {"type": "box", "layout": "vertical", "backgroundColor": "#112a4d", "contents": [{"type": "text", "text": f"{train_no} 次 {type_name}", "color": "#ffffff"}]},
        "body": {"type": "box", "layout": "vertical", "contents": _crew_route_body(crew_text)}
    }

def build_help_text() -> str:
    return "🚂 臺鐵小鋼彈 專業版\n─\n🕐 起站 終站 (例: 台北 高雄)\n🚞 車次 (例: 111)\n🤖 詢問位置 (例: 111現在在哪)"
