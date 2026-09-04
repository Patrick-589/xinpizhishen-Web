from __future__ import annotations

import re
import hashlib
from decimal import Decimal
from typing import Any

from ..parsers import ParsedBlock, ParsedDocument, normalize_text
from .extractor import FinancialExtractor
from .formulas import FinancialFormulaEngine
from .financial_cases import annotation_reference, load_financial_cases
from .models import AuditCheck, AuditResult, SourceLocation
from .normalizer import normalize_label
from .normalizer import close_enough, decimal_text


# Bump the persisted-result contract whenever source matching rules change so
# an already completed task is recalculated with the complete comparison set.
ENGINE_VERSION = "1.6.0"
EXTERNAL_SOURCE_ORGANIZATIONS = (
    "国家统计局", "工业和信息化部", "工信部", "最高人民法院", "深圳证券交易所",
    "深交所", "中国证监会", "证监会",
)


def _paragraph_location(document_id: str, block: ParsedBlock) -> SourceLocation:
    identifier = f"paragraph-{block.paragraph_index}"
    return SourceLocation(
        document_id=document_id,
        page=block.page,
        table_id="",
        table_name=block.section,
        row_id=identifier,
        row_label=block.section,
        column_id="",
        column_label="",
        cell_id=identifier,
        paragraph_index=block.paragraph_index,
        source_start=block.source_start,
        source_end=block.source_end,
        source_text=block.text,
    )


