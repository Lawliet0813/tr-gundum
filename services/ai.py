"""AI fallback service — Gemma 4 with function calling via google-genai."""

import logging
from datetime import date as dt_date
from typing import TYPE_CHECKING

from google import genai
from google.genai import types

if TYPE_CHECKING:
    from .tdx import TDXClient
    from .consist import ConsistService

logger = logging.getLogger(__name__)

_WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]

_SYSTEM_PROMPT = """你是「臺鐵小鋼彈」LINE Bot 的 AI 助理，專門協助台灣鐵路（台鐵/臺鐵）相關問題。

## 你可以做的事
- 呼叫工具查詢即時台鐵時刻表（OD 班次）
- 呼叫工具查詢列車車種與編組摘要
- 回答台鐵一般知識（車種說明、訂票方式、路線介紹等）

## Bot 快捷指令（請適時引導用戶使用）
- `台北 高雄`：查詢今日 OD 時刻表（會顯示精美卡片）
- `台北 高雄 明天`：指定日期查詢
- `105`：查詢 105 次車次時刻
- `##105`：查詢 105 次列車詳細編組（需授權）

## 回覆原則
- 使用繁體中文，口吻親切自然
- 有工具可用時優先呼叫工具，取得即時資料後再回答
- 回答要簡潔，避免過長
- 若問題與台鐵無關，婉拒並說明 Bot 功能範圍
- 無法確定的資訊請誠實告知，引導用戶查詢台鐵官網
"""

_GEMMA_TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="query_schedule",
        description="查詢台鐵兩站間時刻表班次（需提供出發站和目的站）",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "origin": types.Schema(
                    type=types.Type.STRING,
                    description="出發站中文站名，例如「台北」、「新竹」",
                ),
                "destination": types.Schema(
                    type=types.Type.STRING,
                    description="目的站中文站名，例如「高雄」、「台南」",
                ),
                "date": types.Schema(
                    type=types.Type.STRING,
                    description="查詢日期，格式 YYYY-MM-DD，預設今天",
                ),
            },
            required=["origin", "destination"],
        ),
    ),
    types.FunctionDeclaration(
        name="query_consist",
        description="查詢台鐵列車的車種與編組摘要（不含授權限定詳細資訊）",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "train_no": types.Schema(
                    type=types.Type.STRING,
                    description="車次號碼，例如「105」、「1035」",
                ),
            },
            required=["train_no"],
        ),
    ),
])


class GemmaAIService:
    def __init__(
        self,
        api_key: str,
        tdx: "TDXClient",
        consist: "ConsistService",
        model: str = "gemma-4-31b-it",
    ):
        self._client = genai.Client(api_key=api_key)
        self._tdx = tdx
        self._consist = consist
        self._model = model

    def _system(self) -> str:
        today = dt_date.today()
        wd = _WEEKDAY_ZH[today.weekday()]
        return _SYSTEM_PROMPT + f"\n今日日期：{today.strftime('%Y-%m-%d')}（星期{wd}）"

    async def reply(self, user_text: str) -> str:
        try:
            result = await self._agentic_loop(user_text)
            if len(result) > 4800:
                result = result[:4800] + "…（回覆過長已截斷）"
            return result
        except Exception as exc:
            logger.error("Gemma AI error: %s", exc)
            return "目前 AI 助理暫時無法回應，請稍後再試。\n\n輸入「幫助」查看 Bot 支援的指令。"

    async def _agentic_loop(self, user_text: str) -> str:
        config = types.GenerateContentConfig(
            system_instruction=self._system(),
            tools=[_GEMMA_TOOLS],
            max_output_tokens=2048,
            temperature=0.7,
        )
        contents: list = [types.Content(role="user", parts=[types.Part(text=user_text)])]

        for _ in range(5):
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )

            candidate = response.candidates[0]
            parts = candidate.content.parts

            func_calls = [p for p in parts if p.function_call]
            if not func_calls:
                for p in parts:
                    if p.text:
                        return p.text.strip()
                return "抱歉，我暫時無法回應。"

            contents.append(types.Content(role="model", parts=parts))

            result_parts = []
            for p in func_calls:
                fc = p.function_call
                result = await self._execute_tool(fc.name, dict(fc.args))
                result_parts.append(types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result},
                    )
                ))
            contents.append(types.Content(role="user", parts=result_parts))

        return "抱歉，查詢超時，請稍後再試。"

    async def _execute_tool(self, name: str, inp: dict) -> str:
        if name == "query_schedule":
            return await self._tool_query_schedule(inp)
        if name == "query_consist":
            return self._tool_query_consist(inp)
        return f"未知工具：{name}"

    async def _tool_query_schedule(self, inp: dict) -> str:
        origin_raw = inp.get("origin", "")
        dest_raw = inp.get("destination", "")
        date = inp.get("date") or str(dt_date.today())

        origin = self._tdx.find_station(origin_raw)
        dest = self._tdx.find_station(dest_raw)

        if not origin:
            return f"找不到車站「{origin_raw}」，請確認站名。"
        if not dest:
            return f"找不到車站「{dest_raw}」，請確認站名。"

        origin_id, origin_name = origin
        dest_id, dest_name = dest
        trains = await self._tdx.query_od(origin_id, dest_id, date)

        if not trains:
            return f"{date} {origin_name}→{dest_name} 無班次資料。"

        lines = [f"{origin_name}→{dest_name} {date}，共 {len(trains)} 班："]
        for t in trains[:10]:
            lines.append(
                f"  {t['train_no']}次 {t['type_name']} "
                f"出發 {t['departure']} 到達 {t['arrival']}"
            )
        if len(trains) > 10:
            lines.append(f"  （僅顯示前 10 班，共 {len(trains)} 班）")
        return "\n".join(lines)

    def _tool_query_consist(self, inp: dict) -> str:
        train_no = inp.get("train_no", "").strip()

        try:
            base = int(train_no.rstrip("AB"))
            if base >= 7000:
                return f"{train_no} 次為貨運車次，編組資訊不對外開放。"
        except ValueError:
            pass

        consist = self._consist.get(train_no)
        if not consist:
            return f"查無 {train_no} 次編組資料（資料版本：{self._consist.updated_at}）。"

        type_name = consist.get("type_name", "未知車種")
        formation = consist.get("formation", "")
        result = f"{train_no} 次：{type_name}"
        if formation:
            result += f"，{formation}"
        result += f"。\n（輸入 ##{train_no} 可查詢詳細授權資訊）"
        return result
