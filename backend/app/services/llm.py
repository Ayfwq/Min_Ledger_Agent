"""SiliconFlow (OpenAI-compatible) client + structured receipt extraction."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = [
    "餐饮",
    "交通",
    "购物",
    "生活缴费",
    "娱乐",
    "医疗",
    "教育",
    "住房",
    "旅行",
    "通讯",
    "其他",
]


class LLMError(RuntimeError):
    """Raised when the model cannot be reached or keeps returning bad output."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class ExtractedTransaction(BaseModel):
    amount: float | None = None
    currency: str | None = None
    date: str | None = None
    merchant: str | None = None
    description: str | None = None
    category: str | None = None
    confidence: dict[str, float] = Field(default_factory=dict)
    ambiguous_fields: list[str] = Field(default_factory=list)
    notes: str | None = None


class ExtractionResult(BaseModel):
    transactions: list[ExtractedTransaction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_text: str | None = None


SYSTEM_PROMPT = """你是一个严谨的记账信息抽取引擎。你的任务是从用户提供的消费描述或交易截图中，
抽取**所有**消费/支出记录，并输出严格 JSON。

硬性规则：
1. 只输出 JSON，不要输出 markdown 代码块或解释文字。
2. 不得编造。看不到或不确定的字段必须输出 null，并在 confidence 中给出低分。
3. 金额必须是数字（单位：元），不要带货币符号；无法确定则为 null。
4. 日期必须是 YYYY-MM-DD。相对日期（今天/昨天/前天/上周X）请结合"今天是 {today}"换算。
5. 一条输入可能包含多笔消费，必须拆成多个 transactions 元素。
6. category 只能取以下值之一：{categories}；无法判断则为 null。
7. merchant 是商户/店铺/平台名；description 是消费说明（如"拿铁 2 杯"）。
8. confidence 是 0~1 的数字，键名用 amount/date/merchant/category/description。
9. ambiguous_fields 列出你无法确定、需要向用户澄清的字段名。
10. 如果是截图且模糊、遮挡、被裁剪导致无法读取，transactions 可为空数组，并在 warnings 说明原因。

输出 JSON schema：
{{
  "transactions": [
    {{
      "amount": 35.5,
      "currency": "CNY",
      "date": "2026-11-10",
      "merchant": "星巴克",
      "description": "拿铁",
      "category": "餐饮",
      "confidence": {{"amount": 0.98, "date": 0.9, "merchant": 0.85, "category": 0.8}},
      "ambiguous_fields": [],
      "notes": null
    }}
  ],
  "warnings": []
}}"""

USER_TEXT_TEMPLATE = """请从下面这段消费描述中抽取账单：

<<<
{text}
>>>"""

IMAGE_PROMPT = """请识别这张交易/订单截图中的消费信息，按系统要求输出 JSON。
注意：截图可能模糊、被遮挡或字段缺失；看不清的字段必须为 null，不要猜测。"""


def _today() -> str:
    try:
        tz = ZoneInfo(settings.timezone)
    except Exception:  # Windows without tzdata
        from datetime import timedelta, timezone

        tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d")


def _system_prompt() -> str:
    return SYSTEM_PROMPT.format(today=_today(), categories="、".join(ALLOWED_CATEGORIES))


def _strip_code_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    return content.strip()


def _extract_json_object(content: str) -> dict[str, Any]:
    content = _strip_code_fence(content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start : end + 1])
        raise


class SiliconFlowClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        text_model: str | None = None,
        vision_model: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.siliconflow_api_key
        self.base_url = (base_url or settings.siliconflow_base_url).rstrip("/")
        self.text_model = text_model or settings.llm_text_model
        self.vision_model = vision_model or settings.llm_vision_model
        self.timeout = timeout if timeout is not None else settings.llm_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else settings.llm_max_retries

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def _chat(self, messages: list[dict[str, Any]], model: str) -> str:
        if not self.configured:
            raise LLMError("未配置硅基流动 API Key，请设置 SILICONFLOW_API_KEY")

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        last_error: str | None = None
        client_kwargs: dict[str, Any] = {"timeout": self.timeout, "trust_env": False}
        if settings.llm_proxy:
            client_kwargs["proxy"] = settings.llm_proxy
        async with httpx.AsyncClient(**client_kwargs) as client:
            for attempt in range(self.max_retries + 1):
                started = time.perf_counter()
                try:
                    resp = await client.post(url, json=payload, headers=headers)
                    elapsed = int((time.perf_counter() - started) * 1000)
                    logger.info(
                        "llm call model=%s status=%s duration_ms=%s",
                        model,
                        resp.status_code,
                        elapsed,
                    )
                    if resp.status_code >= 500 or resp.status_code == 429:
                        raise LLMError(f"模型服务暂不可用 (HTTP {resp.status_code})")
                    if resp.status_code >= 400:
                        # Never log the key; body is useful for debugging.
                        raise LLMError(
                            f"模型调用失败 (HTTP {resp.status_code})",
                            detail=resp.text[:500],
                        )
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    if not content:
                        raise LLMError("模型返回空内容")
                    return content
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = f"模型调用超时或网络错误: {exc}"
                except (KeyError, ValueError) as exc:
                    last_error = f"模型响应格式异常: {exc}"
                except LLMError as exc:
                    last_error = str(exc)
                    if exc.detail:
                        last_error = f"{last_error} | {exc.detail}"
                if attempt < self.max_retries:
                    logger.warning("llm retry %s/%s: %s", attempt + 1, self.max_retries, last_error)
                    await _sleep(1.5 * (attempt + 1))
        raise LLMError(last_error or "模型调用失败")

    async def _extract_with_repair(
        self, messages: list[dict[str, Any]], model: str
    ) -> tuple[ExtractionResult, dict[str, Any]]:
        """Call the model and validate JSON, asking for a repair when invalid."""
        last_raw: str | None = None
        last_error: str | None = None
        convo = list(messages)
        for attempt in range(self.max_retries + 1):
            content = await self._chat(convo, model)
            last_raw = content
            try:
                data = _extract_json_object(content)
                result = ExtractionResult.model_validate(data)
                return result, data
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = str(exc)[:400]
                logger.warning("extraction json invalid (attempt %s): %s", attempt + 1, last_error)
                convo = [
                    *messages,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "上面的 JSON 不符合要求：" + last_error + "。"
                            "请只输出一个合法的 JSON 对象，字段与 schema 完全一致。"
                        ),
                    },
                ]
                await _sleep(0.8)
        raise LLMError("模型输出无法解析为合法账单 JSON", detail=last_raw[:800] if last_raw else None)

    async def extract_text(self, text: str) -> tuple[ExtractionResult, dict[str, Any]]:
        messages = [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": USER_TEXT_TEMPLATE.format(text=text)},
        ]
        return await self._extract_with_repair(messages, self.text_model)

    async def extract_image(self, path: Path, content_type: str) -> tuple[ExtractionResult, dict[str, Any]]:
        import asyncio

        encoded = base64.b64encode(await asyncio.to_thread(path.read_bytes)).decode("ascii")
        messages = [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": IMAGE_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{content_type};base64,{encoded}"},
                    },
                ],
            },
        ]
        return await self._extract_with_repair(messages, self.vision_model)


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


client = SiliconFlowClient()