class FinancialAuditEngine:
    """Local deterministic financial audit engine. It never calls RAG or an LLM."""

    def __init__(self) -> None:
        self.extractor = FinancialExtractor()
        self.formulas = FinancialFormulaEngine()
        self.financial_cases = load_financial_cases()

    def analyze(
        self,
        parsed: ParsedDocument,
        *,
        document_id: str,
        file_hash: str,
        comparison_parsed: ParsedDocument | None = None,
        comparison_document_id: str | None = None,
        comparison_documents: list[tuple[ParsedDocument, str]] | None = None,
    ) -> AuditResult:
        extracted = self.extractor.extract(parsed, document_id)
        checks: list[AuditCheck] = []
        checks.extend(self.formulas.statement_checks(extracted.tables))
        checks.extend(self.formulas.yoy_checks(extracted.tables))
        checks.extend(self.formulas.profit_ratio_checks(extracted.tables, extracted.facts))
        checks.extend(self.formulas.gross_margin_checks(extracted.tables))
        checks.extend(self.formulas.table_proportion_checks(extracted.tables))
        checks.extend(self.formulas.simple_total_checks(extracted.tables))
        checks.extend(self.formulas.movement_checks(extracted.tables))
        checks.extend(self.formulas.calibrated_reconciliation_checks(extracted.tables, extracted.facts))
        checks.extend(self.formulas.cross_table_checks(extracted.facts))
        checks.extend(self.formulas.required_amount_checks(extracted.tables))
        checks.extend(self.formulas.repeated_fact_checks(extracted.facts))
        checks.extend(self._period_checks(parsed, document_id, extracted.periods))
        checks.extend(self._unit_checks(extracted.tables))
        checks.extend(self._source_checks(parsed, document_id))
        if comparison_documents is None:
            comparison_documents = (
                [(comparison_parsed, comparison_document_id or f"comparison:{comparison_parsed.filename}")]
                if comparison_parsed is not None else []
            )
        for comparison_index, (comparison_document, comparison_id) in enumerate(comparison_documents):
            comparison_extracted = self.extractor.extract(comparison_document, comparison_id)
            cross_document_checks = self._cross_document_checks(
                extracted.facts, comparison_extracted.facts, comparison_document.filename,
            )
            source_suffix = ""
            if len(comparison_documents) > 1:
                # The same metric and cell coordinates can legitimately occur
                # in several supplied workbooks.  Keep each workbook's
                # result distinct so later semantic de-duplication cannot
                # hide a mismatch from a second source.
                source_suffix = hashlib.sha256(
                    comparison_document.filename.encode("utf-8")
                ).hexdigest()[:12]
                for check in cross_document_checks:
                    check.check_id = f"{check.check_id}:{source_suffix}:{comparison_index}"
                    check.inputs.setdefault("spreadsheet_file", comparison_document.filename)
            checks.extend(cross_document_checks)
            authoritative_checks = self.formulas.authoritative_metric_checks(
                extracted.tables, comparison_extracted.tables,
            )
            # The formula checker uses stable metric IDs for a single workbook.
            # Add the source file to IDs when several workbooks are supplied so
            # one workbook cannot silently hide a mismatch in another.
            if len(comparison_documents) > 1:
                for check in authoritative_checks:
                    check.check_id = f"{check.check_id}:{source_suffix}:{comparison_index}"
                    check.inputs.setdefault("spreadsheet_file", comparison_document.filename)
            checks.extend(authoritative_checks)

        # Attach the validated pattern references first.  Anchor-only findings
        # are added afterwards only for annotations not already represented by
        # a deterministic or semantically matched check, preventing duplicate
        # risks for the same confirmed issue.
        checks = self._attach_case_references(checks)
        checks.extend(self._case_anchor_checks(parsed, document_id, checks))
        checks = self._attach_case_references(checks)
        unique: dict[str, AuditCheck] = {}
        for check in self._merge_repeated_semantic_checks(checks):
            unique.setdefault(check.check_id, check)
        ordered = sorted(
            unique.values(),
            key=lambda item: (
                {"failed": 0, "source_issue": 1, "needs_review": 2, "passed": 3}.get(item.status, 4),
                {"high": 0, "medium": 1, "low": 2, "none": 3}.get(item.severity, 4),
                item.category,
                item.title,
            ),
        )
        return AuditResult(
            engine_version=ENGINE_VERSION,
            document_id=document_id,
            filename=parsed.filename,
            file_hash=file_hash,
            status="completed",
            period_registry=extracted.periods,
            checks=ordered,
            facts=extracted.facts,
            tables=extracted.tables,
            external_ai_used=False,
            case_calibration={
                "enabled": bool(self.financial_cases),
                "case_count": len(self.financial_cases),
                "matched_checks": sum(bool(check.case_references) for check in ordered),
                "validated_only": True,
            },
        )

    def _case_anchor_checks(
        self,
        parsed: ParsedDocument,
        document_id: str,
        checks: list[AuditCheck],
    ) -> list[AuditCheck]:
        """Surface validated annotations that have no deterministic numeric rule.

        A confirmed case can contain version or classification findings that
        cannot be inferred from amounts alone.  When the same anchor text is
        present in a later document, keep the finding visible as a traceable
        manual-review item instead of silently dropping the calibration signal.
        """
        if not self.financial_cases:
            return []
        covered_patterns = {
            str(check.inputs.get("case_pattern") or "")
            for check in checks
            if str(check.inputs.get("case_pattern") or "")
        }
        covered_patterns.update(
            str(reference.get("pattern") or "")
            for check in checks
            for reference in check.case_references
            if str(reference.get("pattern") or "")
        )
        results: list[AuditCheck] = []
        for case in self.financial_cases:
            for annotation in case.get("annotations", []):
                if not isinstance(annotation, dict):
                    continue
                pattern = str(annotation.get("pattern") or "")
                if not pattern or pattern in covered_patterns:
                    continue
                anchor = normalize_text(str(annotation.get("anchor_text") or ""))
                if not anchor:
                    continue
                locations: list[SourceLocation] = []
                for block in parsed.blocks:
                    text = normalize_text(block.text)
                    matched = anchor in text
                    if not matched and ("-" in anchor or "−" in anchor):
                        parts = [part for part in re.split(r"[-−]", anchor) if part]
                        matched = len(parts) > 1 and all(part in text for part in parts)
                    if matched:
                        locations.append(_paragraph_location(document_id, block))
                if not locations:
                    continue
                annotation_text = str(annotation.get("text") or "已确认案例标记该处存在问题。")
                check_id = "financial-" + hashlib.sha256(
                    f"CASE-ANCHOR|{case.get('case_id', '')}|{pattern}|{anchor}|{parsed.filename}".encode("utf-8")
                ).hexdigest()[:20]
                results.append(AuditCheck(
                    check_id=check_id,
                    rule_id="VALIDATED-CASE-ANCHOR",
                    status="needs_review",
                    severity="medium",
                    category="已确认案例校准",
                    title=f"已确认案例问题待核：{annotation_text[:80]}",
                    explanation=(
                        f"当前文档包含与已确认案例相同的原文锚点“{anchor}”。"
                        "该案例问题属于版本、分类或其他需结合公司资料核实的判断，系统不据此臆造结论。"
                    ),
                    suggestion="打开原文位置，结合最新关联方清单、制度版本或审批资料人工确认；确认后再标记为已确认或误报。",
                    formula="已确认案例原文锚点命中；需结合现行资料完成判断",
                    inputs={
                        "case_pattern": pattern,
                        "anchor_text": anchor,
                        "case_annotation": annotation_text,
                    },
                    source_locations=locations,
                    source_sufficient=False,
                ))
        return results

    def _attach_case_references(self, checks: list[AuditCheck]) -> list[AuditCheck]:
        """Attach only semantically matching validated case annotations."""
        if not self.financial_cases:
            return checks
        for check in checks:
            # Keep generic remediation wording out of matching: terms such as
            # "尾差" may appear in a suggestion for many unrelated checks.
            haystack = " ".join((check.title, check.explanation, check.formula))
            explicit_pattern = str(check.inputs.get("case_pattern") or "")
            references: list[dict[str, Any]] = []
            for case in self.financial_cases:
                for annotation in case.get("annotations", []):
                    if not isinstance(annotation, dict):
                        continue
                    if explicit_pattern and annotation.get("pattern") == explicit_pattern:
                        references.append(annotation_reference(case, annotation))
                        continue
                    terms = [str(term) for term in annotation.get("match_terms", []) if str(term).strip()]
                    if terms and all(term in haystack for term in terms):
                        references.append(annotation_reference(case, annotation))
            check.case_references = references[:3]
        return checks

    @staticmethod
    def _cross_document_checks(
        primary_facts: list,
        comparison_facts: list,
        comparison_filename: str,
    ) -> list[AuditCheck]:
        """Compare document facts with authoritative spreadsheet facts by meaning."""
        # Financial workbooks commonly repeat the same row on a current-period
        # sheet, an archived sheet and a statement summary.  Matching only the
        # raw canonical name makes those candidates tie; the old implementation
        # then discarded the comparison entirely.  Normalize the small set of
        # accounting aliases here and choose one deterministic, authoritative
        # source below so a real mismatch cannot disappear because of duplicates.
        metric_aliases = (
            ("归属于母公司所有者的净利润", (
                "归属于母公司所有者的净利润", "归属于母公司股东的净利润",
                "归属于上市公司股东的净利润", "归属于上市公司股东净利润",
            )),
            ("资产总计", ("资产总计", "资产总额")),
            ("负债和所有者权益总计", ("负债和所有者权益总计", "负债和所有者权益总额")),
            ("经营活动产生的现金流量净额", (
                "经营活动产生的现金流量净额", "经营活动现金流净额",
            )),
            ("投资活动产生的现金流量净额", (
                "投资活动产生的现金流量净额", "投资活动现金流净额",
            )),
            ("筹资活动产生的现金流量净额", (
                "筹资活动产生的现金流量净额", "筹资活动现金流净额",
            )),
            ("现金及现金等价物净增加额", (
                "现金及现金等价物净增加额", "现金及现金等价物增加额",
            )),
        )

        def metric_key(fact: Any) -> str:
            haystack = normalize_label(f"{fact.canonical_name} {fact.raw_name}")
            for canonical, aliases in metric_aliases:
                if any(normalize_label(alias) in haystack for alias in aliases):
                    return canonical
            return normalize_label(fact.canonical_name)

        periodless_metrics = {"权益法投资收益", "其他非流动金融资产"}
        statement_terms = (
            "资产表", "负债表", "利润表", "现金流量表",
            "股东权益变动表", "所有者权益变动表",
        )
        excluded_primary_context = (
            "补充资料", "收到其他与经营活动有关的现金",
            "支付其他与筹资活动有关的现金", "按欠款方归集",
            "所有权或使用权受限制的资产",
            "重要的合营企业或联营企业",
            "子公司（划分为持有待售的除外）的重要财务信息",
        )

        def is_nested_note_context(context: str) -> bool:
            """Numbered sub-tables are detail disclosures, not statement totals."""
            return bool(re.match(
                r"^[（(]\s*[一二三四五六七八九十0-9]+[）)]",
                str(context or ""),
            ))

        def is_statement_context(context: str) -> bool:
            normalized = normalize_label(context)
            return any(term in normalized for term in statement_terms)

        def is_aggregate_fact(fact: Any) -> bool:
            label = normalize_label(fact.raw_name)
            return label in {"合计", "小计", "总计"} or label.endswith("合计")

        def grouped(facts: list, *, primary: bool) -> dict[tuple[str, str], list[Any]]:
            result: dict[tuple[str, str], list[Any]] = {}
            for fact in facts:
                if fact.unit == "%" or fact.value is None:
                    continue
                context = str(fact.location.table_name or "")
                if primary and any(term in context for term in excluded_primary_context):
                    continue
                name = metric_key(fact)
                if not name or name in {
                    "项目", "金额", "比例", "其他", "合计", "小计", "总计",
                    "本期增加金额", "本年增加金额", "单位", "序号",
                }:
                    continue
                if primary:
                    raw_name = normalize_label(fact.raw_name)
                    # Keep descriptive note rows (for example
                    # "单项计提坏账准备的应收账款") in scope.  The previous
                    # exact-name gate silently dropped these rows even when
                    # the workbook contained the same fact.  Only discard
                    # obvious headers/date columns; canonical name matching,
                    # period and context ranking below provide the safeguards.
                    if len(raw_name) < 2 or re.fullmatch(r"20\d{2}年.*", raw_name):
                        continue
                # Parsed DOCX notes often omit an explicit unit while the
                # spreadsheet carries "人民币元"; numeric financial cells use
                # 元 as the common base when no other unit is declared.
                key = (name, fact.unit or "元")
                result.setdefault(key, []).append(fact)
            return result

        # Used below to distinguish a note total from its entity-level detail
        # rows.  Both remain in the comparison set; only detail rows are
        # blocked from being compared to a statement aggregate.
        aggregate_scopes = {
            (value.location.table_id, str(value.period or ""))
            for value in primary_facts
            if is_aggregate_fact(value)
        }

        def context_compatible(primary: Any, comparison: Any) -> bool:
            comparison_context = normalize_label(comparison.location.table_name)
            primary_context_raw = str(primary.location.table_name or "")
            primary_context = normalize_label(primary_context_raw)
            # A numbered note sub-table contains entity-level details (for
            # example one customer or one investee).  A statement row with the
            # same label is an aggregate and must never be used as its source.
            if is_nested_note_context(primary_context_raw) and is_statement_context(comparison_context):
                return False
            primary_scope_key = (primary.location.table_id, str(primary.period or ""))
            if (
                primary_scope_key in aggregate_scopes
                and not is_aggregate_fact(primary)
                and not is_statement_context(primary_context_raw)
                and is_statement_context(comparison_context)
            ):
                return False
            if is_statement_context(comparison_context):
                return True
            # Non-statement workbook tabs do not always repeat the exact
            # numbered note heading used by Word.  A same-row-label match is
            # therefore sufficient to admit the candidate; period/scope and
            # the context score still decide which source is authoritative.
            generic = {"附注", "主要项目注释", "项目注释", "财务报表"}
            left = primary_context
            right = comparison_context
            for token in generic:
                left = left.replace(token, "")
                right = right.replace(token, "")
            left = re.sub(r"\d+", "", left).strip()
            right = re.sub(r"\d+", "", right).strip()
            raw_match = normalize_label(primary.raw_name) == normalize_label(comparison.raw_name)
            return raw_match or bool(left and right and (left in right or right in left))

        def report_year(facts: list) -> str:
            years: list[str] = []
            for fact in facts:
                for value in (str(fact.period or ""), str(fact.location.column_label or "")):
                    years.extend(re.findall(r"(20\d{2})年", value))
            return max(years, default="")

        primary_report_year = report_year(primary_facts)

        def period_key(fact: Any) -> str:
            period = str(fact.period or "")
            label = normalize_label(fact.location.column_label)
            if period in {"current_period", "comparative_period", "current_end", "prior_year_end"}:
                return period
            date = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", label)
            if date:
                return f"balance:{date.group(1)}-{int(date.group(2)):02d}-{int(date.group(3)):02d}"
            year = re.search(r"(20\d{2})年", label or period)
            if year and any(term in label for term in ("月金额", "月发生额", "月")):
                return f"flow:{year.group(1)}"
            return period

        def period_score(primary: Any, comparison: Any) -> int | None:
            left_key = period_key(primary)
            right_key = period_key(comparison)
            if left_key and left_key == right_key:
                return 30
            if left_key == "current_period" and right_key.startswith("flow:"):
                return 24 if not primary_report_year or right_key == f"flow:{primary_report_year}" else None
            if right_key == "current_period" and left_key.startswith("flow:"):
                return 24 if not primary_report_year or left_key == f"flow:{primary_report_year}" else None
            if left_key == "current_end" and right_key.startswith("balance:"):
                return 24
            if right_key == "current_end" and left_key.startswith("balance:"):
                return 24
            metric = str(primary.canonical_name)
            # Some financial working papers omit a period in both the table
            # header and the workbook sheet (for example a single-period
            # allowance schedule).  Once scope and table context are already
            # compatible, treating two missing period labels as comparable is
            # safer than silently dropping every mismatch in that table.
            if not left_key and not right_key:
                # Period-less rows are only comparable when the workbook
                # source is a current working sheet.  Historical tabs such as
                # X0/X1/2002 carry the same row labels but must not be used as
                # a substitute for a current-period value.
                archive_context = normalize_label(
                    comparison.location.table_name or comparison.location.sheet_name
                )
                if (
                    re.match(r"^[xX]\d", archive_context)
                    or re.search(r"(?:19|20)\d{2}", archive_context)
                    or any(term in archive_context for term in ("抵消分录", "工作底稿", "归档", "历史"))
                ):
                    return None
                return 8
            if not left_key or not right_key:
                return 6 if metric in periodless_metrics else None
            return None

        def scope_score(primary: Any, comparison: Any) -> int | None:
            left_scope = primary.statement_scope
            right_scope = comparison.statement_scope
            if left_scope == right_scope:
                return 20
            # A workbook often labels its note worksheet simply by the note
            # name, which the extractor classifies as disclosure rather than
            # note.  Treat those scopes as equivalent before falling back to
            # a statement row, otherwise the statement value can hide the
            # actual note mismatch.
            left_is_note_context = not is_statement_context(primary.location.table_name)
            right_is_note_context = not is_statement_context(comparison.location.table_name)
            if (
                left_is_note_context and right_is_note_context
                and left_scope in {"parent", "note", "disclosure"}
                and right_scope in {"parent", "note", "disclosure"}
            ):
                return 18
            if right_scope in {"note", "disclosure"} and left_scope == "consolidated":
                return 10
            if left_scope in {"note", "disclosure"} and right_scope == "consolidated":
                return 12
            if left_scope == "disclosure" and right_scope == "parent":
                return 8
            return None

        left = grouped(primary_facts, primary=True)
        right = grouped(comparison_facts, primary=False)

        def source_priority(fact: Any, metric: str) -> tuple[int, int, int]:
            """Prefer the current authoritative statement over workbook copies."""
            context = normalize_label(fact.location.table_name or fact.location.sheet_name)
            score = 0
            # Archived workbook tabs in the supplied templates are commonly
            # prefixed X0/X1.  They remain searchable, but the unprefixed tab
            # is the current working paper and must win a tie.
            if not re.match(r"^[xX]\d", context):
                score += 20
            statement_map = {
                "营业收入": ("利润表", "损益表"),
                "营业利润": ("利润表", "损益表"),
                "净利润": ("利润表", "损益表"),
                "归属于母公司所有者的净利润": ("利润表", "损益表"),
                "资产总计": ("资产负债表", "资产表"),
                "负债合计": ("资产负债表", "负债表"),
                "货币资金": ("资产负债表", "资产表"),
                "经营活动产生的现金流量净额": ("现金流量表", "现金流"),
                "投资活动产生的现金流量净额": ("现金流量表", "现金流"),
                "筹资活动产生的现金流量净额": ("现金流量表", "现金流"),
                "现金及现金等价物净增加额": ("现金流量表", "现金流"),
            }
            expected = statement_map.get(metric, ())
            if expected and any(term in context for term in expected):
                score += 15
            if normalize_label(metric) in context:
                score += 4
            # Return stable tie-break components rather than relying on the
            # database/workbook iteration order.
            return score, len(context), len(str(fact.location.cell_id or ""))

        def candidate_rank(primary: Any, comparison: Any) -> tuple[Any, ...] | None:
            period_points = period_score(primary, comparison)
            scope_points = scope_score(primary, comparison)
            if period_points is None or scope_points is None:
                return None
            metric = metric_key(primary)
            primary_context = normalize_label(primary.location.table_name)
            primary_context_raw = str(primary.location.table_name or "")
            comparison_context = normalize_label(comparison.location.table_name)
            context_points = 0
            primary_raw = normalize_label(primary.raw_name)
            comparison_raw = normalize_label(comparison.raw_name)
            if primary_raw == comparison_raw:
                context_points += 12
            primary_is_statement = is_statement_context(primary_context)
            comparison_is_statement = is_statement_context(comparison_context)
            primary_is_nested = is_nested_note_context(primary_context_raw)
            if primary_is_statement == comparison_is_statement:
                context_points += 8
            if primary_is_nested and not comparison_is_statement:
                context_points += 18
            if primary_context == comparison_context:
                context_points += 16
            elif primary_context and comparison_context and (
                primary_context in comparison_context or comparison_context in primary_context
            ):
                context_points += 10
            if metric in primary_context:
                context_points += 3
            if metric in comparison_context:
                context_points += 3
            priority = source_priority(comparison, metric)
            exact = 1 if close_enough(primary.value, comparison.value) else 0
            distance = abs(primary.value - comparison.value)
            # Source authority precedes exact-value preference.  Otherwise an
            # archived sheet containing the old (matching) value could hide a
            # mismatch in the current authoritative sheet.
            # Context/scope must precede value proximity: an old statement
            # copy that happens to match numerically must not mask a differing
            # value in the same note worksheet.
            return (period_points, scope_points, context_points, priority, exact, -distance)

        checks: list[AuditCheck] = []
        pairs: list[tuple[Any, Any]] = []
        for key in sorted(set(left) & set(right)):
            primary_group: list[Any] = []
            seen_primary: set[tuple[str, str, str, Decimal]] = set()
            for fact in left[key]:
                identity = (
                    fact.statement_scope,
                    fact.period,
                    fact.location.table_name,
                    fact.value,
                )
                if identity in seen_primary:
                    continue
                seen_primary.add(identity)
                primary_group.append(fact)
            comparison_group = list(right[key])
            for primary in primary_group:
                candidates: list[tuple[tuple[Any, ...], Any]] = []
                for comparison in comparison_group:
                    if not context_compatible(primary, comparison):
                        continue
                    rank = candidate_rank(primary, comparison)
                    if rank is not None:
                        candidates.append((rank, comparison))
                if not candidates:
                    continue
                candidates.sort(key=lambda item: item[0], reverse=True)
                best_score = candidates[0][0]
                best = [item for score, item in candidates if score == best_score]
                # There can still be byte-for-byte duplicate workbook rows;
                # select the stable first location rather than dropping the
                # check.  Distinct values have already been ranked by their
                # authoritative sheet and numeric distance.
                best.sort(key=lambda item: (
                    str(item.location.table_id or ""),
                    str(item.location.cell_id or ""),
                ))
                pairs.append((primary, best[0]))

        for primary, comparison in pairs:
            period = primary.period
            locations = [primary.location, comparison.location]
            same = close_enough(primary.value, comparison.value)
            period_label = {
                "current_period": "本期",
                "comparative_period": "上年同期",
                "current_end": "期末",
                "prior_year_end": "期初/上年末",
            }.get(period, period or "期间未标明")
            context = primary.location.table_name or comparison.location.sheet_name or comparison.location.table_name
            context_label = f" · {context}" if context else ""
            metric_name = (
                metric_key(primary)
                if normalize_label(primary.raw_name) in {"合计", "小计", "总计"}
                else primary.raw_name
            )
            title = f"文档与 Excel 勾稽：{metric_name}（{period_label}{context_label}）"
            difference = comparison.value - primary.value
            check_id = "financial-" + hashlib.sha256(
                f"CROSS-DOCUMENT-FACT|{title}|{primary.location.cell_id}|{comparison.location.cell_id}".encode("utf-8")
            ).hexdigest()[:20]
            case_pattern = ""
            if primary.canonical_name == "权益法投资收益":
                if primary.statement_scope == "parent":
                    case_pattern = "parent_statement_reconciliation"
                elif "长期股权投资" in primary.location.table_name:
                    case_pattern = "cross_table_investment_income"
                else:
                    case_pattern = "equity_method_income_reconciliation"
            elif primary.canonical_name == "长期股权投资" and primary.statement_scope == "parent":
                case_pattern = "opening_balance_reconciliation"
            elif (
                primary.canonical_name == "其他非流动金融资产"
                and "期末公允价值" in primary.location.table_name
            ):
                case_pattern = "fair_value_reconciliation"
            checks.append(AuditCheck(
                check_id=check_id,
                rule_id="CROSS-DOCUMENT-FACT",
                status="passed" if same else "failed",
                severity="none" if same else "high",
                category="文档与 Excel 勾稽",
                title=("已核对无误：" if same else "文档与 Excel 金额不一致：") + title,
                explanation=(
                    f"文档列示 {decimal_text(primary.value)}，Excel（{comparison_filename}）列示 "
                    f"{decimal_text(comparison.value)}，差异 {decimal_text(difference)}。"
                ),
                suggestion=(
                    "无需修改。"
                    if same else
                    "逐项核对文档与 Excel 的期间、合并范围、单位和正负号；确认口径一致后统一修正，并保留勾稽底稿。"
                ),
                formula="文档同一指标金额 = Excel 同一指标金额（Decimal，单位统一为元）",
                reported_value=primary.value,
                calculated_value=comparison.value,
                difference=difference,
                inputs={
                    "document_value": primary.value,
                    "spreadsheet_value": comparison.value,
                    "period": period,
                    "document_statement_scope": primary.statement_scope,
                    "spreadsheet_statement_scope": comparison.statement_scope,
                    "spreadsheet_file": comparison_filename,
                    "case_pattern": case_pattern,
                },
                source_locations=locations,
                source_sufficient=True,
            ))
        return checks

    @staticmethod
    def _merge_repeated_semantic_checks(checks: list[AuditCheck]) -> list[AuditCheck]:
        """Collapse repeated disclosures of one semantic YoY issue without losing provenance."""
        merged: list[AuditCheck] = []
        indexes: dict[tuple[Any, ...], int] = {}
        for check in checks:
            if check.rule_id != "YOY-NEGATIVE-SEMANTICS":
                merged.append(check)
                continue
            key = (
                check.rule_id,
                check.status,
                check.severity,
                normalize_label(check.title),
                str(check.reported_value),
                str(check.calculated_value),
                str(check.inputs.get("current")),
                str(check.inputs.get("previous")),
                str(check.inputs.get("change_type")),
                str(check.inputs.get("semantic")),
            )
            existing_index = indexes.get(key)
            if existing_index is None:
                indexes[key] = len(merged)
                merged.append(check)
                continue
            existing = merged[existing_index]
            location_keys = {
                (location.cell_id, location.source_start, location.source_end)
                for location in existing.source_locations
            }
            for location in check.source_locations:
                location_key = (location.cell_id, location.source_start, location.source_end)
                if location_key not in location_keys:
                    existing.source_locations.append(location)
                    location_keys.add(location_key)
        return merged

    @staticmethod
    def issue_risks(result: AuditResult, *, include_needs_review: bool = False) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []
        for check in result.checks:
            if check.status == "passed" or (check.status == "needs_review" and not include_needs_review):
                continue
            locations = [
                {
                    "label": location.row_label or location.table_name or check.title,
                    "page": location.page,
                    "section": location.table_name,
                    "paragraphIndex": location.paragraph_index,
                    "text": location.source_text,
                    "tableId": location.table_id,
                    "rowId": location.row_id,
                    "columnId": location.column_id,
                    "cellId": location.cell_id,
                    "column": location.column_label,
                    "sourceStart": location.source_start,
                    "sourceEnd": location.source_end,
                    "spreadsheetRow": location.spreadsheet_row,
                    "sheetName": location.sheet_name,
                    "documentId": location.document_id,
                }
                for location in check.source_locations
            ]
            first = check.source_locations[0] if check.source_locations else None
            calculation = {
                "check_id": check.check_id,
                "rule_id": check.rule_id,
                "status": check.status,
                "formula": check.formula,
                "reported_value": str(check.reported_value) if check.reported_value is not None else None,
                "calculated_value": str(check.calculated_value) if check.calculated_value is not None else None,
                "difference": str(check.difference) if check.difference is not None else None,
                "inputs": {key: str(value) if isinstance(value, Decimal) else value for key, value in check.inputs.items()},
                "source_sufficient": check.source_sufficient,
                "engine_version": result.engine_version,
            }
            risks.append({
                "id": check.check_id,
                "level": check.severity if check.severity in {"high", "medium", "low"} else "needs_review",
                "type": "财务数据勾稽审计",
                "title": check.title,
                "description": check.explanation,
                "evidence": "\n".join(location.source_text for location in check.source_locations),
                "source_text": first.source_text if first else "",
                "page": first.page if first else None,
                "section": first.table_name if first else "财务数据勾稽审计",
                "paragraph_index": first.paragraph_index if first else 0,
                "location": {
                    "page": first.page if first else None,
                    "section": first.table_name if first else "财务数据勾稽审计",
                    "paragraph": (first.paragraph_index + 1) if first else None,
                    "items": locations,
                },
                "regulation_basis": [],
                "company_basis": [],
                "internal_rule_basis": [],
                "historical_cases": check.case_references,
                "source_documents": [],
                "recommendation": check.suggestion,
                "confidence": 0.99 if check.status == "failed" else 0.78,
                "calculation": calculation,
            })
        return risks

    @staticmethod
    def payload_issue_risks(payload: dict[str, Any], *, include_needs_review: bool = False) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []
        engine_version = str(payload.get("engineVersion") or ENGINE_VERSION)
        for check in payload.get("checks", []):
            if not isinstance(check, dict):
                continue
            status = str(check.get("status") or "")
            if status == "passed" or (status == "needs_review" and not include_needs_review):
                continue
            raw_locations = [item for item in check.get("source_locations", []) if isinstance(item, dict)]
            locations = [{
                "label": item.get("row_label") or item.get("table_name") or check.get("title"),
                "page": item.get("page"),
                "section": item.get("table_name", ""),
                "paragraphIndex": item.get("paragraph_index", 0),
                "text": item.get("source_text", ""),
                "tableId": item.get("table_id", ""),
                "rowId": item.get("row_id", ""),
                "columnId": item.get("column_id", ""),
                "cellId": item.get("cell_id", ""),
                "column": item.get("column_label", ""),
                "sourceStart": item.get("source_start", 0),
                "sourceEnd": item.get("source_end", 0),
                "spreadsheetRow": item.get("spreadsheet_row"),
                "sheetName": item.get("sheet_name", ""),
                "documentId": item.get("document_id", ""),
            } for item in raw_locations]
            first = raw_locations[0] if raw_locations else {}
            risks.append({
                "id": str(check.get("check_id") or ""),
                "level": check.get("severity") if check.get("severity") in {"high", "medium", "low"} else "needs_review",
                "type": "财务数据勾稽审计",
                "title": str(check.get("title") or "待复核财务问题"),
                "description": str(check.get("explanation") or ""),
                "evidence": "\n".join(str(item.get("source_text") or "") for item in raw_locations),
                "source_text": str(first.get("source_text") or ""),
                "page": first.get("page"),
                "section": str(first.get("table_name") or "财务数据勾稽审计"),
                "paragraph_index": int(first.get("paragraph_index") or 0),
                "location": {
                    "page": first.get("page"),
                    "section": str(first.get("table_name") or "财务数据勾稽审计"),
                    "paragraph": (int(first.get("paragraph_index") or 0) + 1) if first else None,
                    "items": locations,
                },
                "regulation_basis": [],
                "company_basis": [],
                "internal_rule_basis": [],
                "historical_cases": check.get("case_references", []),
                "source_documents": [],
                "recommendation": str(check.get("suggestion") or "请人工进一步确认。"),
                "confidence": 0.99 if status == "failed" else 0.78,
                "calculation": {
                    "check_id": check.get("check_id"),
                    "rule_id": check.get("rule_id"),
                    "status": status,
                    "formula": check.get("formula"),
                    "reported_value": check.get("reported_value"),
                    "calculated_value": check.get("calculated_value"),
                    "difference": check.get("difference"),
                    "inputs": check.get("inputs", {}),
                    "source_sufficient": bool(check.get("source_sufficient")),
                    "engine_version": engine_version,
                },
            })
        return risks

    @staticmethod
    def _period_checks(parsed: ParsedDocument, document_id: str, periods) -> list[AuditCheck]:
        block = parsed.blocks[0]
        location = _paragraph_location(document_id, block)
        if periods.period_start and periods.period_end:
            title = "已核对无误：报告期识别"
            explanation = f"已识别报告期 {periods.period_start} 至 {periods.period_end}，报告期末 {periods.as_of_date}，上年度末 {periods.prior_year_end}。"
            status, severity = "passed", "none"
            suggestion = "后续所有期末、期初、本期和上年同期取数均按该期间登记。"
        else:
            title = "报告期无法确定"
            explanation = "文件名和正文未形成可验证的报告期登记，无法自动核对本期、上期和期末口径。"
            status, severity = "needs_review", "medium"
            suggestion = "确认报告类型、报告期起止日、报告期末和上年度末。"
        return [AuditCheck(
            check_id=f"financial-period-{document_id}",
            rule_id="PERIOD-REGISTRY",
            status=status,
            severity=severity,
            category="日期",
            title=title,
            explanation=explanation,
            suggestion=suggestion,
            formula="报告类型 -> 报告期/比较期/时点登记",
            source_locations=[location],
            source_sufficient=status == "passed",
        )]

    @staticmethod
    def _unit_checks(tables) -> list[AuditCheck]:
        checks: list[AuditCheck] = []
        for table in tables:
            units: set[str] = set()
            for cell in table.cells:
                if cell.normalized_value is None or cell.is_percentage:
                    continue
                context = f"{cell.row_label} {cell.column_label} {cell.raw_text}"
                if "亿元" in context:
                    units.add("亿元")
                elif "万元" in context:
                    units.add("万元")
                elif re.search(r"(?:人民币)?元(?:[^/股]|$)", context):
                    units.add("元")
            if len(units) <= 1:
                continue
            location = next((cell.location for cell in table.cells if cell.raw_text), None)
            if location is None:
                continue
            checks.append(AuditCheck(
                check_id=f"financial-unit-{table.table_id}",
                rule_id="UNIT-CONSISTENCY",
                status="needs_review",
                severity="medium",
                category="单位",
                title=f"同表存在多个金额单位：{table.name}",
                explanation=f"同一表格中识别到 {'、'.join(sorted(units))}。系统已分别换算为元，但需确认是否为有意设置。",
                suggestion="核对表头单位、各行单位和金额数量级；不同单位属于合理口径时应在表内明确标注。",
                formula="原始金额 * 单位换算因子 = 元",
                source_locations=[location],
                source_sufficient=False,
            ))
        return checks

    @staticmethod
    def _source_checks(parsed: ParsedDocument, document_id: str) -> list[AuditCheck]:
        checks: list[AuditCheck] = []
        for block in parsed.blocks:
            if block.block_type == "table" or len(block.text) > 800:
                continue
            organization = next((name for name in EXTERNAL_SOURCE_ORGANIZATIONS if name in block.text), None)
            if organization is None or not re.search(r"(?:数据显示|发布|统计|报告指出|资料显示)", block.text):
                continue
            has_date = bool(re.search(r"20\d{2}年(?:\d{1,2}月)?", block.text))
            has_document = bool(re.search(r"《[^》]{2,80}》|https?://|[（(]?[\u4e00-\u9fff]{1,8}\[?20\d{4}\]?\d+号", block.text))
            if has_date and has_document:
                continue
            location = _paragraph_location(document_id, block)
            check_id = f"financial-source-{block.paragraph_index}"
            checks.append(AuditCheck(
                check_id=check_id,
                rule_id="SOURCE-SUFFICIENCY",
                status="source_issue",
                severity="medium",
                category="来源",
                title=f"外部数据来源信息不足：{organization}",
                explanation="原文引用了外部机构数据，但当前段落未同时提供可核验的文件名称/链接和统计日期。",
                suggestion="补充来源机构、文件标题、发布日期、统计时点和可访问链接；禁止由系统补造来源。",
                formula="来源机构 + 来源标题/链接 + 发布日期 + 统计日期",
                source_locations=[location],
                source_sufficient=False,
            ))
        return checks


__all__ = ["ENGINE_VERSION", "FinancialAuditEngine"]
