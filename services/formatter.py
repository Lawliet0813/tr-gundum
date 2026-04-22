"""Build LINE Flex Messages for train schedule query results."""

from datetime import datetime
from typing import Optional

PAGE_SIZE = 10
WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]

# type_name keyword → image filename（順序優先：越具體越前）
_TYPE_IMAGE_MAP = [
    ("普悠瑪",      "TEMU1000.png"),
    ("太魯閣",      "TEMU2000.png"),
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
    """Return absolute image URL for a train type, or None if no match."""
    if not base_url:
        return None
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
    authorized: bool = False,
    image_url: Optional[str] = None,
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

    if authorized and consist:
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
        if consist.get("crew_mech"):
            header_contents.append({
                "type": "text",
                "text": f"機務：{consist['crew_mech']}",
                "color": "#b0bec5",
                "size": "xxs",
                "wrap": True,
            })
        if consist.get("crew_ops"):
            header_contents.append({
                "type": "text",
                "text": f"運務：{consist['crew_ops']}",
                "color": "#b0bec5",
                "size": "xxs",
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

    bubble: dict = {
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

    if image_url:
        bubble["hero"] = {
            "type": "image",
            "url": image_url,
            "size": "full",
            "aspectRatio": "17:4",
            "aspectMode": "fit",
            "backgroundColor": "#f0f4f8",
        }

    return bubble


# ── 編組詳細 Flex（純編組查詢，無需 TDX）─────────────────────────────────────

def build_consist_flex(
    train_no: str,
    consist: dict,
    version_date: str,
    image_url: Optional[str] = None,
) -> dict:
    """橫向卡片：左圖右文（有圖時），或純直向資訊（無圖時）。"""
    type_name = consist.get("type_name", "—")

    def _crew_section(label: str, crew_text: str) -> list:
        items = [
            {"type": "text", "text": label, "size": "xs", "color": "#888888", "margin": "sm"},
        ]
        items.extend(_crew_route_body(crew_text or "—"))
        return items

    info_items = [
        {"type": "text", "text": f"{train_no} 次", "weight": "bold",
         "size": "md", "color": "#1a1a2e"},
        {"type": "text", "text": type_name, "size": "xs",
         "color": "#555577", "wrap": True},
        {"type": "separator", "margin": "sm"},
        _info_row("編組", consist.get("formation", "—")),
        _info_row("區間", consist.get("route", "—"), wrap=True),
        {"type": "separator", "margin": "sm"},
        *_crew_section("機務乘務（司機員）", consist.get("crew_mech", "")),
        {"type": "separator", "margin": "sm"},
        *_crew_section("運務乘務（車長）", consist.get("crew_ops", "")),
        {"type": "text", "text": version_date,
         "size": "xxs", "color": "#aaaaaa", "margin": "sm"},
    ]

    if image_url:
        return {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "0px",
                "contents": [
                    {
                        "type": "image",
                        "url": image_url,
                        "size": "full",
                        "aspectRatio": "17:4",
                        "aspectMode": "fit",
                        "backgroundColor": "#f0f4f8",
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "paddingAll": "12px",
                        "spacing": "xs",
                        "contents": info_items,
                    },
                ],
            },
        }

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#37474f",
            "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": f"{train_no} 次　編組運用",
                 "color": "#ffffff", "weight": "bold", "size": "md"},
                {"type": "text", "text": f"資料日期：{version_date}",
                 "color": "#b0bec5", "size": "xs"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "12px",
            "contents": [
                _info_row("車型",     type_name),
                _info_row("編組",     consist.get("formation", "—")),
                _info_row("區間",     consist.get("route", "—")),
                _info_row("機務乘務", consist.get("crew_mech", "—"), wrap=True),
                _info_row("運務乘務", consist.get("crew_ops", "—"), wrap=True),
            ],
        },
    }


def _crew_route_body(crew_text: str) -> list:
    """將 '臺北=(花H20)=花蓮=...' 轉為 Flex body contents（時刻線格式）。"""
    # 複合格式（含逗號），分段顯示
    segments_raw = [s.strip() for s in crew_text.split("，") if s.strip()]
    contents = []
    for seg_idx, seg_text in enumerate(segments_raw):
        if seg_idx > 0:
            contents.append({"type": "separator", "margin": "sm"})
        if "=" in seg_text:
            parts = [p.strip() for p in seg_text.split("=") if p.strip()]
            for i, part in enumerate(parts):
                if i % 2 == 0:  # 站名
                    contents.append({
                        "type": "box",
                        "layout": "horizontal",
                        "spacing": "sm",
                        "contents": [
                            {"type": "text", "text": "●", "color": "#1a73e8",
                             "size": "xs", "flex": 0},
                            {"type": "text", "text": part, "size": "sm",
                             "weight": "bold", "color": "#1a1a2e", "flex": 1},
                        ],
                    })
                else:  # 段次代號
                    seg = part.strip("()")
                    contents.append({
                        "type": "box",
                        "layout": "horizontal",
                        "spacing": "sm",
                        "paddingStart": "4px",
                        "contents": [
                            {"type": "text", "text": "│", "color": "#c0c8d8",
                             "size": "xs", "flex": 0},
                            {"type": "text", "text": seg, "size": "xs",
                             "color": "#555577", "flex": 1},
                        ],
                    })
        else:
            contents.append({
                "type": "text",
                "text": seg_text,
                "size": "sm",
                "color": "#1a1a2e",
                "wrap": True,
            })
    return contents


def build_crew_route_flex(
    train_no: str,
    type_name: str,
    crew_type: str,
    crew_text: str,
    version_date: str,
) -> dict:
    label = "機務乘務（司機員）" if crew_type == "mech" else "運務乘務（車長）"
    header_text = f"{train_no} 次　{type_name}" if type_name else f"{train_no} 次"

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1a3a6b",
            "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": header_text, "color": "#ffffff",
                 "weight": "bold", "size": "md"},
                {"type": "text", "text": label, "color": "#b0bec5", "size": "xs"},
                {"type": "text", "text": f"資料日期：{version_date}",
                 "color": "#7090b0", "size": "xxs"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "xs",
            "paddingAll": "12px",
            "contents": _crew_route_body(crew_text),
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
