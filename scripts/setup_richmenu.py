"""
一次性圖文選單設定腳本。

執行後會：
1. 生成兩張選單圖片（一般用戶 3 鈕 / 授權員工 4 鈕）
2. 上傳至 LINE，取得 richMenuId
3. 將一般選單設為預設
4. 印出兩組 ID → 存入 Railway 環境變數

用法：
    python scripts/setup_richmenu.py
    （需先在環境變數設定 LINE_CHANNEL_ACCESS_TOKEN）
"""

import os
import sys
import json
import httpx
from pathlib import Path

# ── 圖片生成 ───────────────────────────────────────────────────────────────────

W, H = 2500, 843  # LINE compact 尺寸
BG   = "#1a3a6b"  # 深藍背景
TEXT = "#ffffff"  # 白色文字
SEP  = "#3d6090"  # 分隔線


def _hex(color: str) -> tuple:
    c = color.lstrip("#")
    return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))


def _draw_menu(path: Path, labels: list[str]) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (W, H), _hex(BG))
    draw = ImageDraw.Draw(img)
    n = len(labels)

    # 分欄（若 4 鈕改為 2×2）
    if n <= 3:
        cols, rows = n, 1
    else:
        cols, rows = 2, 2

    cell_w = W // cols
    cell_h = H // rows

    # 嘗試載入支援中文的字型
    font = None
    font_candidates = [
        "/System/Library/Fonts/PingFang.ttc",                         # macOS (newer)
        "/System/Library/Fonts/STHeiti Medium.ttc",                   # macOS (fallback)
        "/System/Library/Fonts/Hiragino Sans GB.ttc",                 # macOS
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",    # Linux
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJKtc-Regular.otf",
    ]
    for fp in font_candidates:
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, size=120)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    for i, label in enumerate(labels):
        col = i % cols
        row = i // cols
        x0 = col * cell_w
        y0 = row * cell_h
        x1 = x0 + cell_w
        y1 = y0 + cell_h

        # 分隔線
        if col > 0:
            draw.line([(x0, y0 + 20), (x0, y1 - 20)], fill=_hex(SEP), width=4)
        if row > 0:
            draw.line([(x0 + 20, y0), (x1 - 20, y0)], fill=_hex(SEP), width=4)

        # 文字置中
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = x0 + (cell_w - tw) // 2
        ty = y0 + (cell_h - th) // 2
        draw.text((tx, ty), label, fill=_hex(TEXT), font=font)

    img.save(path, "PNG")
    print(f"  生成：{path}")


# ── LINE API 呼叫 ──────────────────────────────────────────────────────────────

BASE = "https://api.line.me/v2/bot"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_menu(token: str, body: dict) -> str:
    r = httpx.post(f"{BASE}/richmenu", headers=_headers(token), json=body, timeout=20)
    r.raise_for_status()
    return r.json()["richMenuId"]


def _upload_image(token: str, menu_id: str, image_path: Path) -> None:
    with open(image_path, "rb") as f:
        r = httpx.post(
            f"https://api-data.line.me/v2/bot/richmenu/{menu_id}/content",
            headers={**_headers(token), "Content-Type": "image/png"},
            content=f.read(),
            timeout=30,
        )
    r.raise_for_status()


def _set_default(token: str, menu_id: str) -> None:
    r = httpx.post(
        f"{BASE}/user/all/richmenu/{menu_id}",
        headers=_headers(token),
        timeout=20,
    )
    r.raise_for_status()


# ── 選單定義 ───────────────────────────────────────────────────────────────────

def _menu_body_general(liff_id: str) -> dict:
    """一般用戶：上排 2 鈕 + 下排 2 鈕（含 LIFF 邀請碼）"""
    hw = W // 2
    hh = H // 2
    liff_uri = f"https://liff.line.me/{liff_id}" if liff_id else "https://line.me"
    return {
        "size": {"width": W, "height": H},
        "selected": True,
        "name": "general",
        "chatBarText": "功能選單",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": hw, "height": hh},
                "action": {"type": "message", "label": "查時刻", "text": "查時刻"},
            },
            {
                "bounds": {"x": hw, "y": 0, "width": hw, "height": hh},
                "action": {"type": "message", "label": "查車次", "text": "查車次"},
            },
            {
                "bounds": {"x": 0, "y": hh, "width": hw, "height": hh},
                "action": {"type": "message", "label": "使用說明", "text": "幫助"},
            },
            {
                "bounds": {"x": hw, "y": hh, "width": hw, "height": hh},
                "action": {"type": "uri", "label": "輸入邀請碼", "uri": liff_uri},
            },
        ],
    }


def _menu_body_4btn() -> dict:
    """授權員工：4 鈕 2×2"""
    hw = W // 2
    hh = H // 2
    return {
        "size": {"width": W, "height": H},
        "selected": True,
        "name": "authorized",
        "chatBarText": "功能選單",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": hw, "height": hh},
                "action": {"type": "message", "label": "查時刻", "text": "查時刻"},
            },
            {
                "bounds": {"x": hw, "y": 0, "width": hw, "height": hh},
                "action": {"type": "message", "label": "查車次", "text": "查車次"},
            },
            {
                "bounds": {"x": 0, "y": hh, "width": hw, "height": hh},
                "action": {"type": "message", "label": "查編組", "text": "查編組"},
            },
            {
                "bounds": {"x": hw, "y": hh, "width": hw, "height": hh},
                "action": {"type": "message", "label": "使用說明", "text": "幫助"},
            },
        ],
    }


# ── 主程式 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        print("❌ 請設定環境變數 LINE_CHANNEL_ACCESS_TOKEN", file=sys.stderr)
        sys.exit(1)

    liff_id = os.getenv("LIFF_ID", "")
    if not liff_id:
        print("⚠️  未設定 LIFF_ID，邀請碼按鈕將指向 line.me（建議先建立 LIFF App）")

    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)

    img_general    = data_dir / "richmenu_general.png"
    img_authorized = data_dir / "richmenu_authorized.png"

    print("📐 生成圖文選單圖片…")
    _draw_menu(img_general,    ["查時刻", "查車次", "使用說明", "輸入邀請碼"])
    _draw_menu(img_authorized, ["查時刻", "查車次", "查編組", "使用說明"])

    print("\n📤 上傳至 LINE…")
    gid = _create_menu(token, _menu_body_general(liff_id))
    _upload_image(token, gid, img_general)
    print(f"  一般用戶選單 ID：{gid}")

    aid = _create_menu(token, _menu_body_4btn())
    _upload_image(token, aid, img_authorized)
    print(f"  授權員工選單 ID：{aid}")

    print("\n🔧 設定預設選單（一般用戶）…")
    _set_default(token, gid)

    print("\n✅ 完成！請將以下設定存入 Railway 環境變數：\n")
    print(f"  RICHMENU_GENERAL_ID={gid}")
    print(f"  RICHMENU_AUTHORIZED_ID={aid}")
    print()


if __name__ == "__main__":
    main()
