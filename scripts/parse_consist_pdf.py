"""從「114年12月23日時刻微調客車編組運用表」PDF 抽出每筆車次的編組運用資訊。

PDF 版面（一個「區塊」= 一個車組一天的班表，通常佔一頁的一半）：
  header   : 臺北機務段 【TEMU1000】 機車運行 114.5.2 152電
  station  : 花    樹  （2 字站名分兩行：y=50 花 / y=68 蓮）
             蓮    調
  unit+row : T1   13:18 (218) 10:27 ○ 小 站
             ...  16:45 站 (231) 19:40
  footer   : 1 編 × 8 車       417.6 km

抽取規則：
- 車次號 = 括號中的 \d+[A-Z]?，flag 如 'ㄏㄙ'（回送車）、'山'/'海'（路線別）
- 每個時刻 word 的 x 與站名 column x 最靠近者決定該時刻發生在哪一站
- 行內最左時刻 = 發車（發站 = 該時刻最近站），最右時刻 = 到達（到站 = 該時刻最近站）
- 若一行只有 1 個時刻（可能是 mid-point 接力），就記錄該車次但起迄留空

輸出 data/consist_from_pdf.json：
  { "trains": { "<train_no>": {
      "type_name", "depot", "unit_code",
      "origin", "destination", "route",
      "dep_time", "arr_time",
      "flags": [...], "day_conditions": str,
      "page": int, "formation_id": str,
      "is_deadhead": bool }, ... },
    "meta": { "source", "parsed_at", "page_count", "block_count", "train_count" } }
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).parent.parent
PDF_PATH = ROOT / "114年12月23日時刻微調客車編組運用表合併檔1150115(自115年1月20日起實施).pdf"
OUT_PATH = ROOT / "data" / "consist_from_pdf.json"

HEADER_RE = re.compile(r"(\S+機務段)")
HEADER_TYPE_RE = re.compile(r"【([^】]+)】")
FORM_ID_RE = re.compile(r"(\d{1,3}[一-鿿])$")  # e.g., 152電, 151電
UNIT_CODE_RE = re.compile(r"^[A-Z]\d{1,3}[A-Z]?$")
TRAIN_TOKEN_RE = re.compile(r"^\((\d{1,4}[A-Z]?)\)$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")

# 車次行中出現的 flag token
TRAIN_FLAGS = {"ㄏㄙ", "山", "海", "經南迴"}
DAY_CONDITION_PATTERNS = [
    re.compile(r"逢週[一二三四五六日～、]+行駛"),
    re.compile(r"^週[一二三四五六日、～]+"),
]


def group_words_by_y(words: list[dict], tol: float = 2.5) -> list[list[dict]]:
    """Group words into rows by y; rows sorted top-to-bottom, within-row sorted by x."""
    if not words:
        return []
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda x: (x["top"], x["x0"])):
        if rows and abs(rows[-1][-1]["top"] - w["top"]) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    for r in rows:
        r.sort(key=lambda x: x["x0"])
    return rows


def merge_station_pieces(block_rows: list[list[dict]], hdr_y: float) -> list[tuple[float, str]]:
    """站名 row 常把 2 字站名拆到兩個 y（相鄰約 18 px）。把同一 x 的 word 依 y 串起來。

    只吃 header 下方、第一個時刻行之前的 rows。
    """
    stations: dict[float, list[tuple[float, str]]] = defaultdict(list)
    for r in block_rows:
        if not r:
            continue
        y = r[0]["top"]
        if y < hdr_y + 5:
            continue
        # 碰到時刻 row → stop
        if any(TIME_RE.match(w["text"]) for w in r):
            break
        for w in r:
            txt = w["text"]
            # 排除左邊欄（運 號 用 碼）和右邊欄（編 組 × 數字 車 km）
            if w["x0"] < 100 or w["x0"] > 510:
                continue
            # 只吃中文字（含全形標點）
            if not re.search(r"[一-鿿]", txt):
                continue
            # 噪音字：編組 / 里程 / 時刻 欄的單字被誤抓
            if txt in ("編", "組", "車", "×", "時", "刻", "電", "運", "號", "用", "碼",
                       "日", "檢", "以", "行", "為", "準", "站", "小"):
                continue
            # 多字同字（pdfplumber 有時把「車車車車」合成一個 token）
            if len(txt) > 1 and len(set(txt)) == 1:
                continue
            # 含「車」/「編」/「組」字的字串幾乎都是版面噪音（TRA 無此字首站名）
            if any(c in txt for c in ("車", "編", "組")):
                continue
            # 以 x 為 key（tolerance 5）
            key = round(w["x0"] / 5) * 5
            stations[key].append((y, txt))

    # 每個 x key，依 y 串起來（上到下）
    result: list[tuple[float, str]] = []
    for x_key, items in sorted(stations.items()):
        items.sort(key=lambda t: t[0])
        name = "".join(t[1] for t in items)
        if name and len(name) <= 5:
            result.append((float(x_key), name))
    return result


def nearest_station(time_x: float, stations: list[tuple[float, str]]) -> str:
    if not stations:
        return ""
    return min(stations, key=lambda s: abs(s[0] - time_x))[1]


def parse_unit_code(row: list[dict]) -> str | None:
    """行首（x < 75）若是運用碼 pattern，回傳該碼。"""
    for w in row:
        if w["x0"] < 75 and UNIT_CODE_RE.fullmatch(w["text"]):
            return w["text"]
    return None


def parse_train_row(
    row: list[dict], stations: list[tuple[float, str]]
) -> list[dict]:
    """從一個 row 抽出車次記錄。可能一行有多個車次。"""
    # 找所有 (train_no) tokens
    train_tokens = [(i, w) for i, w in enumerate(row) if TRAIN_TOKEN_RE.match(w["text"])]
    if not train_tokens:
        return []

    results: list[dict] = []
    n = len(train_tokens)

    # 行內所有時刻
    times = [(w["x0"], w["text"]) for w in row if TIME_RE.match(w["text"])]

    # flags
    row_flags: list[str] = []
    row_day_cond = ""
    for w in row:
        t = w["text"]
        if t in TRAIN_FLAGS:
            row_flags.append(t)
        for pat in DAY_CONDITION_PATTERNS:
            if pat.match(t):
                row_day_cond = t
                break

    # 一行通常只有一個車次；少數情況多個（如 T6 裡 107A/107）
    # 簡化：若一行多個車次，將時刻平均分配
    for idx, (tok_idx, tok_w) in enumerate(train_tokens):
        m = TRAIN_TOKEN_RE.match(tok_w["text"])
        no = m.group(1)

        # 屬於該車次的時刻：找 x 與 token 最接近的 <=2 個時刻
        tok_x = tok_w["x0"]
        if n == 1:
            own_times = times
        else:
            # 若行裡有多個車次，用時刻到 token 的 x 距離排序取最近的 2 個
            sorted_times = sorted(times, key=lambda t: abs(t[0] - tok_x))
            own_times = sorted(sorted_times[:2], key=lambda t: t[0])

        dep_time = arr_time = ""
        dep_st = arr_st = ""
        if len(own_times) >= 2:
            dep_time = own_times[0][1]
            arr_time = own_times[-1][1]
            dep_st = nearest_station(own_times[0][0], stations)
            arr_st = nearest_station(own_times[-1][0], stations)
        elif len(own_times) == 1:
            dep_time = own_times[0][1]
            dep_st = nearest_station(own_times[0][0], stations)

        is_deadhead = "ㄏㄙ" in row_flags

        results.append({
            "train_no": no,
            "dep_time": dep_time,
            "arr_time": arr_time,
            "origin": dep_st,
            "destination": arr_st,
            "flags": list(row_flags),
            "day_conditions": row_day_cond,
            "is_deadhead": is_deadhead,
        })

    return results


def parse_page(page, page_idx: int) -> list[dict]:
    """一頁可能有多個區塊（自走車組=機車運行；推拉/莒光/普通=客車運行）。"""
    words = page.extract_words(keep_blank_chars=False)
    rows = group_words_by_y(words)

    # 找所有 header row 位置
    block_starts: list[tuple[int, dict]] = []
    for i, r in enumerate(rows):
        text_line = "".join(w["text"] for w in r)
        typ_match = HEADER_TYPE_RE.search(text_line)
        if not typ_match or ("機車運行" not in text_line and "客車運行" not in text_line):
            continue
        run_type = "機車運行" if "機車運行" in text_line else "客車運行"
        # depot 在前一段中文，但可能被橫書「行車經辦人」之類文字干擾
        # 啟發：把所有 x < 260 的中文字串起來，過濾出結尾含「機務段」的子字串
        chars = [w["text"] for w in r if w["x0"] < 270 and re.search(r"[一-鿿]", w["text"])]
        raw = "".join(chars)
        dep_m = re.search(r"(臺北|臺東|花蓮|七堵|高雄|新竹|嘉義|彰化)機務段", raw)
        if not dep_m:
            continue
        depot = dep_m.group(0)
        car_type = typ_match.group(1)
        # formation_id（如 152電）：頁頭最右邊的 word
        form_id = ""
        for w in reversed(r):
            if re.match(r"\d{1,3}[一-鿿]$", w["text"]):
                form_id = w["text"]
                break
        # date 也在 header：114.5.2 之類
        form_date = ""
        for w in r:
            if re.match(r"\d{3}\.\d{1,2}\.\d{1,2}$", w["text"]):
                form_date = w["text"]
                break
        block_starts.append((i, {
            "depot": depot, "car_type": car_type, "run_type": run_type,
            "formation_id": form_id, "formation_date": form_date,
            "hdr_y": r[0]["top"],
        }))

    if not block_starts:
        return []

    records: list[dict] = []
    for bi, (ri, meta) in enumerate(block_starts):
        end_ri = block_starts[bi + 1][0] if bi + 1 < len(block_starts) else len(rows)
        block_rows = rows[ri + 1:end_ri]

        stations = merge_station_pieces(block_rows, meta["hdr_y"])

        # 解析車次行：從 header 之後、站名行結束之後
        # 站名行結束點 = 第一個含時刻的行的 index（相對 block_rows）
        first_time_idx = next(
            (k for k, r in enumerate(block_rows) if any(TIME_RE.match(w["text"]) for w in r)),
            len(block_rows),
        )
        # 運用碼：掃整個 block，記錄「current unit_code」
        current_unit = ""
        for r in block_rows[first_time_idx:]:
            uc = parse_unit_code(r)
            if uc:
                current_unit = uc
            trains = parse_train_row(r, stations)
            for t in trains:
                t.update(
                    depot=meta["depot"],
                    car_type=meta["car_type"],
                    run_type=meta["run_type"],
                    formation_id=meta["formation_id"],
                    formation_date=meta["formation_date"],
                    unit_code=current_unit,
                    page=page_idx + 1,
                )
                records.append(t)
    return records


def main() -> int:
    if not PDF_PATH.exists():
        print(f"PDF not found: {PDF_PATH}", file=sys.stderr)
        return 1

    all_records: list[dict] = []
    block_count = 0
    with pdfplumber.open(PDF_PATH) as pdf:
        for i, page in enumerate(pdf.pages):
            recs = parse_page(page, i)
            all_records.extend(recs)
            # count blocks on page
            words = page.extract_words(keep_blank_chars=False)
            rows = group_words_by_y(words)
            for r in rows:
                text_line = "".join(w["text"] for w in r)
                if "機車運行" in text_line:
                    block_count += 1

    # aggregate per train_no：一個 train_no 可能多次出現（不同運用、不同段、不同天）
    # 採「第一次出現的完整資料」為代表；多版本保存在 variants
    trains: dict[str, dict] = {}
    variants: dict[str, list[dict]] = defaultdict(list)
    for rec in all_records:
        no = rec["train_no"]
        variants[no].append(rec)
        # 主紀錄：優先取 origin 和 destination 都有、且 non-deadhead 的
        existing = trains.get(no)
        score = (1 if (rec["origin"] and rec["destination"]) else 0) + (0 if rec["is_deadhead"] else 1)
        existing_score = -1
        if existing:
            existing_score = (1 if (existing["origin"] and existing["destination"]) else 0) + (0 if existing["is_deadhead"] else 1)
        if score > existing_score:
            # copy primary view
            trains[no] = {
                "train_no": no,
                "type_name": rec["car_type"],
                "depot": rec["depot"],
                "run_type": rec["run_type"],
                "unit_code": rec["unit_code"],
                "formation_id": rec["formation_id"],
                "formation_date": rec["formation_date"],
                "origin": rec["origin"],
                "destination": rec["destination"],
                "route": f"{rec['origin']}－{rec['destination']}" if rec["origin"] and rec["destination"] else "",
                "dep_time": rec["dep_time"],
                "arr_time": rec["arr_time"],
                "flags": rec["flags"],
                "day_conditions": rec["day_conditions"],
                "is_deadhead": rec["is_deadhead"],
                "page": rec["page"],
            }

    # 寫出
    out = {
        "meta": {
            "source": str(PDF_PATH.name),
            "parsed_at": datetime.now().isoformat(timespec="seconds"),
            "block_count": block_count,
            "record_count": len(all_records),
            "train_count": len(trains),
        },
        "trains": trains,
        "variant_count": {no: len(vs) for no, vs in variants.items() if len(vs) > 1},
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"records parsed : {len(all_records)}")
    print(f"unique trains  : {len(trains)}")
    print(f"blocks         : {block_count}")
    print(f"written to     : {OUT_PATH}")

    # sanity
    with_od = sum(1 for t in trains.values() if t["origin"] and t["destination"])
    deadheads = sum(1 for t in trains.values() if t["is_deadhead"])
    print(f"  has origin/destination : {with_od}/{len(trains)}")
    print(f"  deadhead (ㄏㄙ)         : {deadheads}")
    print(f"  sample 105             : {trains.get('105')}")
    print(f"  sample 3131            : {trains.get('3131')}")
    print(f"  sample 105A (variant)  : {trains.get('105A')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
