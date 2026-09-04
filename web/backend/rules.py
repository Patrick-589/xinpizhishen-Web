from __future__ import annotations

import re
import uuid
from typing import Any

from .parsers import ParsedDocument
from .related_transaction_audit import analyze_major_related_transactions


MAX_RULE_RISKS = 160


def _excerpt(text: str, match: re.Match[str] | None = None, limit: int = 180) -> str:
    if len(text) <= limit:
        return text
    center = match.start() if match else 0
    start = max(0, center - 50)
    end = min(len(text), start + limit)
    return ("..." if start else "") + text[start:end] + ("..." if end < len(text) else "")


class DeterministicRuleEngine:
    def analyze(self, parsed: ParsedDocument, task_type: str) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []

        def add(
            title: str,
            risk_type: str,
            level: str,
            paragraph_index: int,
            source_text: str,
            description: str,
            recommendation: str,
            confidence: float,
            regulation_basis: list[dict[str, Any]] | None = None,
            original_locations: list[dict[str, Any]] | None = None,
        ) -> None:
            block = parsed.blocks[max(0, min(paragraph_index, len(parsed.blocks) - 1))]
            location_items = original_locations or [{
                "label": title,
                "page": block.page,
                "section": block.section,
                "paragraphIndex": block.paragraph_index,
                "text": source_text,
            }]
            risks.append({
                "id": str(uuid.uuid4()),
                "level": level,
                "type": risk_type,
                "title": title,
                "description": description,
                "evidence": source_text,
                "source_text": source_text,
                "page": block.page,
                "section": block.section,
                "paragraph_index": block.paragraph_index,
                "location": {
                    "page": block.page,
                    "section": block.section,
                    "paragraph": block.paragraph_index + 1,
                    "items": location_items,
                },
                "regulation_basis": regulation_basis or [],
                "company_basis": [],
                "internal_rule_basis": [],
                "historical_cases": [],
                "source_documents": [],
                "recommendation": recommendation,
                "confidence": confidence,
            })

        numeric_pattern = re.compile(
            r"(?:总规模|总金额|交易金额)[^0-9]{0,20}([0-9][0-9,.]*)\s*万元"
            r".*?(?:出资|支付|投资金额)[^0-9]{0,20}([0-9][0-9,.]*)\s*万元"
            r".*?占[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)%"
        )
        absolute_pattern = re.compile(
            r"必然|一定会|完全不会|零风险|无任何风险|"
            r"(?:确保|保证|承诺)(?=[^。；\n]{0,36}(?:未来|增长|盈利|收益|回报|业绩|目标|成功|完成|实现|达到))"
        )
        date_pattern = re.compile(r"(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})日?")

        for block in parsed.blocks:
            paragraph = block.text
            numeric_match = numeric_pattern.search(paragraph)
            if numeric_match:
                try:
                    total = float(numeric_match.group(1).replace(",", ""))
                    amount = float(numeric_match.group(2).replace(",", ""))
                    disclosed = float(numeric_match.group(3))
                    calculated = amount / total * 100 if total else 0
                    if total and abs(calculated - disclosed) >= 0.2:
                        add(
                            "金额与比例可能不一致", "数据一致性", "high", block.paragraph_index,
                            _excerpt(paragraph, numeric_match),
                            f"按文中金额计算的比例约为 {calculated:.2f}%，与披露的 {disclosed:.2f}% 不一致。",
                            "核对总金额、出资金额和披露比例，并同步检查协议、决议及公告中的相同数字。",
                            0.98,
                        )
                except ValueError:
                    pass
            absolute_match = absolute_pattern.search(paragraph)
            if absolute_match:
                add(
                    "绝对化或确定性表述", "表述风险", "medium", block.paragraph_index,
                    _excerpt(paragraph, absolute_match),
                    f"检测到“{absolute_match.group(0)}”等确定性措辞，相关结果可能受未来条件影响。",
                            "先判断该表述是否属于对未来经营结果的预测或保证。若只是对已发生事实、履职过程或制度要求的客观描述，可标记为误报；若涉及未来结果，应删除绝对化措辞，并补充实现条件、不确定性和风险提示。",
                    0.88,
                )
            for match in date_pattern.finditer(paragraph):
                try:
                    _, month, day = map(int, match.groups())
                    if not 1 <= month <= 12 or not 1 <= day <= 31:
                        add(
                            "日期格式或数值异常", "期限与日期", "high", block.paragraph_index,
                            _excerpt(paragraph, match), "检测到无效日期，可能影响披露期限或文件一致性。",
                            "核对日期原文，并检查审批、签署和披露时间链。", 0.99,
                        )
                except ValueError:
                    pass
            if len(risks) >= MAX_RULE_RISKS:
                break

        full_text = "\n".join(parsed.paragraphs)
        anchor = _excerpt(parsed.paragraphs[0])
        if (parsed.scanned_suspected and not parsed.ocr_used) or len(full_text) < 200:
            add(
                "文档解析完整性待确认", "解析完整性", "needs_review", 0, anchor,
                "提取到的正文较少，文件可能为扫描件、仅含图片或内容不完整。",
                "核对原始文件是否清晰完整；扫描件由 Windows 本地 OCR 处理后仍需人工抽查。", 0.95,
            )
        if "定期报告" not in task_type and any(
            term in full_text for term in ("交易", "投资", "合同", "股权", "收购", "出售")
        ) and not any(
            term in full_text for term in ("风险提示", "风险因素", "特别提示")
        ):
            add(
                "风险提示章节待确认", "信息完整性", "needs_review", 0, anchor,
                "文档涉及交易或投资事项，但未检索到风险提示相关章节标题。",
                "结合文件类型和有效规则，人工确认是否需要补充风险提示及具体披露内容。", 0.72,
            )
        if "关联交易" in full_text and not any(term in full_text for term in ("关联关系", "关联方基本情况", "关联人介绍")):
            add(
                "关联关系说明待补充", "关联交易", "needs_review", 0, anchor,
                "文档出现“关联交易”，但未检索到明确的关联关系或关联方基本情况说明。",
                "核对交易对方、控制链条、关联关系形成原因和回避表决信息。", 0.78,
            )
        if "公告" in task_type and "备查文件" not in full_text:
            add(
                "备查文件章节待确认", "信息完整性", "needs_review", 0, anchor,
                "当前文本未检索到“备查文件”章节。",
                "结合公告格式要求，确认决议、协议等备查文件是否需要列示。", 0.68,
            )
        if "定期报告" in task_type:
            self._analyze_periodic_report(parsed, full_text, add)
            if "年度报告" in re.sub(r"\s+", "", full_text):
                risks.extend(analyze_major_related_transactions(parsed))
        return risks[:MAX_RULE_RISKS]

    @staticmethod
    def _analyze_periodic_report(
        parsed: ParsedDocument,
        full_text: str,
        add: Any,
    ) -> None:
        listing_rules_title = "深圳证券交易所创业板股票上市规则（2026年修订）"
        listing_rules_url = "https://www.szse.cn/lawrules/rule/stock/supervision/chinext/t20260424_620189.html"

        def basis(article: str, page: int, detail: str) -> list[dict[str, Any]]:
            return [{
                "title": listing_rules_title,
                "article": article,
                "page": page,
                "detail": detail,
                "source": "深圳证券交易所",
                "source_url": listing_rules_url,
                "version": "2026年修订",
            }]

        def block_for(*terms: str) -> tuple[int, str]:
            for block in parsed.blocks:
                if any(term in block.text for term in terms):
                    return block.paragraph_index, _excerpt(block.text)
            return 0, _excerpt(parsed.paragraphs[0])

        normalized = re.sub(r"\s+", "", full_text)
        report_kind = "unknown"
        if "半年度报告" in normalized:
            report_kind = "half-year"
        elif re.search(r"(?:第一|第三|一|三)季度报告|第[13]季度报告", normalized):
            report_kind = "quarterly"
        elif "年度报告" in normalized:
            report_kind = "annual"

        format_basis: list[dict[str, Any]] = []
        if report_kind == "half-year":
            format_basis = [{
                "title": "公开发行证券的公司信息披露内容与格式准则第3号——半年度报告的内容与格式",
                "article": "第四条",
                "page": 1,
                "detail": "具体要求确实不适用时，可以在不影响披露内容完整性的前提下适当修改，并说明修改原因。",
                "source": "中国证券监督管理委员会",
                "source_url": "https://www.szse.cn/lawrules/csrcrules/notice/P020250519344477160571.pdf",
                "version": "2025年发布",
            }]
        elif report_kind == "annual":
            format_basis = [{
                "title": "公开发行证券的公司信息披露内容与格式准则第2号——年度报告的内容与格式",
                "article": "第四条",
                "page": 1,
                "detail": "具体要求确实不适用时，可以在不影响披露内容完整性的前提下适当修改，并说明修改原因。",
                "source": "中国证券监督管理委员会",
                "source_url": "https://www.szse.cn/lawrules/csrcrules/notice/P020250519344652102565.pdf",
                "version": "2025年发布",
            }]
        DeterministicRuleEngine._analyze_template_choices(parsed, add, format_basis)

        if report_kind == "unknown":
            paragraph_index, source_text = block_for("报告")
            add(
                "定期报告类型待确认", "定期报告类型", "needs_review", paragraph_index, source_text,
                "当前任务选择了定期报告审查，但正文中未明确识别年度报告、半年度报告或季度报告类型。不同报告适用的期限和审计要求不同。",
                "先确认报告类型和报告期，再按对应披露期限、审计要求及公告格式继续审查。", 0.94,
                basis("第6.1.1条、第6.1.2条", 51, "定期报告包括年度报告、半年度报告和季度报告，并分别适用不同披露期限。"),
            )

        approval_patterns = (
            r"董事会.{0,40}(?:审议|审阅)(?:通过)?.{0,30}(?:年度|半年度|季度)?报告",
            r"(?:年度|半年度|季度)?报告.{0,40}董事会.{0,20}(?:审议|审阅)(?:通过)?",
        )
        audit_committee_patterns = (
            r"审计委员会.{0,50}(?:审核|审议|同意).{0,30}(?:财务信息|定期报告|年度报告|半年度报告|季度报告)",
            r"(?:财务信息|定期报告|年度报告|半年度报告|季度报告).{0,50}审计委员会.{0,20}(?:审核|审议|同意)",
        )
        board_found = any(re.search(pattern, normalized) for pattern in approval_patterns)
        audit_committee_found = any(re.search(pattern, normalized) for pattern in audit_committee_patterns)
        missing_approval_steps: list[str] = []
        approval_locations: list[dict[str, Any]] = []
        if not audit_committee_found:
            paragraph_index, source_text = block_for("审计委员会", "重要提示", "董事会")
            block = parsed.blocks[max(0, min(paragraph_index, len(parsed.blocks) - 1))]
            missing_approval_steps.append("审计委员会审核并经全体成员过半数同意")
            approval_locations.append({
                "label": "审计委员会审核程序对应位置",
                "page": block.page,
                "section": block.section,
                "paragraphIndex": block.paragraph_index,
                "text": source_text,
            })
        if not board_found:
            paragraph_index, source_text = block_for("董事会", "重要提示", "审计委员会")
            block = parsed.blocks[max(0, min(paragraph_index, len(parsed.blocks) - 1))]
            missing_approval_steps.append("董事会审议通过")
            approval_locations.append({
                "label": "董事会审议程序对应位置",
                "page": block.page,
                "section": block.section,
                "paragraphIndex": block.paragraph_index,
                "text": source_text,
            })
        if missing_approval_steps:
            unique_locations: list[dict[str, Any]] = []
            seen_locations: set[tuple[Any, ...]] = set()
            for location in approval_locations:
                key = (
                    location.get("page"), location.get("section"),
                    location.get("paragraphIndex"), location.get("text"),
                )
                if key in seen_locations:
                    if unique_locations:
                        unique_locations[-1]["label"] = "审批程序共同对应位置"
                    continue
                seen_locations.add(key)
                unique_locations.append(location)
            approval_basis = basis(
                "第6.1.4条", 52,
                "定期报告财务信息须经审计委员会审核并由全体成员过半数同意后提交董事会审议；定期报告经董事会审议通过后方可披露。",
            )
            anchor_location = unique_locations[0]
            add(
                "定期报告审批程序待核验", "审批程序", "needs_review",
                int(anchor_location["paragraphIndex"]), str(anchor_location["text"]),
                f"待核验：{'；'.join(missing_approval_steps)}。",
                "核对审计委员会和董事会会议材料、表决结果及决议，确认审批顺序和披露版本一致。",
                0.92, approval_basis, unique_locations,
            )

        confirmation_found = bool(re.search(
            r"(?:董事|高级管理人员|全体董事).{0,100}(?:书面确认意见|真实.{0,12}准确.{0,12}完整)",
            normalized,
        ))
        if not confirmation_found:
            paragraph_index, source_text = block_for("董事", "高级管理人员", "重要提示")
            add(
                "董高书面确认意见待核验", "签署与确认", "needs_review", paragraph_index, source_text,
                "当前文件未检索到董事、高级管理人员对定期报告签署书面确认意见的完整信息。",
                "核对全部董事、高级管理人员的书面确认意见；存在异议的，应核对反对或弃权表决、具体理由及同步披露情况。", 0.88,
                basis("第6.1.5条、第6.1.6条", 52, "董事、高级管理人员应依法签署书面确认意见，不得拒绝签署并影响按时披露。"),
            )

        if report_kind == "annual":
            audit_report_found = "审计报告" in normalized and any(
                term in normalized for term in ("审计意见", "会计师事务所", "注册会计师")
            )
            if not audit_report_found:
                paragraph_index, source_text = block_for("财务报告", "审计", "年度报告")
                add(
                    "年度报告审计文件缺失", "审计要求", "high", paragraph_index, source_text,
                    "年度报告中的财务会计报告必须经符合规定的会计师事务所审计，当前文件未检索到完整审计报告或审计意见信息。",
                    "在披露前补充并核验正式审计报告、审计意见类型、会计师事务所和注册会计师签章；未经审计不得披露年度报告。", 0.98,
                    basis("第6.1.7条、第6.1.8条", 53, "年度报告中的财务会计报告必须经会计师事务所审计。"),
                )

            statement_terms = ("资产负债表", "利润表", "现金流量表", "所有者权益变动表")
            missing_statements = [term for term in statement_terms if term not in normalized]
            if missing_statements:
                paragraph_index, source_text = block_for("财务报告", "财务报表", "资产负债表")
                add(
                    "年度财务报表完整性待核验", "财务报告完整性", "high", paragraph_index, source_text,
                    f"当前解析文本未检索到：{'、'.join(missing_statements)}。可能是文件缺页、表格解析失败或财务报告不完整。",
                    "先对照原始 PDF 核对财务报表页是否齐全；若原文存在但解析缺失，应重新解析或 OCR，不得仅凭当前文本作出合规结论。", 0.96,
                    basis("第6.1.1条、第6.1.8条", 51, "定期报告应按证监会及深交所规定编制，年度财务会计报告须经审计。"),
                )

        if report_kind == "half-year" and any(term in normalized for term in ("利润分配预案", "公积金转增股本", "弥补亏损")):
            if "审计报告" not in normalized and "仅进行现金分红" not in normalized:
                paragraph_index, source_text = block_for("利润分配预案", "公积金转增股本", "弥补亏损")
                add(
                    "半年度报告审计条件待核验", "审计要求", "high", paragraph_index, source_text,
                    "正文涉及利润分配、公积金转增股本或弥补亏损安排，但当前文件未检索到审计报告。半年度报告在特定安排下需要审计。",
                    "核对本次是否仅进行现金分红；如不是，应在披露前取得并附具符合要求的审计报告。", 0.92,
                    basis("第6.1.8条", 54, "拟依据半年度报告进行特定利润分配、转增股本或弥补亏损时，应聘请会计师事务所审计。"),
                )

        if report_kind == "half-year":
            statement_terms = ("资产负债表", "利润表", "现金流量表", "所有者权益变动表")
            missing_statements = [term for term in statement_terms if term not in normalized]
            notes_markers = ("财务报表附注", "重要会计政策及会计估计", "合并财务报表项目注释", "财务报表项目注释")
            if not any(marker in normalized for marker in notes_markers):
                missing_statements.append("财务报表附注")
            if missing_statements:
                paragraph_index, source_text = block_for("财务报告", "财务报表", "资产负债表")
                add(
                    "财务报告组成项目待补充", "财务报告完整性", "high", paragraph_index, source_text,
                    f"当前解析文本未检索到：{'、'.join(missing_statements)}。可能是原文件缺失、表格解析不完整或报告尚未编制完成。",
                    "逐页核对原文件与披露目录，确认财务报表及附注完整；若原文存在但解析遗漏，应重新解析后再审查，不能据当前结果直接认定披露完整。", 0.96,
                    [{
                        "title": "公开发行证券的公司信息披露内容与格式准则第3号——半年度报告的内容与格式",
                        "article": "第五十三条",
                        "page": 24,
                        "detail": "半年度报告应披露比较式资产负债表、利润表、现金流量表、所有者权益变动表和财务报表附注。",
                        "source": "中国证券监督管理委员会",
                        "source_url": "https://www.szse.cn/lawrules/csrcrules/notice/P020250519344477160571.pdf",
                        "version": "2025年发布",
                    }],
                )

        if report_kind == "half-year" and "未经审计" not in normalized and "审计意见类型" not in normalized:
            paragraph_index, source_text = block_for("财务报告", "审计")
            add(
                "半年度财务报告审计状态未明确", "审计要求", "high", paragraph_index, source_text,
                "当前文件未检索到“未经审计”标识，也未检索到已审计情况下的审计意见类型，审计状态表达不完整。",
                "确认半年度财务报告是否审计；未经审计的应明确注明“未经审计”，已经审计的应披露审计意见类型，并按非标准意见情形补充相应文件。", 0.95,
                [{
                    "title": "公开发行证券的公司信息披露内容与格式准则第3号——半年度报告的内容与格式",
                    "article": "第五十四条",
                    "page": 24,
                    "detail": "半年度财务报告未经审计的应注明“未经审计”；已经审计的应披露审计意见类型。",
                    "source": "中国证券监督管理委员会",
                    "source_url": "https://www.szse.cn/lawrules/csrcrules/notice/P020250519344477160571.pdf",
                    "version": "2025年发布",
                }],
            )

        paragraph_index, source_text = block_for("报告期", "年度报告", "半年度报告", "季度报告")
        add(
            "定期报告披露时限与预约日期待核验", "披露期限", "needs_review", paragraph_index, source_text,
            "上传文件不包含深交所预约披露日期和实际提交时间，系统无法仅凭正文确认是否按期披露。",
            "核对报告期结束日、法定期限、深交所预约日期和实际提交时间；如需变更预约，应核对是否提前五个交易日申请及变更次数。", 0.99,
            basis("第6.1.2条、第6.1.3条", 51, "年度、半年度、季度报告分别适用四个月、两个月和一个月期限，并应按预约时间披露。"),
        )

    @staticmethod
    def _analyze_template_choices(
        parsed: ParsedDocument,
        add: Any,
        regulation_basis: list[dict[str, Any]],
    ) -> None:
        unchecked_pattern = re.compile(r"□\s*(适用|是|有)\s*□\s*(不适用|否|无)")
        conflicting_pattern = re.compile(r"☑\s*(适用|是|有)\s*☑\s*(不适用|否|无)")

        def nearby_label(index: int, fallback: str) -> str:
            for candidate in reversed(parsed.blocks[max(0, index - 5):index]):
                text = re.sub(r"\s+", " ", candidate.text).strip()
                if not text or len(text) > 100 or unchecked_pattern.search(text) or conflicting_pattern.search(text):
                    continue
                if re.fullmatch(r"[-—–0-9. ]+", text):
                    continue
                return text[:70]
            return fallback[:70] or "当前披露事项"

        unchecked: list[dict[str, Any]] = []
        conflicting: list[dict[str, Any]] = []
        for position, block in enumerate(parsed.blocks):
            label = nearby_label(position, block.section)
            for match in unchecked_pattern.finditer(block.text):
                unchecked.append({
                    "block": block,
                    "label": label,
                    "left": match.group(1),
                    "right": match.group(2),
                    "excerpt": _excerpt(block.text, match),
                })
            for match in conflicting_pattern.finditer(block.text):
                conflicting.append({
                    "block": block,
                    "label": label,
                    "left": match.group(1),
                    "right": match.group(2),
                    "excerpt": _excerpt(block.text, match),
                })

        def unique_findings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            seen: set[tuple[Any, ...]] = set()
            for item in items:
                key = (
                    item["block"].paragraph_index,
                    item["label"],
                    item["left"],
                    item["right"],
                )
                if key not in seen:
                    seen.add(key)
                    result.append(item)
            return result

        def location_list(items: list[dict[str, Any]]) -> str:
            return "；".join(
                f"{index}. {item['label']}（第{item['block'].page}页，第{item['block'].paragraph_index + 1}段）"
                for index, item in enumerate(items, start=1)
            )

        def original_locations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{
                "label": item["label"],
                "page": item["block"].page,
                "section": item["block"].section,
                "paragraphIndex": item["block"].paragraph_index,
                "text": item["excerpt"],
            } for item in items]

        unchecked = unique_findings(unchecked)
        conflicting = unique_findings(conflicting)
        if unchecked:
            first = unchecked[0]
            add(
                f"适用性选项待确认（共{len(unchecked)}处）", "模板选项完整性", "needs_review",
                first["block"].paragraph_index,
                "\n".join(f"{item['label']}：{item['excerpt']}" for item in unchecked),
                f"文档共有 {len(unchecked)} 处“适用/不适用（或是/否、有/无）”均未勾选。位置：{location_list(unchecked)}。"
                "该结果可能是编制未完成，也可能是 Word/PDF 勾选符号未被正确解析，不能直接认定为披露违规。",
                "先对照原始文件逐项确认视觉勾选；原文已有勾选的标记为解析问题，原文确未选择的由编制部门按事实仅选一项，最后复核后续说明、表格和附注与选择一致。",
                0.96, regulation_basis, original_locations(unchecked),
            )
        if conflicting:
            first = conflicting[0]
            material_terms = ("审计", "关联", "担保", "诉讼", "处罚", "退市", "持续经营", "会计政策", "控制权", "重大")
            level = "high" if any(
                any(term in item["label"] for term in material_terms) for item in conflicting
            ) else "medium"
            add(
                f"互斥选项冲突（共{len(conflicting)}处）", "模板选项一致性", level,
                first["block"].paragraph_index,
                "\n".join(f"{item['label']}：{item['excerpt']}" for item in conflicting),
                f"文档共有 {len(conflicting)} 处互斥选项同时勾选，披露结论相互矛盾。位置：{location_list(conflicting)}。",
                "逐项回查业务事实和底稿，仅保留一个选项；随后核对对应说明、表格、财务附注和全文同类表述，确保不存在相反结论。",
                0.99, regulation_basis, original_locations(conflicting),
            )
