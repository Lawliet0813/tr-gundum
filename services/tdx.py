import time
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import httpx

TDX_TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
TDX_BASE_URL = "https://tdx.transportdata.tw/api/basic"
STATION_CACHE_PATH = Path(__file__).parent.parent / "data" / "stations_cache.json"
CACHE_TTL_SECONDS = 86400  # 24 hours
TW_TZ = timezone(timedelta(hours=8))


class TDXClient:
    def __init__(self, client_id: str = "", client_secret: str = ""):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        # stations: dict mapping station_id -> {"name_zh": ..., "name_en": ...}
        self._stations: dict[str, dict] = {}
        # alias lookup: normalized string -> station_id
        self._alias_map: dict[str, str] = {}

    async def init(self) -> None:
        if self._client_id and self._client_secret:
            await self._ensure_token()
        try:
            await self._load_stations()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Station data unavailable: %s", exc)

    # ── Token management ──────────────────────────────────────────────────────

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

    # ── Station data ──────────────────────────────────────────────────────────

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

        # TDX v3 may return array directly or wrapped; handle both
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
        STATION_CACHE_PATH.write_text(
            json.dumps(stations, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._build_alias_map()

    # Common name variations that differ only in 台/臺
    _EXTRA_ALIASES: dict[str, str] = {
        "台北": "臺北",
        "台中": "臺中",
        "台南": "臺南",
        "台東": "臺東",
        "台鐵臺北": "臺北",
        "北車": "臺北",
        "北站": "臺北",
        "南車": "高雄",
        "高雄站": "高雄",
    }

    def _build_alias_map(self) -> None:
        name_to_id = {v["name_zh"]: k for k, v in self._stations.items()}
        alias_map: dict[str, str] = {}

        for alias, canonical in self._EXTRA_ALIASES.items():
            if canonical in name_to_id:
                alias_map[alias] = name_to_id[canonical]

        for sid, info in self._stations.items():
            alias_map[info["name_zh"]] = sid
            if info["name_en"]:
                alias_map[info["name_en"].lower()] = sid

        self._alias_map = alias_map

    def find_station(self, name: str) -> Optional[tuple[str, str]]:
        """Return (station_id, display_name) or None."""
        key = name.strip()
        sid = self._alias_map.get(key) or self._alias_map.get(key.lower())
        if sid:
            return sid, self._stations[sid]["name_zh"]
        # Partial match fallback (first hit)
        for mapped_name, mid in self._alias_map.items():
            if key in mapped_name or mapped_name in key:
                return mid, self._stations[mid]["name_zh"]
        return None

    def station_name(self, station_id: str) -> str:
        info = self._stations.get(station_id)
        return info["name_zh"] if info else station_id

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_list(raw) -> list:
        """Handle TDX responses that may be a bare array or a wrapped object."""
        if isinstance(raw, list):
            return raw
        # Common wrapper keys used by TDX
        for key in ("TrainTimetables", "TrainTimetable", "Trains", "Data"):
            if key in raw:
                return raw[key]
        return []

    @staticmethod
    def _trim_time(t: str) -> str:
        """HH:MM:SS → HH:MM"""
        return t[:5] if t else ""

    # ── Schedule queries ──────────────────────────────────────────────────────

    async def query_od(
        self, origin_id: str, dest_id: str, date: str
    ) -> list[dict]:
        """Return trains between two stations on date (YYYY-MM-DD), sorted by departure."""
        headers = await self._auth_headers()
        url = (
            f"{TDX_BASE_URL}/v3/Rail/TRA/DailyTrainTimetable"
            f"/OD/{origin_id}/to/{dest_id}/{date}"
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers=headers,
                params={"$format": "JSON", "$top": 200},
                timeout=20,
            )
            resp.raise_for_status()
            raw = resp.json()

        items = self._extract_list(raw)
        trains: list[dict] = []
        for item in items:
            info = item.get("DailyTrainInfo", {})
            stops = item.get("StopTimes", [])
            origin_stop = next((s for s in stops if s.get("StationID") == origin_id), None)
            dest_stop = next((s for s in stops if s.get("StationID") == dest_id), None)
            if not origin_stop or not dest_stop:
                continue
            trains.append({
                "train_no": info.get("TrainNo", ""),
                "type_name": info.get("TrainTypeName", {}).get("Zh_tw", ""),
                "type_id": info.get("TrainTypeID", ""),
                "departure": self._trim_time(origin_stop.get("DepartureTime", "")),
                "arrival": self._trim_time(dest_stop.get("ArrivalTime", "")),
                "start_name": info.get("StartingStationName", {}).get("Zh_tw", ""),
                "end_name": info.get("EndingStationName", {}).get("Zh_tw", ""),
            })

        trains.sort(key=lambda t: t["departure"])
        return trains

    async def query_train(self, train_no: str, date: str) -> Optional[dict]:
        """Return full timetable for a single train on date (YYYY-MM-DD)."""
        headers = await self._auth_headers()
        padded = train_no.zfill(4)

        today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
        if date == today:
            url = f"{TDX_BASE_URL}/v3/Rail/TRA/DailyTrainTimetable/Today/TrainNo/{padded}"
            params: dict = {"$format": "JSON"}
        else:
            url = f"{TDX_BASE_URL}/v3/Rail/TRA/DailyTrainTimetable/TrainDate/{date}"
            params = {
                "$format": "JSON",
                "$filter": f"TrainNo eq '{padded}'",
                "$top": 1,
            }

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, params=params, timeout=20)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            raw = resp.json()

        items = self._extract_list(raw)
        if not items:
            return None

        item = items[0]
        info = item.get("DailyTrainInfo", {})
        stops = item.get("StopTimes", [])
        return {
            "train_no": info.get("TrainNo", padded),
            "type_name": info.get("TrainTypeName", {}).get("Zh_tw", ""),
            "type_id": info.get("TrainTypeID", ""),
            "start_name": info.get("StartingStationName", {}).get("Zh_tw", ""),
            "end_name": info.get("EndingStationName", {}).get("Zh_tw", ""),
            "stops": [
                {
                    "seq": s.get("StopSequence", 0),
                    "station_id": s.get("StationID", ""),
                    "station_name": s.get("StationName", {}).get("Zh_tw", ""),
                    "arrival": self._trim_time(s.get("ArrivalTime", "")),
                    "departure": self._trim_time(s.get("DepartureTime", "")),
                }
                for s in stops
            ],
        }
