"""一次性遷移腳本：從舊版 new.py 的 TEMP3 函數抽取編組運用資料，寫入 consist.json。"""

import re
import json
import sys
from datetime import date
from pathlib import Path

NEW_PY = Path(__file__).parent.parent / "linebot" / "new.py"
OUTPUT = Path(__file__).parent.parent / "data" / "consist.json"


def get_field(line: str, field: str) -> str:
    m = re.search(rf"'{re.escape(field)}：([^']+)'", line)
    return m.group(1).strip() if m else ""


def extract_date(line: str) -> str:
    m = re.search(r"'編組運用日期：(\d+)'", line)
    return m.group(1) if m else ""


def roc_to_ad(roc: str) -> str:
    """民國 YYYMMDD → AD YYYY-MM-DD"""
    if len(roc) == 7:
        year = int(roc[:3]) + 1911
        return f"{year}-{roc[3:5]}-{roc[5:7]}"
    return roc


def main():
    if not NEW_PY.exists():
        print(f"找不到 {NEW_PY}，請確認路徑", file=sys.stderr)
        sys.exit(1)

    content = NEW_PY.read_text(encoding="utf-8")

    # 找到 TEMP3 函數的範圍
    start = content.find("def TEMP3(")
    if start == -1:
        print("找不到 TEMP3 函數", file=sys.stderr)
        sys.exit(1)
    # 下一個 def 或 EOF
    next_def = content.find("\ndef ", start + 1)
    block = content[start:next_def] if next_def != -1 else content[start:]

    line_re = re.compile(r"(?:if|elif) msg == '([^']+)':")

    trains: dict[str, dict] = {}
    version_roc = ""

    for line in block.splitlines():
        m = line_re.search(line)
        if not m:
            continue
        train_no = m.group(1)
        if not version_roc:
            version_roc = extract_date(line)

        trains[train_no] = {
            "type_name":  get_field(line, "車型"),
            "formation":  get_field(line, "歸屬段與運用號碼"),
            "route":      get_field(line, "區間"),
            "crew_mech":  get_field(line, "值乘區間(機務)"),
            "crew_ops":   get_field(line, "值乘區間(運務)"),
        }

    if not trains:
        print("未找到任何車次資料，請檢查 TEMP3 格式是否有變", file=sys.stderr)
        sys.exit(1)

    result = {
        "version": version_roc,
        "updated_at": roc_to_ad(version_roc),
        "source": "extracted from new.py TEMP3",
        "trains": trains,
    }

    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：共匯出 {len(trains)} 筆車次資料 → {OUTPUT}")
    print(f"版本：民國 {version_roc}（西元 {roc_to_ad(version_roc)}）")


if __name__ == "__main__":
    main()
