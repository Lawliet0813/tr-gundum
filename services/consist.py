import json
from pathlib import Path
from typing import Optional

CONSIST_PATH = Path(__file__).parent.parent / "data" / "consist.json"


class ConsistService:
    def __init__(self):
        self._trains: dict[str, dict] = {}
        self._version: str = ""
        self._updated_at: str = ""
        self.reload()

    def reload(self) -> None:
        if not CONSIST_PATH.exists():
            return
        raw = json.loads(CONSIST_PATH.read_text(encoding="utf-8"))
        self._trains = raw.get("trains", {})
        self._version = raw.get("version", "")
        self._updated_at = raw.get("updated_at", "")

    def get(self, train_no: str) -> Optional[dict]:
        """依車次查詢編組，接受有無前導零（'105' 和 '0105' 均可）。"""
        # 優先用原始值，再試去掉前導零的版本
        return (
            self._trains.get(train_no)
            or self._trains.get(train_no.lstrip("0") or "0")
        )

    @property
    def version(self) -> str:
        return self._version

    @property
    def updated_at(self) -> str:
        return self._updated_at

    @property
    def train_count(self) -> int:
        return len(self._trains)
