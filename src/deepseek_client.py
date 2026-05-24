from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

from .prompts import build_classification_messages, build_expansion_messages, build_repair_messages

DEFAULT_MODEL = "deepseek-v4-pro"


def get_deepseek_client() -> OpenAI | None:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def call_deepseek(messages: list[dict[str, str]], model: str = DEFAULT_MODEL) -> tuple[str, bool, str]:
    client = get_deepseek_client()
    if client is None:
        return "", False, "环境变量 DEEPSEEK_API_KEY 未设置，已跳过API调用。"
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )
        return response.choices[0].message.content or "", True, ""
    except Exception as exc:  # noqa: BLE001 - UI needs graceful fallback
        return "", False, f"DeepSeek API调用失败: {exc}"


def call_expansion(target_disease: str, user_notes: str, available_source_types: list[str], available_diagnosis_types: list[str]) -> tuple[str, bool, str]:
    return call_deepseek(build_expansion_messages(target_disease, user_notes, available_source_types, available_diagnosis_types))


def call_classification_batch(target_disease: str, expansion_json: dict[str, Any], candidate_type: str, candidate_batch: list[dict[str, Any]], user_notes: str) -> tuple[str, bool, str]:
    return call_deepseek(build_classification_messages(target_disease, expansion_json, candidate_type, candidate_batch, user_notes))


def call_json_repair(bad_json_text: str) -> tuple[str, bool, str]:
    return call_deepseek(build_repair_messages(bad_json_text))
