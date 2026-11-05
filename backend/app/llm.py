from __future__ import annotations

import json
import re
import time
from typing import Any

from openai import OpenAI

from app.config import get_settings
from app.pipeline.settings_store import resolve_llm_config


def get_client() -> OpenAI:
    llm = resolve_llm_config()
    if not llm["llm_api_key"]:
        raise RuntimeError("LLM_API_KEY is not configured (set it in Admin → Settings or .env)")
    return OpenAI(api_key=llm["llm_api_key"], base_url=llm["llm_base_url"])


def _is_stackit(base_url: str | None = None) -> bool:
    base = (base_url or resolve_llm_config()["llm_base_url"]).lower()
    return "onstackit.cloud" in base or "stackit" in base


def chat_completion(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    json_mode: bool = False,
    model: str | None = None,
) -> Any:
    llm = resolve_llm_config()
    client = get_client()
    model_name = model or llm["llm_model"] or get_settings().llm_model

    kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
    }

    # STACKIT/Qwen: keep short classification calls free of long thinking budgets.
    if _is_stackit(llm["llm_base_url"]) and re.search(r"qwen", model_name, re.IGNORECASE):
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    if tools:
        kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    kwargs["max_tokens"] = max_tokens

    last_error: Exception | None = None
    for attempt in range(1, 7):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            message = str(exc).lower()
            if "429" in message or "rate" in message:
                time.sleep(min(2**attempt, 30))
                continue
            if attempt == 1 and "extra_body" in kwargs:
                kwargs.pop("extra_body", None)
                continue
            if attempt == 1 and "response_format" in kwargs:
                kwargs.pop("response_format", None)
                continue
            raise
    assert last_error is not None
    raise last_error


def parse_json_content(content: str | None) -> dict[str, Any]:
    if not content:
        return {}
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"value": data}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                return data if isinstance(data, dict) else {"value": data}
            except json.JSONDecodeError:
                return {"raw": content}
        return {"raw": content}
