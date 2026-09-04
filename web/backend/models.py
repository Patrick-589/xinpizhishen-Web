from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError


class SourceDocument(BaseModel):
    title: str
    document_id: str = ""
    chunk_id: str = ""
    source: str = ""
    source_url: str = ""
    date: str = ""
    version: str = ""
    page: int | None = None
    section: str = ""
    document_type: str = ""
    content: str = ""
    score: float = 0


class RiskItem(BaseModel):
    level: str
    type: str
    title: str
    description: str
    evidence: str = ""
    source_documents: list[SourceDocument] = Field(default_factory=list)
    page: list[int] = Field(default_factory=list)
    regulation_basis: list[dict[str, Any] | str] = Field(default_factory=list)
    company_basis: list[dict[str, Any] | str] = Field(default_factory=list)
    internal_rule_basis: list[dict[str, Any] | str] = Field(default_factory=list)
    historical_cases: list[dict[str, Any] | str] = Field(default_factory=list)
    recommendation: str
    revision_text: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)


class RiskReport(BaseModel):
    summary: str
    risk_score: int = Field(ge=0, le=100)
    risk_level: str
    risks: list[RiskItem]


def validate_risk_report(value: Any) -> RiskReport:
    if hasattr(RiskReport, "model_validate"):
        return RiskReport.model_validate(value)
    return RiskReport.parse_obj(value)


def dump_model(value: BaseModel) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value.dict()


__all__ = ["RiskReport", "RiskItem", "SourceDocument", "ValidationError", "validate_risk_report", "dump_model"]
