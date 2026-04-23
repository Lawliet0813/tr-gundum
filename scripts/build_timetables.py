"""從 data/timetables/*.ods 重新產生 data/full_timetables.json + data/train_list.json。

ODS 來源：臺鐵全球資訊網 「各級列車時刻表 (.ods)」
  https://www.railway.gov.tw/tra-tip-web/tip/tip00C/tipC21/view?proCode=8ae4cac3756b7b41017572e9077f1790&subCode=8ae4cac3756b7b41017573e352ae18f8
更新版本時，重新下載該頁所有 ODS 到 data/timetables/ 後執行本腳本。

正確處理：
- table:number-columns-repeated（設上限避免 ODS 尾部 16000+ 空欄爆炸）
- covered-table-cell（由 rows/cols-spanned 造成，必須計入欄索引）
- cell 文字收集包含 text:p 下所有 child 的 text + tail（不漏 <text:s/>）
- 兩種版面：對號快車（車次橫排）、區間車（車次縱排，站名在 r1+r2 兩列拼接）

輸出：
- data/full_timetables.json  = { "<train_no>": {"no", "type", "stops": [{"s", "t"}, ...]}, ... }
- data/train_list.json        = [ {"train_no", "type", "origin", "destination", "route", "source_file"}, ... ]
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

ROOT = Path(__file__).parent.parent
TT_DIR = ROOT / "data" / "timetables"
OUT_TIMETABLES = ROOT / "data" / "full_timetables.json"
OUT_TRAIN_LIST = ROOT / "data" / "train_list.json"

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
T_NS = NS["table"]
TE_NS = NS["text"]

MAX_COLS = 128

TIME_RE = re.compile(r"^(\d{1,2}):?(\d{2})$")


def tag(e: ET.Element) -> str:
    return e.tag.split("}", 1)[1] if "}" in e.tag else e.tag


def cell_text(cell: ET.Element) -> str:
    """收集一個 <table-cell> 裡所有可見文字，包含 <text:p> 下 child 的 tail。"""
    out: list[str] = []
    for p in cell.findall(f"{{{TE_NS}}}p"):
        buf: list[str] = []
        if p.text:
            buf.append(p.text)
        for child in p.iter():
            if child is p:
                continue
            if tag(child) == "s":
                # <text:s text:c="3"/>：3 個空白
                c = child.get(f"{{{TE_NS}}}c") or "1"
                try:
                    buf.append(" " * int(c))
                except ValueError:
                    buf.append(" ")
            elif tag(child) == "tab":
                buf.append("\t")
            else:
                if child.text:
                    buf.append(child.text)
            if child.tail:
                buf.append(child.tail)
        out.append("".join(buf).strip())
    return "\n".join(s for s in out if s)


def expand_row(row: ET.Element) -> list[dict]:
    """把一列展開成 physical cells 陣列。covered-table-cell 也計入（文字為空）。

    每個 cell dict: {"text": str, "covered": bool}
    會在達到 MAX_COLS 或尾端都是空 cell 時截斷。
    """
    cells: list[dict] = []
    for child in row:
        t = tag(child)
        if t not in ("table-cell", "covered-table-cell"):
            continue
        rep = int(child.get(f"{{{T_NS}}}number-columns-repeated") or "1")
        # 一個 ODS 列常常在最後補 16000+ 空 cell，需截斷
        if len(cells) >= MAX_COLS:
            break
        rep = min(rep, MAX_COLS - len(cells))

        text = cell_text(child) if t == "table-cell" else ""
        covered = t == "covered-table-cell"
        entry = {"text": text, "covered": covered}
        for _ in range(rep):
            cells.append(entry)
            if len(cells) >= MAX_COLS:
                break
    # 去掉尾端連續空 cell
    while cells and not cells[-1]["text"] and cells[-1]["covered"] is False:
        cells.pop()
    return cells


def iter_tables(ods_path: Path) -> Iterator[ET.Element]:
    with zipfile.ZipFile(ods_path) as zf:
        with zf.open("content.xml") as f:
            root = ET.parse(f).getroot()
    for tbl in root.iter(f"{{{T_NS}}}table"):
        yield tbl


def build_grid(table: ET.Element) -> list[list[str]]:
    """把 table 轉成 grid[row][col] = text。對 spanC 不做複製（covered cell 文字本來就空）。"""
    grid: list[list[str]] = []
    for row in table.findall(f"{{{T_NS}}}table-row"):
        rep = int(row.get(f"{{{T_NS}}}number-rows-repeated") or "1")
        rep = min(rep, 2)  # 時刻表列基本不會 repeat；防呆上限
        expanded = expand_row(row)
        texts = [c["text"] for c in expanded]
        for _ in range(rep):
            grid.append(texts)
    return grid


def parse_time(raw: str) -> str | None:
    """'05:30' / '0530' / '5:30' → 'HH:MM'，非時刻回 None。備註（↓、∥、│ 等）不是時刻。"""
    s = raw.strip()
    if not s:
        return None
    m = TIME_RE.match(s)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if not (0 <= hh <= 29 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


def find_header_rows(grid: list[list[str]], max_cols: int) -> dict:
    """回傳 {"train_no_row", "type_row", "origin_row", "dest_row", "arrow_row"} 的列索引。

    策略：掃前 20 列，找：
    - train_no_row：該列有 >=3 格是純數字 3-5 位 → 車次
    - type_row：在 train_no_row 之上，內容含 '自強'|'莒光'|'區間'|'普悠瑪'|'太魯閣'
    - origin_row / dest_row：箭頭 ↓ 所在列的上/下一列
    """
    train_no_row = None
    type_row = None
    arrow_row = None

    def row_stats(r: int) -> tuple[int, int]:
        """回傳 (數字 cell 數, 2-3 位數字 cell 數)"""
        row = grid[r]
        nums = sum(1 for v in row[:max_cols] if v.isdigit())
        short = sum(1 for v in row[:max_cols] if v.isdigit() and 2 <= len(v) <= 5)
        return nums, short

    for r in range(min(len(grid), 20)):
        row = grid[r]
        arrows = sum(1 for v in row[:max_cols] if v.strip() in ("↓", "↑"))
        if arrows >= 3:
            arrow_row = r
            break

    for r in range(min(len(grid), 20)):
        _, short = row_stats(r)
        if short >= 3:
            train_no_row = r
            break

    if train_no_row is not None:
        for r in range(max(0, train_no_row - 3), train_no_row):
            row = grid[r]
            type_hits = sum(
                1 for v in row[:max_cols]
                if any(k in v for k in ("自強", "莒光", "區間", "普悠瑪", "太魯閣", "復興"))
            )
            if type_hits >= 2:
                type_row = r
                break

    origin_row = arrow_row - 1 if arrow_row is not None else None
    dest_row = arrow_row + 1 if arrow_row is not None else None

    return {
        "train_no_row": train_no_row,
        "type_row": type_row,
        "arrow_row": arrow_row,
        "origin_row": origin_row,
        "dest_row": dest_row,
    }


def find_station_rows(grid: list[list[str]], header_end: int) -> list[int]:
    """從 header_end 之後掃，找「該列 col0 有 1-3 個中文字且右側有 >=2 個時刻」的列。"""
    rows: list[int] = []
    for r in range(header_end + 1, len(grid)):
        row = grid[r]
        if not row:
            continue
        station = row[0].strip() if len(row) > 0 else ""
        if not station or len(station) > 4:
            continue
        # 必須含中文字
        if not re.search(r"[一-鿿]", station):
            continue
        # 右側至少 2 個是時刻
        time_count = sum(1 for v in row[1:] if parse_time(v))
        if time_count >= 2:
            rows.append(r)
    return rows


def _strip_noise(s: str) -> str:
    """站名正規化：去換行、全/半形空白、括號標注（但保留路線分隔符 － — －）。"""
    s = s.replace("\n", "").replace("　", "")
    s = re.sub(r"[（(].*?[)）]", "", s)
    s = re.sub(r"\s+", "", s)
    return s


def parse_layout_a(grid: list[list[str]]) -> list[dict]:
    """車次橫排（對號快車常見）：車次在某一列、站名在 col 0。"""
    max_cols = max((len(r) for r in grid), default=0)
    if max_cols == 0:
        return []

    hdr = find_header_rows(grid, max_cols)
    train_no_row = hdr["train_no_row"]
    if train_no_row is None:
        return []

    type_row = hdr["type_row"]
    origin_row = hdr["origin_row"]
    dest_row = hdr["dest_row"]

    header_end = max(r for r in [train_no_row, type_row, origin_row, dest_row] if r is not None)
    stn_rows = find_station_rows(grid, header_end)
    if not stn_rows:
        return []

    trains: list[dict] = []
    train_no_line = grid[train_no_row]
    for c in range(max_cols):
        if c >= len(train_no_line):
            break
        no = train_no_line[c].strip()
        if not no.isdigit() or not (2 <= len(no) <= 5):
            continue

        t_type = (grid[type_row][c] if type_row is not None and c < len(grid[type_row]) else "").strip()
        origin = _strip_noise(grid[origin_row][c]) if origin_row is not None and c < len(grid[origin_row]) else ""
        dest = _strip_noise(grid[dest_row][c]) if dest_row is not None and c < len(grid[dest_row]) else ""

        stops: list[dict] = []
        for sr in stn_rows:
            row = grid[sr]
            if c >= len(row):
                continue
            t = parse_time(row[c].strip())
            if not t:
                continue
            station = _strip_noise(row[0])
            if station:
                stops.append({"s": station, "t": t})

        if len(stops) < 2:
            continue

        trains.append({
            "train_no": no,
            "type": t_type,
            "origin": origin,
            "destination": dest,
            "stops": stops,
        })

    return trains


_ROUTE_SEP_RE = re.compile(r"[－—─\-~～]")


def parse_layout_b(grid: list[list[str]]) -> list[dict]:
    """車次縱排（區間車常見）：每列一個車次；站名在 r1+r2 兩列拼接。

    欄位慣例：col 0 = 車種、col 2 = 車次、col 3 = 山/海（可無）、col 4 = 路線、col 5+ = 每欄一站。
    """
    if len(grid) < 5:
        return []
    max_cols = max((len(r) for r in grid), default=0)
    if max_cols < 8:
        return []

    # 偵測：col 2 有 ≥ 3 列是純數字
    col2 = [grid[r][2].strip() if len(grid[r]) > 2 else "" for r in range(len(grid))]
    digit_hits = sum(1 for v in col2 if v.isdigit() and 2 <= len(v) <= 5)
    if digit_hits < 3:
        return []

    # 找站名起始 col：在站名列嘗試由右往左推測，但簡化：預設 col 5
    stn_start = 5
    # 某些表 col 3 有「山/海」，col 4 是路線；route 含 '－' 即可確認
    # 但不影響 stn_start

    # 合併 r1 + r2 作為站名
    def station_at(col: int) -> str:
        parts: list[str] = []
        for r in (1, 2):
            if r < len(grid) and col < len(grid[r]):
                v = grid[r][col].replace("　", "").strip()
                if v:
                    parts.append(v)
        name = _strip_noise("".join(parts))
        return name

    station_names: dict[int, str] = {}
    for c in range(stn_start, max_cols):
        name = station_at(c)
        if name and re.search(r"[一-鿿]", name):
            station_names[c] = name

    if len(station_names) < 3:
        return []

    trains: list[dict] = []
    for r in range(3, len(grid)):
        row = grid[r]
        if len(row) <= 4:
            continue
        no = row[2].strip() if len(row) > 2 else ""
        if not (no.isdigit() and 2 <= len(no) <= 5):
            continue
        t_type = row[0].strip()
        route = row[4].strip() if len(row) > 4 else ""

        origin = dest = ""
        if route:
            parts = _ROUTE_SEP_RE.split(route, maxsplit=1)
            if len(parts) == 2:
                origin, dest = _strip_noise(parts[0]), _strip_noise(parts[1])

        stops: list[dict] = []
        for c in sorted(station_names.keys()):
            if c >= len(row):
                continue
            t = parse_time(row[c].strip())
            if not t:
                continue
            stops.append({"s": station_names[c], "t": t})

        if len(stops) < 2:
            continue

        trains.append({
            "train_no": no,
            "type": t_type,
            "origin": origin,
            "destination": dest,
            "stops": stops,
        })

    return trains


def parse_one_ods(ods_path: Path) -> list[dict]:
    """先試對號快車版面（layout A），若取不到車次再試區間車版面（layout B）。"""
    all_trains: list[dict] = []
    for table in iter_tables(ods_path):
        grid = build_grid(table)
        if not grid:
            continue
        trains = parse_layout_a(grid)
        if not trains:
            trains = parse_layout_b(grid)
        all_trains.extend(trains)
    return all_trains


def merge_train_stops(accum: dict, new_list: list[dict], source_file: str, train_meta: dict) -> None:
    """把一個檔的車次併入 accum。

    stops：以 len 最多者為準。
    meta：優先採 origin/destination 有值的那份；若都有值或都沒，再比 stops 數。
    """
    for tr in new_list:
        no = tr["train_no"].lstrip("0")
        existing = accum.get(no)
        if existing is None or len(tr["stops"]) > len(existing["stops"]):
            accum[no] = {"no": tr["train_no"], "type": tr["type"], "stops": tr["stops"]}

        m = train_meta.get(no)
        new_has_od = bool(tr["origin"] and tr["destination"])
        old_has_od = bool(m and m.get("origin") and m.get("destination"))
        new_stops_n = len(tr["stops"])

        take = False
        if m is None:
            take = True
        elif new_has_od and not old_has_od:
            take = True
        elif new_has_od == old_has_od and new_stops_n > m["_stop_count"]:
            take = True

        if take:
            train_meta[no] = {
                "train_no": tr["train_no"],
                "type": tr["type"],
                "origin": tr["origin"],
                "destination": tr["destination"],
                "route": f"{tr['origin']}－{tr['destination']}" if tr["origin"] and tr["destination"] else "",
                "source_file": source_file,
                "_stop_count": new_stops_n,
            }


def main() -> int:
    files = sorted(TT_DIR.glob("*.ods"))
    if not files:
        print(f"no .ods files in {TT_DIR}", file=sys.stderr)
        return 1

    full: dict = {}
    meta: dict = {}
    for f in files:
        trains = parse_one_ods(f)
        merge_train_stops(full, trains, f.name, meta)
        print(f"  {f.name}: {len(trains)} trains")

    # train_list 拿掉內部 _stop_count
    train_list = []
    for no in sorted(meta.keys(), key=lambda x: int(x)):
        m = dict(meta[no])
        m.pop("_stop_count", None)
        train_list.append(m)

    OUT_TIMETABLES.write_text(
        json.dumps(full, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    OUT_TRAIN_LIST.write_text(
        json.dumps(train_list, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"full_timetables.json: {len(full)} trains")
    print(f"train_list.json:      {len(train_list)} trains")

    # sanity
    long_haul_ok = [no for no in ("105", "109", "111", "117") if no in full and len(full[no]["stops"]) >= 15]
    print(f"長程抽查（≥15 stops）: {long_haul_ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
