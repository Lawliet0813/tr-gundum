"""AI fallback service — Claude Haiku with tool use (primary), Gemini (fallback)."""

import logging
from datetime import date as dt_date
from typing import TYPE_CHECKING

import anthropic
from google import genai
from google.genai import types

if TYPE_CHECKING:
    from .tdx import TDXClient
    from .consist import ConsistService

logger = logging.getLogger(__name__)

# ── System prompts ──────────────────────────────────────────────────────────────

_CLAUDE_SYSTEM = """你是「臺鐵小鋼彈」LINE Bot 的 AI 助理，專門協助台灣鐵路（台鐵/臺鐵）相關問題。

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

_GEMINI_SYSTEM = """你是「臺鐵小鋼彈」LINE Bot 的 AI 助理，專門協助台灣鐵路（台鐵/臺鐵）相關問題。

## 你能回答的問題
- 台鐵車種說明（自強號、莒光號、區間車、普悠瑪、太魯閣等）
- 訂票方式、退票規則、行李規定
- 各站介紹、著名路線（北迴線、南迴線、山線、海線等）
- 搭車注意事項、無障礙服務

## Bot 支援的查詢指令（請引導用戶使用）
- `台北 高雄`：查詢 OD 時刻表（今天）
- `台北 高雄 明天`：查詢指定日期
- `105`：查詢 105 次車次時刻
- `##105`：查詢 105 次列車編組

## 回覆原則
- 使用繁體中文，口吻親切自然
- 回答要簡潔，避免過長
- 無法確定的資訊（如即時誤點）請誠實說明，並引導用戶查詢台鐵官網
- 若問題與台鐵無關，婉拒並說明 Bot 的功能範圍
"""

# ── Tool schemas ────────────────────────────────────────────────────────────────

_TOOLS = [
    {
        "name": "query_schedule",
        "description": "查詢台鐵兩站間的時刻表班次（需提供出發站和目的站）",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "出發站中文站名，例如「台北」、「新竹」",
                },
                "destination": {
                    "type": "string",
                    "description": "目的站中文站名，例如「高雄」、「台南」",
                },
                "date": {
                    "type": "string",
                    "description": "查詢日期，格式 YYYY-MM-DD，預設今天",
                },
            },
            "required": ["origin", "destination"],
        },
    },
    {
        "name": "query_consist",
        "description": "查詢台鐵列車的車種與編組摘要（不含授權限定的詳細資訊）",
        "input_schema": {
            "type": "object",
            "properties": {
                "train_no": {
                    "type": "string",
                    "description": "車次號碼，例如「105」、「1035」",
                },
            },
            "required": ["train_no"],
        },
    },
]


# ── Claude Haiku service ────────────────────────────────────────────────────────

class ClaudeAIService:
    def __init__(self, api_key: str, tdx: "TDXClient", consist: "ConsistService"):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._tdx = tdx
        self._consist = consist

    async def reply(self, user_text: str) -> str:
        try:
            return await self._agentic_loop(user_text)
        except Exception as exc:
            logger.error("Claude AI error: %s", exc)
            return "目前 AI 助理暫時無法回應，請稍後再試。\n\n輸入「幫助」查看 Bot 支援的指令。"

    async def _agentic_loop(self, user_text: str) -> str:
        messages = [{"role": "user", "content": user_text}]

        for _ in range(5):  # max 5 tool-call rounds
            response = await self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=_CLAUDE_SYSTEM,
                tools=_TOOLS,
                messages=messages,
            )

            if response.stop_reason != "tool_use":
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text.strip()
                return "抱歉，我暫時無法回應。"

            # Execute all requested tools, then continue
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = await self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

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


# ── Gemini fallback service ─────────────────────────────────────────────────────

class GeminiService:
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def reply(self, user_text: str) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_text,
                config=types.GenerateContentConfig(
                    system_instruction=_GEMINI_SYSTEM,
                    max_output_tokens=512,
                    temperature=0.7,
                ),
            )
            return response.text.strip()
        except Exception as exc:
            logger.error("Gemini API error: %s", exc)
            return "目前 AI 助理暫時無法回應，請稍後再試。\n\n輸入「幫助」查看 Bot 支援的指令。"
