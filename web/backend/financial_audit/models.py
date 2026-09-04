from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class SourceLocation:
    document_id: str
    page: int | None
    table_id: str
    table_name: str
    row_id: str
    row_label: str
    column_id: str
    column_label: str
    cell_id: str
    paragraph_index: int
    source_start: int
    source_end: int
    source_text: str
    spreadsheet_row: int | None = None
    sheet_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FinancialCell:
    cell_id: str
    document_id: str
    table_id: str
    table_name: str
    row_id: str
    row_index: int
    row_label: str
    column_id: str
    column_index: int
    column_label: str
    raw_text: str
    normalized_value: Decimal | None
    original_unit: str
    normalized_unit: str
    base_amount: Decimal | None
    is_percentage: bool
    period: str
    location: SourceLocation

    def to_dict(self) -> dict[str, Any]:
        return _json_value(asdict(self))


@dataclass
class FinancialTable:
    table_id: str
    document_id: str
    name: str
    page: int | None
    section: str
    paragraph_index: int
    rows: list[list[str]]
    row_labels: list[str]
    column_labels: list[str]
    cells: list[FinancialCell]
    unit: str = ""
    source_text: str = ""

    def row_cells(self, row_index: int) -> list[FinancialCell]:
        return sorted(
            (cell for cell in self.cells if cell.row_index == row_index),
            key=lambda item: item.column_index,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "document_id": self.document_id,
            "name": self.name,
            "page": self.page,
            "section": self.section,
            "paragraph_index": self.paragraph_index,
            "row_count": len(self.rows),
            "column_count": max((len(row) for row in self.rows), default=0),
            "unit": self.unit,
        }


@dataclass(frozen=True)
class FinancialFact:
    fact_id: str
    canonical_name: str
    raw_name: str
    value: Decimal
    unit: str
    period: str
    statement_scope: str
    location: SourceLocation

    def to_dict(self) -> dict[str, Any]:
        return _json_value(asdict(self))


@dataclass
class AuditCheck:
    check_id: str
    rule_id: str
    status: str
    severity: str
    category: str
    title: str
    explanation: str
    suggestion: str
    formula: str = ""
    reported_value: Decimal | str | None = None
    calculated_value: Decimal | str | None = None
    difference: Decimal | str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    source_locations: list[SourceLocation] = field(default_factory=list)
    source_sufficient: bool = True
    case_references: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _json_value(asdict(self))


@dataclass
class PeriodRegistry:
    report_type: str = ""
    period_start: str = ""
    period_end: str = ""
    as_of_date: str = ""
    comparative_start: str = ""
    comparative_end: str = ""
    prior_year_end: str = ""
    approval_date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditResult:
    engine_version: str
    document_id: str
    filename: str
    file_hash: str
    status: str
    period_registry: PeriodRegistry
    checks: list[AuditCheck]
    facts: list[FinancialFact]
    tables: list[FinancialTable]
    external_ai_used: bool = False
    case_calibration: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> dict[str, Any]:
        counts = {
            "total": len(self.checks),
            "passed": 0,
            "exceptions": 0,
            "severe": 0,
            "needs_review": 0,
            "source_issues": 0,
        }
        for check in self.checks:
            if check.status == "passed":
                counts["passed"] += 1
            else:
                counts["exceptions"] += 1
            if check.status == "failed" and check.severity == "high":
                counts["severe"] += 1
            if check.status == "needs_review":
                counts["needs_review"] += 1
            if check.status == "source_issue":
                counts["source_issues"] += 1
        counts["tables_scanned"] = len(self.tables)
        counts["facts_extracted"] = len(self.facts)
        return counts

    def to_dict(self, *, include_facts: bool = False) -> dict[str, Any]:
        value = {
            "engineVersion": self.engine_version,
            "documentId": self.document_id,
            "filename": self.filename,
            "fileHash": self.file_hash,
            "status": self.status,
            "summary": self.summary,
            "periodRegistry": self.period_registry.to_dict(),
            "checks": [check.to_dict() for check in self.checks],
            "tables": [table.to_dict() for table in self.tables],
            "externalAiUsed": self.external_ai_used,
            "caseCalibration": self.case_calibration,
        }
        if include_facts:
            value["facts"] = [fact.to_dict() for fact in self.facts]
        return value


__all__ = [
    "AuditCheck",
    "AuditResult",
    "FinancialCell",
    "FinancialFact",
    "FinancialTable",
    "PeriodRegistry",
    "SourceLocation",
]
