from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .models import ValidationError, dump_model, validate_risk_report
from .rag import INSUFFICIENT_EVIDENCE, RAGContext, RAGService


class AIServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class AIResult:
    content: str
    citations: list[dict[str, Any]]
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    structured: dict[str, Any] | None = None


class AIProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict[str, str]], context: RAGContext) -> AIResult:
        raise NotImplementedError

    @abstractmethod
    def analyze(self, document_text: str, context: RAGContext) -> AIResult:
        raise NotImplementedError

    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError


SYSTEM_PROMPT = """你是上市公司证券合规审阅助手。你只能依据提供的来源和已确认事实作答。
必须区分已确认事实、来源内容、AI推断和待人工确认项。不得编造法规、条款、公司事实、案例、页码或来源。
涉及同比变动时，只有上年同期为正且本期非负才展示“（本期数－上年同期数）÷ 上年同期数 × 100%”。负数之间应按金额绝对值表述为亏损或净流出收窄/扩大；负转正、正转负和上期为零均不得展示传统同比百分比。任何内部 raw_yoy_rate 都不得直接决定增长、下降或涨跌幅文字。
证据不足时必须明确回复“当前知识库未检索到足够直接依据，请人工进一步确认。”
AI仅提供辅助审查，最终结论由证券事务人员确认。"""


class AliyunProvider(AIProvider):
    def __init__(self, settings: Settings):
        if not settings.cloud_configured:
            raise AIServiceError("AI 服务尚未配置，请联系管理员。")
        self.settings = settings
        self.model = settings.aliyun_model

    def name(self) -> str:
        return "aliyun"

    def _endpoint(self) -> str:
        base = self.settings.aliyun_base_url.rstrip("/")
        path = self.settings.aliyun_chat_path
        return base + (path if path.startswith("/") else "/" + path)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.aliyun_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request_error_message(self) -> str:
        return "阿里云 AI 请求失败，请稍后重试。"

    def _request(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> tuple[str, dict[str, int]]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers=self._headers(),
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.settings.request_timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                content = payload["choices"][0]["message"]["content"]
                usage = payload.get("usage", {})
                return str(content), {
                    "input": int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
                    "output": int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
                }
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError) as error:
                last_error = error
                if attempt < 2:
                    time.sleep(0.5 * (2 ** attempt))
        raise AIServiceError(self._request_error_message()) from last_error

    def chat(self, messages: list[dict[str, str]], context: RAGContext) -> AIResult:
        if not context.results:
            return AIResult(INSUFFICIENT_EVIDENCE, [], model=self.model)
        prompt_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        prompt_messages.append({"role": "system", "content": "可用来源：\n" + context.context_text})
        prompt_messages.extend(messages[-12:])
        content, usage = self._request(prompt_messages)
        return AIResult(content, context.citations, usage["input"], usage["output"], self.model)

    @staticmethod
    def _extract_json(value: str) -> Any:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", value.strip(), flags=re.IGNORECASE)
        return json.loads(cleaned)

    def analyze(self, document_text: str, context: RAGContext) -> AIResult:
        del document_text
        if not context.results:
            return AIResult(INSUFFICIENT_EVIDENCE, [], model=self.model)
        schema_instruction = """请输出严格 JSON：
{"summary":"","risk_score":0,"risk_level":"","risks":[{"level":"","type":"","title":"","description":"","evidence":"","source_documents":[],"page":[],"regulation_basis":[],"company_basis":[],"internal_rule_basis":[],"historical_cases":[],"recommendation":"","revision_text":"","confidence":0.5}]}
source_documents 只能选用提供来源，必须带 title、document_id、chunk_id、page、section、content；revision_text 仅在能够给出明确替换句时填写，否则留空。"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": schema_instruction},
            {"role": "system", "content": "可用来源：\n" + context.context_text},
            {"role": "user", "content": "请仅审阅可用来源中的当前审查材料片段，并结合检索到的法规、制度和案例返回结构化风险。"},
        ]
        content, usage = self._request(messages, json_mode=True)
        try:
            report = validate_risk_report(self._extract_json(content))
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            repair_messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "上次输出不符合 JSON Schema。请仅修复格式，不增加未提供的事实或来源。"},
            ]
            repaired, repair_usage = self._request(repair_messages, json_mode=True)
            usage["input"] += repair_usage["input"]
            usage["output"] += repair_usage["output"]
            try:
                report = validate_risk_report(self._extract_json(repaired))
                content = repaired
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
                raise AIServiceError("AI 返回的风险报告格式无法校验，请稍后重试。") from error
        structured = dump_model(report)
        return AIResult(content, context.citations, usage["input"], usage["output"], self.model, structured)


class LocalLLMProvider(AliyunProvider):
    """OpenAI-compatible local LLM endpoint restricted to this computer."""

    def __init__(self, settings: Settings):
        if not settings.local_llm_model:
            raise AIServiceError("本地 LLM 尚未配置，请设置 LOCAL_LLM_MODEL。")
        parsed = urlparse(settings.local_llm_base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise AIServiceError("LOCAL_LLM_BASE_URL 只允许使用本机回环地址。")
        self.settings = settings
        self.model = settings.local_llm_model

    def name(self) -> str:
        return "local_llm"

    def _endpoint(self) -> str:
        base = self.settings.local_llm_base_url.rstrip("/")
        path = self.settings.local_llm_chat_path
        return base + (path if path.startswith("/") else "/" + path)

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "Accept": "application/json"}

    def _request_error_message(self) -> str:
        return "本地 LLM 请求失败，请确认 Ollama 等本机模型服务已经启动。"


class LocalRagProvider(AIProvider):
    def name(self) -> str:
        return "local_rag"

    def chat(self, messages: list[dict[str, str]], context: RAGContext) -> AIResult:
        result = RAGService.local_answer(context)
        return AIResult(result["answer"], result["source_documents"], model="local-rag-retrieval")

    def analyze(self, document_text: str, context: RAGContext) -> AIResult:
        raise AIServiceError("当前处于本地知识检索模式，仅提供资料检索和引用，不提供 AI 推理分析。如需智能分析，请切换 AI 增强模式。")


class MockProvider(AIProvider):
    """Test-only provider; never selected by AI_MODE."""

    def name(self) -> str:
        return "mock"

    def chat(self, messages: list[dict[str, str]], context: RAGContext) -> AIResult:
        return AIResult("DEMO DATA：Mock AI 回答。", context.citations, model="mock")

    def analyze(self, document_text: str, context: RAGContext) -> AIResult:
        return AIResult("DEMO DATA", context.citations, model="mock", structured={"summary": "DEMO DATA", "risk_score": 0, "risk_level": "demo", "risks": []})


def create_ai_provider(settings: Settings) -> AIProvider:
    if settings.ai_mode == "local_rag":
        return LocalRagProvider()
    if settings.ai_mode == "local_llm":
        return LocalLLMProvider(settings)
    return AliyunProvider(settings)
