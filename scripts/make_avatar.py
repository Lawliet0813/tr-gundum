"""
生成台鐵小鋼彈 LINE Bot 2.0 頭像
輸出：linebot/avatar_v2.png（640×640）
"""
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageFont
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ICON_DIR = os.path.join(BASE_DIR, "linebot", "圖案icon")
OUT_PATH = os.path.join(BASE_DIR, "linebot", "avatar_v2.png")

SIZE = 640

# ── 1. 載入素材 ──────────────────────────────────────────
cloud_logo = Image.open(os.path.join(ICON_DIR, "photo_2020-10-27_20-09-04.jpg")).convert("RGBA")
train_raw  = Image.open(os.path.join(ICON_DIR, "train.jpg")).convert("RGBA")

# ── 2. 建立畫布（深色科技感漸層背景） ─────────────────────
canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

# 深藍漸層背景
bg = Image.new("RGBA", (SIZE, SIZE))
draw_bg = ImageDraw.Draw(bg)
for y in range(SIZE):
    t = y / SIZE
    r = int(5  + t * 10)
    g = int(15 + t * 30)
    b = int(40 + t * 60)
    draw_bg.line([(0, y), (SIZE, y)], fill=(r, g, b, 255))
canvas = Image.alpha_composite(canvas, bg)

# ── 3. 貼 EMU900 train 當底部光帶 ─────────────────────────
tw, th = train_raw.size
# 裁掉上方文字，只保留列車車體部分
crop = train_raw.crop((int(tw * 0.08), int(th * 0.42), int(tw * 0.72), int(th * 0.95)))

target_w = SIZE
target_h = int(target_w * crop.height / crop.width)
train_resized = crop.resize((target_w, target_h), Image.LANCZOS)

train_resized = ImageEnhance.Brightness(train_resized).enhance(1.05)
train_resized = ImageEnhance.Contrast(train_resized).enhance(1.15)

# 漸層 mask：上方完全透明 → 下方實
train_alpha = Image.new("L", (target_w, target_h))
draw_ta = ImageDraw.Draw(train_alpha)
for y in range(target_h):
    t = y / target_h
    alpha = int(max(0, t - 0.1) / 0.9 * 210)
    draw_ta.line([(0, y), (target_w, y)], fill=alpha)
train_resized.putalpha(train_alpha)

y_offset = SIZE - target_h + 20
canvas.paste(train_resized, (0, y_offset), train_resized)

# ── 4. 貼雲端＋臺鐵 logo（主視覺，置中偏上） ──────────────
logo_size = int(SIZE * 0.72)
cloud_logo_sq = cloud_logo.resize((logo_size, logo_size), Image.LANCZOS)

# 白色部分轉透明（背景去白）
r, g, b, a = cloud_logo_sq.split()
data = cloud_logo_sq.load()
for y_px in range(logo_size):
    for x_px in range(logo_size):
        pr, pg, pb, pa = data[x_px, y_px]
        if pr > 230 and pg > 230 and pb > 230:
            data[x_px, y_px] = (pr, pg, pb, 0)

# 加一點外發光（白色暈圈）
glow = cloud_logo_sq.filter(ImageFilter.GaussianBlur(10))
glow_enh = ImageEnhance.Brightness(glow)
glow = glow_enh.enhance(1.6)

x_off = (SIZE - logo_size) // 2
y_off = int(SIZE * 0.04)
canvas.paste(glow, (x_off, y_off), glow)
canvas.paste(cloud_logo_sq, (x_off, y_off), cloud_logo_sq)

# ── 5. 綠色速度線（致敬 EMU900 色帶） ────────────────────
draw = ImageDraw.Draw(canvas)
line_y = int(SIZE * 0.75)
# 主線 + 光暈
for dy, alpha, width in [(-4, 80, 2), (-2, 160, 3), (0, 255, 5), (2, 160, 3), (4, 80, 2)]:
    draw.line([(0, line_y + dy), (SIZE, line_y + dy)],
              fill=(60, 210, 100, alpha), width=width)

# 流動光點
for x_pos in range(0, SIZE, SIZE // 10):
    draw.ellipse(
        [x_pos - 5, line_y - 5, x_pos + 5, line_y + 5],
        fill=(160, 255, 170, 200)
    )

# ── 6. 右下角「v2.0」徽章（確保在圓形安全區內） ────────────
# 圓心 (320, 320)，半徑 320
# 45° 方向距圓心 237 → badge 半徑 60 後剛好不超出
badge_r = 64
import math
cx, cy = SIZE // 2, SIZE // 2
dist = cx - badge_r - 18
bx = int(cx + dist * math.sin(math.radians(45)))
by = int(cy + dist * math.cos(math.radians(45)))

# 圓形底板（深藍＋綠框）
draw.ellipse([bx - badge_r, by - badge_r, bx + badge_r, by + badge_r],
             fill=(5, 20, 50, 250))
draw.ellipse([bx - badge_r, by - badge_r, bx + badge_r, by + badge_r],
             outline=(60, 220, 120, 255), width=5)

# 文字
try:
    font_lg = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 36)
    font_sm = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 20)
except Exception:
    font_lg = ImageFont.load_default()
    font_sm = font_lg

# "v2.0"
text = "v2.0"
bbox = draw.textbbox((0, 0), text, font=font_lg)
tw2 = bbox[2] - bbox[0]
th2 = bbox[3] - bbox[1]
draw.text((bx - tw2 // 2, by - th2 // 2 - 2), text,
          font=font_lg, fill=(60, 220, 120, 255))

# ── 7. 裁成圓形（LINE 頭像通常顯示為圓） ─────────────────
mask = Image.new("L", (SIZE, SIZE), 0)
mask_draw = ImageDraw.Draw(mask)
mask_draw.ellipse([0, 0, SIZE, SIZE], fill=255)
output = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
output.paste(canvas, (0, 0), mask)

output.save(OUT_PATH, "PNG")
print(f"✓ 儲存至 {OUT_PATH}")
