import time
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import httpx

TDX_TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
TDX_BASE_URL = "https://tdx.transportdata.tw/api/basic"
STATION_CACHE_PATH = Path(__file__).parent.parent / "data" / "stations_cache.json"
FULL_TIMETABLE_PATH = Path(__file__).parent.parent / "data" / "full_timetables.json"
CACHE_TTL_SECONDS = 86400  # 24 hours
TW_TZ = timezone(timedelta(hours=8))


class TDXClient:
    def __init__(self, client_id: str = "", client_secret: str = ""):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._stations: dict[str, dict] = {}
        self._alias_map: dict[str, str] = {}
        self._full_timetables: dict = {}

    async def init(self) -> None:
        if self._client_id and self._client_secret:
            await self._ensure_token()
        try:
            await self._load_stations()
            await self._load_full_timetables()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Initialisation failed: %s", exc)

    async def _load_full_timetables(self) -> None:
        if FULL_TIMETABLE_PATH.exists():
            self._full_timetables = json.loads(FULL_TIMETABLE_PATH.read_text(encoding="utf-8"))
            print(f"Loaded {len(self._full_timetables)} local train timetables.")

    # ── Token & Station methods remain unchanged... ──────────────────────────

    async def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TDX_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 86400)
        return self._token

    async def _auth_headers(self) -> dict:
        if not self._client_id or not self._client_secret:
            return {}
        token = await self._ensure_token()
        return {"Authorization": f"Bearer {token}"}

    async def _load_stations(self) -> None:
        if STATION_CACHE_PATH.exists():
            mtime = STATION_CACHE_PATH.stat().st_mtime
            if time.time() - mtime < CACHE_TTL_SECONDS:
                self._stations = json.loads(STATION_CACHE_PATH.read_text(encoding="utf-8"))
                self._build_alias_map()
                return
        await self._fetch_and_cache_stations()

    async def _fetch_and_cache_stations(self) -> None:
        headers = await self._auth_headers()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{TDX_BASE_URL}/v3/Rail/TRA/Station",
                headers=headers,
                params={"$format": "JSON", "$top": 500},
                timeout=20,
            )
            resp.raise_for_status()
            raw = resp.json()
        items = raw if isinstance(raw, list) else raw.get("Stations", raw.get("stations", []))
        stations: dict[str, dict] = {}
        for s in items:
            sid = s.get("StationID", "")
            name_zh = s.get("StationName", {}).get("Zh_tw", "")
            name_en = s.get("StationName", {}).get("En", "")
            if sid and name_zh:
                stations[sid] = {"name_zh": name_zh, "name_en": name_en}
        self._stations = stations
        STATION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATION_CACHE_PATH.write_text(json.dumps(stations, ensure_ascii=False, indent=2), encoding="utf-8")
        self._build_alias_map()

    _EXTRA_ALIASES: dict[str, str] = {
        "台北": "臺北", "台中": "臺中", "台南": "臺南", "台東": "臺東",
        "台鐵臺北": "臺北", "北車": "臺北", "北站": "臺北", "南車": "高雄", "高雄站": "高雄",
    }

    def _build_alias_map(self) -> None:
        name_to_id = {v["name_zh"]: k for k, v in self._stations.items()}
        alias_map: dict[str, str] = {}
        for alias, canonical in self._EXTRA_ALIASES.items():
            if canonical in name_to_id: alias_map[alias] = name_to_id[canonical]
        for sid, info in self._stations.items():
            alias_map[info["name_zh"]] = sid
            if info["name_en"]: alias_map[info["name_en"].lower()] = sid
        self._alias_map = alias_map

    def find_station(self, key: str) -> Optional[tuple[str, str]]:
        if not key: return None
        sid = self._alias_map.get(key) or self._alias_map.get(key.lower())
        if sid: return sid, self._stations[sid]["name_zh"]
        if len(key) < 2: return None
        key_lower = key.lower()
        best, best_len = None, 0
        for mapped_name, mid in self._alias_map.items():
            if len(mapped_name) >= 2 and mapped_name in key_lower:
                if len(mapped_name) > best_len:
                    best = (mid, self._stations[mid]["name_zh"])
                    best_len = len(mapped_name)
        return best

    def station_name(self, station_id: str) -> str:
        info = self._stations.get(station_id)
        return info["name_zh"] if info else station_id

    # ── Local Query Methods (Replacing TDX API) ───────────────────────────────

    async def query_od(self, origin_id: str, dest_id: str, date: str) -> list[dict]:
        """從本地 ODS 資料庫執行站到站查詢"""
        if not self._full_timetables:
            await self._load_full_timetables()
        
        origin_name = self.station_name(origin_id).replace("臺", "台")
        dest_name = self.station_name(dest_id).replace("臺", "台")
        
        results = []
        for t_no, data in self._full_timetables.items():
            stops = data.get("stops", [])
            # 找起點與終點
            o_idx = next((i for i, s in enumerate(stops) if s["s"] in (origin_name, origin_name.replace("台", "臺"))), -1)
            d_idx = next((i for i, s in enumerate(stops) if s["s"] in (dest_name, dest_name.replace("台", "臺"))), -1)
            
            if o_idx != -1 and d_idx != -1 and o_idx < d_idx:
                results.append({
                    "train_no": t_no,
                    "type_name": data["type"],
                    "departure": stops[o_idx]["t"],
                    "arrival": stops[d_idx]["t"],
                    "start_name": stops[0]["s"],
                    "end_name": stops[-1]["s"]
                })
        
        results.sort(key=lambda x: x["departure"])
        return results

    async def query_train(self, train_no: str, date: str) -> Optional[dict]:
        """從本地 ODS 資料庫查詢單一車次時刻表"""
        if not self._full_timetables:
            await self._load_full_timetables()
        
        data = self._full_timetables.get(train_no.lstrip('0'))
        if not data:
            return None
            
        stops = data.get("stops", [])
        return {
            "train_no": train_no,
            "type_name": data["type"],
            "start_name": stops[0]["s"],
            "end_name": stops[-1]["s"],
            "stops": [
                {
                    "seq": i + 1,
                    "station_name": s["s"],
                    "arrival": s["t"],
                    "departure": s["t"]
                } for i, s in enumerate(stops)
            ]
        }
