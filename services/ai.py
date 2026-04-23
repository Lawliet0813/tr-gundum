"""AI fallback service — Gemma 4 with function calling via google-genai."""

import logging
from datetime import date as dt_date, datetime
from typing import TYPE_CHECKING, Optional

from google import genai
from google.genai import types

if TYPE_CHECKING:
    from .tdx import TDXClient
    from .consist import ConsistService

logger = logging.getLogger(__name__)

_WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]

_SYSTEM_PROMPT = """你是「臺鐵小鋼彈」LINE Bot 的 AI 助理，專門協助台灣鐵路（台鐵/臺鐵）相關問題。

【最重要規定——絕對遵守】
- 直接輸出最終回覆，嚴禁顯示任何思考過程、分析步驟、推理內容
- 禁止在正文前列出任何推理清單或子彈點分析

【語言規定——絕對遵守】
- 所有回覆必須使用繁體中文（台灣用語），禁止使用英文或其他語言

【格式規定——絕對遵守】
- 這是 LINE 純文字訊息，禁止使用任何 Markdown 語法
- 禁止使用 **粗體**、*斜體*、# 標題
- 箭頭請用 Unicode 符號 →，不可寫 ->
- 條列請用 •、-、數字

## 你可以做的事
- 呼叫工具查詢即時時刻表（OD 班次）
- 呼叫工具查詢列車車種與編組摘要
- 呼叫工具推算列車「目前位置」（輸入車次）
- 回答台鐵一般知識

## 回覆原則
- 口吻專業且親切
- 優先呼叫工具取得最新資料
- 回答要簡潔，避免冗長
"""

_GEMMA_TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="query_schedule",
        description="查詢台鐵兩站間時刻表班次",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "origin": types.Schema(type=types.Type.STRING, description="出發站站名"),
                "destination": types.Schema(type=types.Type.STRING, description="目的站站名"),
                "date": types.Schema(type=types.Type.STRING, description="查詢日期 YYYY-MM-DD"),
            },
            required=["origin", "destination"],
        ),
    ),
    types.FunctionDeclaration(
        name="query_consist",
        description="查詢台鐵列車的車種與編組摘要",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "train_no": types.Schema(type=types.Type.STRING, description="車次號碼"),
            },
            required=["train_no"],
        ),
    ),
    types.FunctionDeclaration(
        name="query_location",
        description="推算特定車次目前的「大約地理位置」（基於時刻表與當前時間）",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "train_no": types.Schema(type=types.Type.STRING, description="車次號碼，例如「4191」"),
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
        # 加上當前時間給 AI 參考，方便它判斷 query_location
        now = datetime.now()
        wd = _WEEKDAY_ZH[now.weekday()]
        return _SYSTEM_PROMPT + f"\n今日日期：{now.strftime('%Y-%m-%d')}（星期{wd}）\n當前時間：{now.strftime('%H:%M:%S')}"

    @staticmethod
    def _strip_thinking(text: str) -> str:
        _THINKING_MARKERS = ("User input:", "* Context:", "Context:", "<think>", "</think>")
        t = text
        for m in _THINKING_MARKERS:
            if m in t: t = t.split(m)[-1]
        return t.strip()

    async def reply(self, user_text: str) -> str:
        try:
            result = await self._agentic_loop(user_text)
            result = self._strip_thinking(result)
            return result
        except Exception as exc:
            logger.error("Gemma AI error: %s", exc)
            return "目前 AI 助理暫時無法回應，請稍後再試。"

    async def _agentic_loop(self, user_text: str) -> str:
        config = types.GenerateContentConfig(
            system_instruction=self._system(),
            tools=[_GEMMA_TOOLS],
            max_output_tokens=1024,
            temperature=0.7,
        )
        contents: list = [types.Content(role="user", parts=[types.Part(text=user_text)])]

        for _ in range(5):
            response = await self._client.aio.models.generate_content(
                model=self._model, contents=contents, config=config,
            )
            candidate = response.candidates[0]
            parts = candidate.content.parts
            func_calls = [p for p in parts if p.function_call]
            
            if not func_calls:
                return "".join([p.text for p in parts if p.text]).strip()

            contents.append(types.Content(role="model", parts=parts))
            res_parts = []
            for p in func_calls:
                fc = p.function_call
                result = await self._execute_tool(fc.name, dict(fc.args))
                res_parts.append(types.Part(
                    function_response=types.FunctionResponse(name=fc.name, response={"result": result})
                ))
            contents.append(types.Content(role="user", parts=res_parts))
        return "抱歉，查詢超時。"

    async def _execute_tool(self, name: str, inp: dict) -> str:
        if name == "query_schedule": return await self._tool_query_schedule(inp)
        if name == "query_consist": return self._tool_query_consist(inp)
        if name == "query_location": return self._tool_query_location(inp)
        return f"未知工具：{name}"

    async def _tool_query_schedule(self, inp: dict) -> str:
        origin_raw = inp.get("origin", "")
        dest_raw = inp.get("destination", "")
        date = inp.get("date") or str(dt_date.today())
        origin = self._tdx.find_station(origin_raw)
        dest = self._tdx.find_station(dest_raw)
        if not origin or not dest: return "找不到站名。"
        trains = await self._tdx.query_od(origin[0], dest[0], date)
        if not trains: return "無班次資料。"
        lines = [f"{origin[1]}→{dest[1]} {date} 前 5 班："]
        for t in trains[:5]:
            lines.append(f"• {t['train_no']}次 {t['type_name']} ({t['departure']}→{t['arrival']})")
        return "\n".join(lines)

    def _tool_query_consist(self, inp: dict) -> str:
        train_no = inp.get("train_no", "").strip()
        consist = self._consist.get(train_no)
        if not consist: return f"查無 {train_no} 次編組資料。"
        return f"{train_no} 次：{consist.get('type_name')}\n編組：{consist.get('formation', '—')}\n區間：{consist.get('route', '—')}"

    async def _tool_query_location(self, inp: dict) -> str:
        train_no = inp.get("train_no", "").strip()
        # 使用當前台北時間推算
        from datetime import timezone, timedelta
        tw_now = datetime.now(timezone(timedelta(hours=8))).strftime("%H:%M")
        location = self._tdx.get_train_location(train_no, tw_now)
        return f"車次 {train_no} 目前位置推算（時間 {tw_now}）：\n{location}"
