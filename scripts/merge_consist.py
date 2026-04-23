"""合併 PDF parse 結果 + 現有 consist.json + train_list.json 為最終 data/consist.json。

欄位來源：
- formation         ← 原 consist.json（xlsx 匯入，PDF 無此資訊）
- type_name         ← PDF 的 car_type（具體車型，如 E500+PP+E500、TEMU2000）
- depot             ← PDF 的機務段
- run_type          ← PDF 的「機車運行」/「客車運行」
- unit_code         ← PDF 的運用碼（如 P27、T6、K11）
- formation_id      ← PDF 的電車組編號（如 151電、152電）
- formation_date    ← PDF 的編成實施日
- origin/destination/route ← train_list.json 的營運區間（若無則 PDF 的機務段 origin/destination）
- depot_origin/depot_destination ← PDF 的起訖（含「潮州基地」這類機務段視角）
- dep_time/arr_time ← PDF 的發車/到達時刻
- flags             ← PDF 的山/海/經南迴等
- day_conditions    ← PDF 的限定行駛日
- is_deadhead       ← PDF 的「ㄏㄙ」回送車標記
- pdf_page          ← PDF 頁碼
- train_level       ← full_timetables 的營運等級（自強/莒光/區間車）
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC_CONSIST = ROOT / "data" / "consist.json"
SRC_PDF = ROOT / "data" / "consist_from_pdf.json"
SRC_TL = ROOT / "data" / "train_list.json"
SRC_FT = ROOT / "data" / "full_timetables.json"
OUT = ROOT / "data" / "consist.json"


def load():
    cj = json.loads(SRC_CONSIST.read_text(encoding="utf-8"))
    pdf = json.loads(SRC_PDF.read_text(encoding="utf-8"))
    tl_raw = json.loads(SRC_TL.read_text(encoding="utf-8"))
    ft = json.loads(SRC_FT.read_text(encoding="utf-8"))
    tl = {t["train_no"].lstrip("0"): t for t in tl_raw}
    return cj, pdf, tl, ft


def merge() -> dict:
    cj, pdf, tl, ft = load()
    pdf_trains = pdf["trains"]
    existing = cj["trains"]

    # 所有 train_no 的聯集
    all_nos: set[str] = set(existing.keys()) | set(pdf_trains.keys())

    merged: dict[str, dict] = {}
    for no in sorted(all_nos, key=lambda x: (not x.isdigit(), int(re.match(r"\d+", x).group()) if re.match(r"\d+", x) else 0, x)):
        # 排序：純數字優先（依數字大小），suffix 版本排後面
        ex = existing.get(no, {})
        pd = pdf_trains.get(no, {})
        clean_no = re.match(r"(\d+)", no).group(1) if re.match(r"\d+", no) else no
        t_meta = tl.get(clean_no) or tl.get(no) or {}
        t_tt = ft.get(clean_no) or ft.get(no) or {}

        # 營運區間（優先 train_list，次之 PDF 的 depot origin/destination）
        # 例外：若 no 是字母後綴的回送車（如 105A ㄏㄙ），不套基礎車次的營運區間，
        # 因為 105A 的實際路線是回送路段，跟 105 不同
        is_dh_suffix = pd.get("is_deadhead") and not no.isdigit()
        if is_dh_suffix:
            origin = pd.get("origin", "")
            dest = pd.get("destination", "")
        else:
            origin = t_meta.get("origin") or ex.get("origin") or pd.get("origin") or ""
            dest = t_meta.get("destination") or ex.get("destination") or pd.get("destination") or ""
        # 清掉 ex 裡的殘留 HH:MM route bug（若還殘留）
        ex_route = ex.get("route", "")
        if re.fullmatch(r"\d{1,2}:\d{2}", ex_route):
            ex_route = ""
        route = t_meta.get("route") or ex_route or (
            f"{origin}－{dest}" if origin and dest else ""
        )

        merged[no] = {
            # 核心識別
            "train_no": no,
            "train_level": t_tt.get("type", ""),
            "type_name": pd.get("type_name") or ex.get("type_name", ""),
            # 營運區間
            "origin": origin,
            "destination": dest,
            "route": route,
            # 機務
            "depot": pd.get("depot", ""),
            "run_type": pd.get("run_type", ""),
            "unit_code": pd.get("unit_code", ""),
            "formation": ex.get("formation", ""),
            "formation_id": pd.get("formation_id", ""),
            "formation_date": pd.get("formation_date", ""),
            # 機務視角起訖（可能與營運不同，例如「潮州基地」）
            # 過濾單字結果：PDF 有些頁把 2 字站名的其中一字被「行車經辦人」疊字噪音吃掉
            "depot_origin": pd.get("origin", "") if len(pd.get("origin", "")) >= 2 else "",
            "depot_destination": pd.get("destination", "") if len(pd.get("destination", "")) >= 2 else "",
            "dep_time": pd.get("dep_time", ""),
            "arr_time": pd.get("arr_time", ""),
            # 標記
            "flags": pd.get("flags", []) or [],
            "day_conditions": pd.get("day_conditions", ""),
            "is_deadhead": pd.get("is_deadhead", False),
            # 乘務（保留原欄位，先前應為 xlsx 提供）
            "crew_mech": ex.get("crew_mech", ""),
            "crew_ops": ex.get("crew_ops", ""),
            # 來源追蹤
            "pdf_page": pd.get("page", 0),
            # 有時刻表：帶後綴版本（105A）的時刻表不算（suffix 通常是回送/備援）
            "has_timetable": no in ft,
        }

    out = {
        "version": cj.get("version", "1150120"),
        "updated_at": date.today().isoformat(),
        "source": (
            "PDF consist (114.12.23 微調, 自 115.01.20 起實施) + "
            "TRA ODS timetables (115.04.09) + xlsx crew/formation"
        ),
        "schema_version": 2,
        "trains": merged,
    }

    OUT.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


def report(out: dict) -> None:
    trains = out["trains"]
    total = len(trains)
    print(f"merged trains: {total}")

    def pct(n, d):
        return f"{n}/{d} ({100*n/d:.1f}%)"

    with_od = sum(1 for t in trains.values() if t["origin"] and t["destination"])
    with_depot = sum(1 for t in trains.values() if t["depot"])
    with_unit = sum(1 for t in trains.values() if t["unit_code"])
    with_form = sum(1 for t in trains.values() if t["formation"])
    with_tt = sum(1 for t in trains.values() if t["has_timetable"])
    deadheads = sum(1 for t in trains.values() if t["is_deadhead"])

    print(f"  origin/destination   : {pct(with_od, total)}")
    print(f"  depot (機務段)        : {pct(with_depot, total)}")
    print(f"  unit_code (運用碼)    : {pct(with_unit, total)}")
    print(f"  formation (機車編號)  : {pct(with_form, total)}")
    print(f"  has_timetable         : {pct(with_tt, total)}")
    print(f"  deadhead (ㄏㄙ)        : {deadheads}")

    # 三個樣本
    for no in ("105", "3131", "105A"):
        t = trains.get(no)
        if not t:
            continue
        print(f"\n  [{no}]")
        for k in ("train_level", "type_name", "depot", "run_type", "unit_code",
                  "origin", "destination", "route", "dep_time", "arr_time",
                  "formation", "flags", "is_deadhead"):
            print(f"    {k:<18} = {t.get(k)!r}")


if __name__ == "__main__":
    report(merge())
