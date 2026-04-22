import json
import os
from pathlib import Path

AUTH_PATH = Path(__file__).parent.parent / "data" / "authorized_users.json"


class AuthService:
    def __init__(self):
        self._authorized: set[str] = set()
        self._admins: set[str] = self._load_admins()
        self.reload()

    @staticmethod
    def _load_admins() -> set[str]:
        raw = os.getenv("ADMIN_USER_IDS", "")
        return {uid.strip() for uid in raw.split(",") if uid.strip()}

    def reload(self) -> None:
        if not AUTH_PATH.exists():
            self._authorized = set()
            return
        data = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
        self._authorized = set(data.get("authorized", []))

    def _save(self) -> None:
        existing = {}
        if AUTH_PATH.exists():
            existing = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
        existing["authorized"] = sorted(self._authorized)
        AUTH_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 查詢 ──────────────────────────────────────────────────────────────────

    def is_authorized(self, user_id: str) -> bool:
        """管理員自動有編組查詢權限。"""
        return user_id in self._authorized or user_id in self._admins

    def is_admin(self, user_id: str) -> bool:
        return user_id in self._admins

    def list_authorized(self) -> list[str]:
        return sorted(self._authorized)

    # ── 管理 ──────────────────────────────────────────────────────────────────

    def add(self, user_id: str) -> bool:
        """新增授權用戶，回傳是否為新增（False 表示已存在）。"""
        if user_id in self._authorized:
            return False
        self._authorized.add(user_id)
        self._save()
        return True

    def remove(self, user_id: str) -> bool:
        """移除授權用戶，回傳是否有實際移除。"""
        if user_id not in self._authorized:
            return False
        self._authorized.discard(user_id)
        self._save()
        return True
