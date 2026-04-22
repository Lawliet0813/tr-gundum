"""一次性邀請碼服務。碼用完即失效，儲存於 data/invite_codes.json。"""

import json
import random
import string
from pathlib import Path

CODES_PATH = Path(__file__).parent.parent / "data" / "invite_codes.json"


class InviteService:
    def __init__(self) -> None:
        self._codes: dict[str, str | None] = {}
        self._load()

    def _load(self) -> None:
        if CODES_PATH.exists():
            self._codes = json.loads(CODES_PATH.read_text(encoding="utf-8"))

    def _save(self) -> None:
        CODES_PATH.parent.mkdir(exist_ok=True)
        CODES_PATH.write_text(
            json.dumps(self._codes, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def generate(self, n: int = 1) -> list[str]:
        """產生 n 個隨機 6 碼大寫英數字邀請碼，寫入檔案後回傳清單。"""
        chars = string.ascii_uppercase + string.digits
        new_codes: list[str] = []
        attempts = 0
        while len(new_codes) < n and attempts < n * 20:
            code = "".join(random.choices(chars, k=6))
            if code not in self._codes:
                self._codes[code] = None
                new_codes.append(code)
            attempts += 1
        self._save()
        return new_codes

    def redeem(self, code: str, user_id: str) -> bool:
        """驗證並兌換邀請碼。碼不存在或已使用回傳 False，成功回傳 True。"""
        code = code.strip().upper()
        if code not in self._codes or self._codes[code] is not None:
            return False
        self._codes[code] = user_id
        self._save()
        return True

    def list_all(self) -> dict[str, str | None]:
        """回傳全部碼與使用狀態。None 表示未使用，字串為使用者 user_id。"""
        return dict(self._codes)

    def delete_unused(self) -> int:
        """刪除所有未使用的碼，回傳刪除數量。"""
        unused = [c for c, uid in self._codes.items() if uid is None]
        for c in unused:
            del self._codes[c]
        self._save()
        return len(unused)
