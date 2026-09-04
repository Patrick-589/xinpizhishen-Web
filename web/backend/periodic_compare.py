from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .financial_change import calculate_financial_change, decimal_value
from .parsers import ParsedBlock, ParsedDocument, parse_document


NUMBER_PATTERN = re.compile(r"\(?[+\-−—－]?\d[\d,]*(?:\.\d+)?\)?")
REPORT_PATTERN = re.compile(
    r"(?P<year>20\d{2})\s*年\s*(?P<kind>半年度|年度|(?:第?[一三13])季度)报告"
)
METRIC_LABELS = (
    "归属于上市公司股东的扣除非经常性损益的净利润（元）",
    "归属于上市公司股东的净利润（元）",
    "经营活动产生的现金流量净额（元）",
    "归属于上市公司股东的净资产（元）",
    "基本每股收益（元/股）",
    "稀释每股收益（元/股）",
    "加权平均净资产收益率",
    "营业收入（元）",
    "总资产（元）",
)
SAME_PERIOD_METRICS = tuple(
    label for label in METRIC_LABELS
    if label not in {"总资产（元）", "归属于上市公司股东的净资产（元）"}
)
BALANCE_SHEET_LABELS = {
    "货币资金", "交易性金融资产", "应收票据", "应收账款", "应收款项融资", "预付款项",
    "其他应收款", "存货", "合同资产", "持有待售资产", "一年内到期的非流动资产",
    "其他流动资产", "流动资产合计", "长期应收款", "长期股权投资", "其他权益工具投资",
    "其他非流动金融资产", "投资性房地产", "固定资产", "在建工程", "使用权资产", "无形资产",
    "开发支出", "商誉", "长期待摊费用", "递延所得税资产", "其他非流动资产",
    "非流动资产合计", "资产总计", "短期借款", "应付票据", "应付账款", "合同负债",
    "应付职工薪酬", "应交税费", "其他应付款", "一年内到期的非流动负债", "其他流动负债",
    "流动负债合计", "长期借款", "租赁负债", "长期应付款", "预计负债", "递延收益",
    "递延所得税负债", "其他非流动负债", "非流动负债合计", "负债合计", "股本", "实收资本",
    "资本公积", "减：库存股", "其他综合收益", "盈余公积", "未分配利润",
    "归属于母公司所有者权益合计", "少数股东权益", "所有者权益合计", "负债和所有者权益总计",
}
INCOME_STATEMENT_LABELS = {
    "营业总收入", "营业收入", "营业总成本", "营业成本", "税金及附加", "销售费用", "管理费用",
    "研发费用", "财务费用", "利息费用", "利息收入", "其他收益", "投资收益", "对联营企业和合营企业的投资收益",
    "公允价值变动收益", "信用减值损失", "资产减值损失", "资产处置收益", "营业利润", "营业外收入",
    "营业外支出", "利润总额", "所得税费用", "净利润", "归属于母公司股东的净利润", "少数股东损益",
    "其他综合收益的税后净额", "综合收益总额", "归属于母公司所有者的综合收益总额",
    "归属于少数股东的综合收益总额", "基本每股收益", "稀释每股收益",
}
CASH_FLOW_LABELS = {
    "销售商品、提供劳务收到的现金", "收到的税费返还", "收到其他与经营活动有关的现金", "经营活动现金流入小计",
    "购买商品、接受劳务支付的现金", "支付给职工以及为职工支付的现金", "支付的各项税费",
    "支付其他与经营活动有关的现金", "经营活动现金流出小计", "经营活动产生的现金流量净额",
    "收回投资收到的现金", "取得投资收益收到的现金", "处置固定资产、无形资产和其他长期资产收回的现金净额",
    "处置子公司及其他营业单位收到的现金净额", "收到其他与投资活动有关的现金", "投资活动现金流入小计",
    "购建固定资产、无形资产和其他长期资产支付的现金", "投资支付的现金", "取得子公司及其他营业单位支付的现金净额",
    "支付其他与投资活动有关的现金", "投资活动现金流出小计", "投资活动产生的现金流量净额",
    "吸收投资收到的现金", "取得借款收到的现金", "收到其他与筹资活动有关的现金", "筹资活动现金流入小计",
    "偿还债务支付的现金", "分配股利、利润或偿付利息支付的现金", "支付其他与筹资活动有关的现金",
    "筹资活动现金流出小计", "筹资活动产生的现金流量净额", "汇率变动对现金及现金等价物的影响",
    "现金及现金等价物净增加额", "期初现金及现金等价物余额", "期末现金及现金等价物余额",
}
CASH_FLOW_CHANGE_LABELS = {
    "经营活动产生的现金流量净额", "投资活动产生的现金流量净额", "筹资活动产生的现金流量净额",
    "现金及现金等价物净增加额",
}

LISTING_RULES_TITLE = "深圳证券交易所创业板股票上市规则（2026年修订）"
LISTING_RULES_URL = "https://www.szse.cn/lawrules/rule/stock/supervision/chinext/t20260424_620189.html"
HALF_YEAR_FORMAT_TITLE = "公开发行证券的公司信息披露内容与格式准则第3号——半年度报告的内容与格式"
HALF_YEAR_FORMAT_URL = "https://www.szse.cn/lawrules/csrcrules/notice/P020250519344477160571.pdf"
FINANCIAL_REPORT_RULE_TITLE = "公开发行证券的公司信息披露编报规则第15号——财务报告的一般规定（2023年修订）"
FINANCIAL_REPORT_RULE_URL = "https://www.szse.cn/lawrules/csrcrules/notice/P020240802356168930071.pdf"

FINANCIAL_CONSISTENCY_BASIS = [{
    "title": LISTING_RULES_TITLE,
    "article": "第5.2.4条",
    "page": 44,
    "detail": "披露信息应当前后一致；财务信息应当具有合理的勾稽关系。与已披露信息存在重大差异的，应充分披露原因并作出合理解释。",
    "source": "深圳证券交易所",
    "source_url": LISTING_RULES_URL,
    "version": "2026年修订",
}]

FINANCIAL_STATEMENT_NOTE_BASIS = FINANCIAL_CONSISTENCY_BASIS + [{
    "title": FINANCIAL_REPORT_RULE_TITLE,
    "article": "第十一条、第十二条",
    "page": 2,
    "detail": "重要报表项目的附注编号应与财务报表附注一致；附注应对报表相关数据涉及的交易和事项作出真实、充分、明晰的说明。",
    "source": "中国证券监督管理委员会",
    "source_url": FINANCIAL_REPORT_RULE_URL,
    "version": "2023年修订",
}]

HALF_YEAR_COMPARATIVE_BASIS = FINANCIAL_CONSISTENCY_BASIS + [{
    "title": HALF_YEAR_FORMAT_TITLE,
    "article": "第五十三条",
    "page": 24,
    "detail": "半年度报告应披露比较式财务报表及附注，各报表项目应包括报告期末数和上年末数，或报告期间数和上年同期数。",
    "source": "中国证券监督管理委员会",
    "source_url": HALF_YEAR_FORMAT_URL,
    "version": "2025年发布",
}]

NARRATIVE_SECTION_SPECS = (
    {
        "key": "main_business",
        "label": "从事的主要业务",
        "aliases": ("报告期内公司从事的主要业务", "公司从事的主要业务", "主要业务"),
    },
    {
        "key": "business_overview",
        "label": "业务概述",
        "aliases": ("主要业务概述", "业务概述", "公司业务概要", "业务概要"),
    },
    {
        "key": "core_competitiveness",
        "label": "核心竞争力",
        "aliases": ("核心竞争力分析", "核心竞争力"),
    },
    {
        "key": "risk_disclosure",
        "label": "风险提示",
        "aliases": (
            "公司面临的风险和应对措施", "重大风险提示", "风险因素提示如下：",
            "风险因素提示如下", "风险因素", "风险提示",
        ),
        "boundary": "report_section_if_unstructured",
    },
    {
        "key": "social_responsibility",
        "label": "社会责任",
        "aliases": ("社会责任情况", "环境和社会责任", "履行社会责任情况", "社会责任"),
        "boundary": "report_section",
    },
)

NARRATIVE_TOPICS = {
    "人工智能业务": ("人工智能", "AI", "大模型", "天启", "HEIMA AI", "智能化"),
    "企业服务": ("企业服务", "企服"),
    "企业培训": ("企业培训", "培训业务", "培训服务"),
    "创业服务": ("创业服务", "创业加速", "企业加速"),
    "知识产权服务": ("知识产权",),
    "数字化转型": ("数字化转型", "数字化升级"),
    "投资管理": ("投资管理", "投资业务"),
    "市场竞争": ("市场竞争", "竞争加剧", "同质化竞争"),
    "研发投入": ("研发投入", "技术研发"),
    "数据安全": ("数据安全", "信息安全", "网络安全"),
    "政策监管": ("监管政策", "政策变化", "政策风险"),
    "客户需求": ("客户需求", "客户流失", "客户集中"),
    "人才风险": ("人才流失", "人才短缺", "核心人员"),
    "应收账款": ("应收账款", "回款风险"),
    "商誉减值": ("商誉减值",),
    "投资损失": ("投资损失", "投资风险"),
    "经营业绩": ("经营业绩", "业绩波动", "经营亏损"),
    "流动性": ("流动性风险", "资金风险"),
}

BUSINESS_HISTORY_TOPICS = {
    key for key in (
        "人工智能业务", "企业服务", "企业培训", "创业服务", "知识产权服务",
        "数字化转型", "投资管理",
    )
}

RISK_DISCLOSURE_TOPICS = {
    key for key in (
        "人工智能业务", "市场竞争", "研发投入", "数据安全", "政策监管", "客户需求",
        "人才风险", "应收账款", "商誉减值", "投资损失", "经营业绩", "流动性",
    )
}

NARRATIVE_CLAIM_RULES = (
    (
        "商业化状态",
        re.compile(r"(?:已|成功|实现|完成)[^。；]{0,12}(?:商业化|商业落地)"),
        re.compile(r"(?:尚未|未能|没有)[^。；]{0,12}(?:商业化|商业落地)"),
        "high",
    ),
    (
        "收入实现状态",
        re.compile(r"(?:已|成功)?(?:实现|产生)[^。；]{0,8}收入"),
        re.compile(r"(?:尚未|未能|没有)[^。；]{0,8}(?:实现|产生)[^。；]{0,6}收入|未产生收入"),
        "high",
    ),
    (
        "盈利状态",
        re.compile(r"扭亏为盈|实现盈利|保持盈利"),
        re.compile(r"持续亏损|出现亏损|尚未盈利|未实现盈利"),
        "high",
    ),
    (
        "有息负债状态",
        re.compile(r"零有息负债|无有息负债|不存在有息负债"),
        re.compile(r"存在有息负债|有息负债(?:增加|上升)"),
        "high",
    ),
    (
        "研发投入方向",
        re.compile(r"(?:增加|扩大|持续加大)[^。；]{0,8}研发投入|研发投入[^。；]{0,6}(?:增长|增加|上升)"),
        re.compile(r"(?:减少|压缩|缩减)[^。；]{0,8}研发投入|研发投入[^。；]{0,6}(?:下降|减少|缩减)"),
        "medium",
    ),
    (
        "业务存续状态",
        re.compile(r"(?:持续|重点|继续)(?:推进|开展|布局|经营)[^。；]{0,12}(?:业务|产品|服务|项目)"),
        re.compile(r"(?:停止|终止|退出|不再)(?:开展|经营|布局)[^。；]{0,12}(?:业务|产品|服务|项目)"),
        "medium",
    ),
)


@dataclass(frozen=True)
class PeriodicReportIdentity:
    year: int
    kind: str


@dataclass(frozen=True)
class ValueLocation:
    label: str
    values: tuple[float, ...]
    raw_values: tuple[str, ...]
    page: int
    paragraph: int
    section: str
    text: str


@dataclass(frozen=True)
class NarrativeSection:
    key: str
    label: str
    heading: str
    blocks: tuple[ParsedBlock, ...]

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks if block.text.strip())

    @property
    def location(self) -> ValueLocation:
        block = self.blocks[0]
        return ValueLocation(
            self.label, (), (), block.page, block.paragraph_index, block.section, block.text,
        )


@dataclass(frozen=True)
class NarrativeClaim:
    kind: str
    polarity: str
    level: str
    section_key: str
    section_label: str
    topics: frozenset[str]
    sentence: str
    location: ValueLocation


def detect_periodic_report_identity(filename: str, parsed: ParsedDocument) -> PeriodicReportIdentity | None:
    sample = f"{Path(filename).stem}\n" + "\n".join(parsed.paragraphs[:30])
    match = REPORT_PATTERN.search(sample.replace(" ", ""))
    if not match:
        return None
    raw_kind = match.group("kind")
    if raw_kind == "半年度":
        kind = "half-year"
    elif raw_kind == "年度":
        kind = "annual"
    elif "一" in raw_kind or "1" in raw_kind:
        kind = "first-quarter"
    else:
        kind = "third-quarter"
    return PeriodicReportIdentity(int(match.group("year")), kind)


def _heading_level(value: str) -> int:
    compact = value.strip()
    if re.match(r"^[一二三四五六七八九十百]+、", compact):
        return 1
    if re.match(r"^[（(][一二三四五六七八九十百0-9]+[）)]", compact):
        return 2
    if re.match(r"^\d+[、.．]", compact):
        return 2
    if re.match(r"^[（(]\d+[）)]", compact):
        return 3
    return 4


def _is_report_section_heading(value: str) -> bool:
    return bool(re.match(r"^第[一二三四五六七八九十百零〇0-9]+节(?:\s|$)", value.strip()))


def _section_heading_score(block: ParsedBlock, aliases: tuple[str, ...]) -> tuple[int, int]:
    text = re.sub(r"\s+", "", block.text)
    if len(text) > 90:
        return 0, 0
    best = 0
    for alias_index, alias in enumerate(aliases):
        normalized_alias = re.sub(r"\s+", "", alias)
        if text == normalized_alias:
            score = 100
        elif text.endswith(normalized_alias):
            score = 90
        elif normalized_alias in text:
            score = 70
        else:
            continue
        if block.block_type == "heading":
            score += 20
        best = max(best, score - alias_index)
    return best, -block.paragraph_index


def extract_narrative_sections(parsed: ParsedDocument) -> dict[str, NarrativeSection]:
    sections: dict[str, NarrativeSection] = {}
    for spec in NARRATIVE_SECTION_SPECS:
        aliases = tuple(spec["aliases"])
        scored = [
            (_section_heading_score(block, aliases), index)
            for index, block in enumerate(parsed.blocks)
        ]
        score, start = max(scored, default=((0, 0), -1), key=lambda item: item[0])
        if start < 0 or score[0] <= 0:
            continue
        start_block = parsed.blocks[start]
        start_level = _heading_level(start_block.text)
        end = len(parsed.blocks)
        boundary = spec.get("boundary")
        use_report_section_boundary = (
            boundary == "report_section"
            or boundary == "report_section_if_unstructured" and start_level == 4
        )
        if use_report_section_boundary:
            end = next((
                index for index, block in enumerate(parsed.blocks[start + 1:], start + 1)
                if block.block_type == "heading" and _is_report_section_heading(block.text)
            ), end)
        if end == len(parsed.blocks):
            for index in range(start + 1, len(parsed.blocks)):
                block = parsed.blocks[index]
                if block.block_type != "heading":
                    continue
                if _heading_level(block.text) <= start_level:
                    end = index
                    break
        selected_blocks = tuple(parsed.blocks[start:end])
        if selected_blocks:
            sections[str(spec["key"])] = NarrativeSection(
                str(spec["key"]), str(spec["label"]), start_block.text.strip(), selected_blocks,
            )
    return sections


def _narrative_topics(text: str) -> set[str]:
    folded = text.casefold()
    return {
        label for label, terms in NARRATIVE_TOPICS.items()
        if any(term.casefold() in folded for term in terms)
    }


def _narrative_similarity(current: str, baseline: str) -> float:
    def grams(value: str) -> set[str]:
        compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", value).casefold()
        return {compact[index:index + 2] for index in range(max(0, len(compact) - 1))}

    current_grams = grams(current)
    baseline_grams = grams(baseline)
    if not current_grams or not baseline_grams:
        return 0.0
    return len(current_grams & baseline_grams) / len(current_grams | baseline_grams)


def _section_topic_location(section: NarrativeSection, topic: str) -> ValueLocation:
    terms = NARRATIVE_TOPICS.get(topic, ())
    block = next(
        (
            item for item in section.blocks
            if any(term.casefold() in item.text.casefold() for term in terms)
        ),
        section.blocks[0],
    )
    return ValueLocation(topic, (), (), block.page, block.paragraph_index, block.section, block.text)


def _claim_sentences(block: ParsedBlock) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？；])|\n+", block.text)
        if len(sentence.strip()) >= 6
    ]


def _extract_narrative_claims(sections: dict[str, NarrativeSection]) -> list[NarrativeClaim]:
    claims: list[NarrativeClaim] = []
    for section in sections.values():
        for block in section.blocks:
            for sentence in _claim_sentences(block):
                for kind, positive, negative, level in NARRATIVE_CLAIM_RULES:
                    positive_match = positive.search(sentence)
                    negative_match = negative.search(sentence)
                    if positive_match and negative_match:
                        continue
                    if not positive_match and not negative_match:
                        continue
                    match = positive_match or negative_match
                    assert match is not None
                    prefix = sentence[max(0, match.start() - 18):match.start()]
                    if negative_match and re.search(r"上年同期|去年|此前|前期|20\d{2}年", prefix):
                        continue
                    topics = frozenset(_narrative_topics(sentence))
                    claims.append(NarrativeClaim(
                        kind,
                        "positive" if positive_match else "negative",
                        level,
                        section.key,
                        section.label,
                        topics,
                        sentence[:500],
                        ValueLocation(
                            kind, (), (), block.page, block.paragraph_index, block.section, sentence[:1000],
                        ),
                    ))
    return claims


def _claims_refer_to_same_subject(left: NarrativeClaim, right: NarrativeClaim) -> bool:
    if left.topics & right.topics:
        return True
    return left.kind in {"有息负债状态", "盈利状态"} and right.kind == left.kind


def _baseline_narrative_source(
    row: dict[str, Any],
    section: NarrativeSection,
    topic: str | None = None,
) -> dict[str, Any]:
    location = _section_topic_location(section, topic) if topic else section.location
    return {
        **_baseline_citation(row),
        "page": location.page,
        "section": location.section,
        "content": location.text,
        "citation_kind": "period_narrative_comparison",
    }


def _first_document_location(parsed: ParsedDocument, label: str) -> ValueLocation:
    block = parsed.blocks[0]
    return ValueLocation(label, (), (), block.page, block.paragraph_index, block.section, block.text)


def select_baseline_rows(
    rows: Iterable[dict[str, Any]],
    identity: PeriodicReportIdentity,
) -> list[dict[str, Any]]:
    target_year = identity.year - 1
    same_period_term = {
        "half-year": "半年度报告",
        "annual": "年度报告",
        "first-quarter": "一季度报告",
        "third-quarter": "三季度报告",
    }[identity.kind]

    def usable(row: dict[str, Any]) -> bool:
        title = str(row.get("title") or "").replace(" ", "")
        if any(term in title for term in ("摘要", "提示", "说明会", "问询", "已取消")):
            return False
        return str(target_year) in title

    def matches_report(row: dict[str, Any], term: str) -> bool:
        title = str(row.get("title") or "").replace(" ", "")
        return bool(re.search(
            rf"(?:^|[:：]){target_year}年{re.escape(term)}(?:（更新后）|\(更新后\))?$",
            title,
        ))

    candidates = [row for row in rows if usable(row)]
    selected: list[dict[str, Any]] = []
    same_period = [row for row in candidates if matches_report(row, same_period_term)]
    if same_period:
        selected.append(max(same_period, key=_baseline_sort_key))
    if identity.kind != "annual":
        annual = [
            row for row in candidates
            if matches_report(row, "年度报告")
        ]
        if annual:
            best = max(annual, key=_baseline_sort_key)
            if all(best.get("id") != item.get("id") for item in selected):
                selected.append(best)
    return selected


def _review_narrative_sections(
    current: ParsedDocument,
    loaded: list[tuple[dict[str, Any], ParsedDocument, PeriodicReportIdentity | None]],
    balance: dict[str, ValueLocation],
    seen: set[tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    current_sections = extract_narrative_sections(current)
    baseline_sections = [
        (row, extract_narrative_sections(parsed))
        for row, parsed, _identity in loaded
    ]
    internal_risks: list[dict[str, Any]] = []
    historical_risks: list[dict[str, Any]] = []
    checked = 0

    if current_sections:
        for spec in NARRATIVE_SECTION_SPECS:
            key = str(spec["key"])
            if key in current_sections:
                continue
            dedupe_key = ("narrative-section-missing", key)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            anchor = _first_document_location(current, str(spec["label"]))
            internal_risks.append(_risk(
                title=f"定期报告重要文字章节未识别：{spec['label']}",
                description=(
                    f"系统未在本报告中识别到“{spec['label']}”对应章节。该结果可能是章节缺失、标题改名或文档解析异常，"
                    "不直接认定披露违规，但无法完成该章节的内部一致性和历史对比。"
                ),
                current=anchor,
                recommendation=(
                    f"人工确认本报告是否应设置“{spec['label']}”章节；如已披露，请统一章节标题并检查解析结果；"
                    "如不适用，应在复核记录中注明适用性依据。"
                ),
                confidence=0.9,
                regulation_basis=FINANCIAL_CONSISTENCY_BASIS,
                level="needs_review",
                risk_type="定期报告文字一致性",
            ))

    claims = _extract_narrative_claims(current_sections)
    for left_index, left in enumerate(claims):
        for right in claims[left_index + 1:]:
            if left.section_key == right.section_key or left.kind != right.kind or left.polarity == right.polarity:
                continue
            if not _claims_refer_to_same_subject(left, right):
                continue
            topic = (
                "研发投入"
                if left.kind == "研发投入方向"
                else sorted(left.topics & right.topics)[0] if left.topics & right.topics else left.kind
            )
            recommendation = (
                "先核对两处“研发投入”是否采用同一口径，包括研发费用总额、资本化支出、研发人员工时和具体产品资源。"
                "若本期研发费用同比下降且没有其他投入增加的底稿依据，应将“持续加大研发投入力度”改为"
                "“持续聚焦核心产品研发，报告期研发费用同比下降，研发资源进一步向核心产品商业化环节集中”等与数据一致的表述。"
                "若仅黑马天启等特定项目投入增加，应补充项目名称、报告期间、金额或人员投入变化，并解释局部增加与研发费用总额下降的关系。"
                if left.kind == "研发投入方向"
                else (
                    "核对两处表述是否属于不同报告期间、不同产品或不同业务口径；在正文中补充明确的时间、主体和范围限定。"
                    "如确属同一事项，应依据底稿保留正确表述并同步修改业务概述、核心竞争力、风险提示和社会责任章节。"
                )
            )
            key = ("narrative-contradiction", f"{left.kind}:{topic}")
            if key in seen:
                continue
            seen.add(key)
            internal_risks.append(_risk(
                title=f"文字章节存在相反事实表述：{topic}",
                description=(
                    f"“{left.section_label}”与“{right.section_label}”对同一事项存在相反表述。"
                    f"前者：{left.sentence} 后者：{right.sentence}。"
                    "系统仅标记文字冲突，最终事实应以业务、财务和审批底稿为准。"
                ),
                current=left.location,
                recommendation=recommendation,
                confidence=0.96,
                regulation_basis=FINANCIAL_CONSISTENCY_BASIS,
                level="high" if "high" in {left.level, right.level} else "medium",
                locations=[
                    (f"{left.section_label}：{left.kind}", left.location),
                    (f"{right.section_label}：{right.kind}", right.location),
                ],
                risk_type="定期报告文字一致性",
            ))
            checked += 1

    social = current_sections.get("social_responsibility")
    if social and re.search(r"零有息负债|无有息负债|不存在有息负债", social.text):
        borrowing_items = [
            balance.get(_normalize_label(label)) for label in ("短期借款", "长期借款")
        ]
        nonzero_borrowings = [
            item for item in borrowing_items
            if item is not None and item.values and not _numbers_equal(item.values[0], 0.0)
        ]
        if nonzero_borrowings and ("narrative-financial", "有息负债") not in seen:
            seen.add(("narrative-financial", "有息负债"))
            social_location = social.location
            total = sum(item.values[0] for item in nonzero_borrowings)
            internal_risks.append(_risk(
                title="社会责任表述与财务报表有息借款不一致",
                description=(
                    f"社会责任章节披露“零/无有息负债”，但合并资产负债表短期借款和长期借款期末余额合计为 {_format_number(total)}。"
                    "除非两处采用了不同且已充分解释的统计口径，否则存在前后不一致。"
                ),
                current=social_location,
                recommendation=(
                    "核对借款明细、计息状态和社会责任章节统计口径；如确有有息借款，应修正“零/无有息负债”表述；"
                    "如报表项目不属于有息负债，应在文字中明确排除范围和依据。"
                ),
                confidence=0.99,
                regulation_basis=FINANCIAL_CONSISTENCY_BASIS,
                locations=[
                    ("社会责任：有息负债表述", social_location),
                    *[(f"合并资产负债表：{item.label}", item) for item in nonzero_borrowings],
                ],
                risk_type="定期报告文字一致性",
            ))
            checked += 1

    current_risk = current_sections.get("risk_disclosure")
    current_operating = "\n".join(
        current_sections[key].text
        for key in ("main_business", "business_overview", "core_competitiveness", "social_responsibility")
        if key in current_sections
    )
    current_operating_topics = _narrative_topics(current_operating)
    current_risk_topics = _narrative_topics(current_risk.text) if current_risk else set()
    for topic in sorted(RISK_DISCLOSURE_TOPICS & current_operating_topics):
        baseline_matches: list[tuple[dict[str, Any], NarrativeSection]] = []
        for row, sections in baseline_sections:
            baseline_risk = sections.get("risk_disclosure")
            if baseline_risk and topic in _narrative_topics(baseline_risk.text):
                baseline_matches.append((row, baseline_risk))
        checked += len(baseline_matches)
        if not baseline_matches or topic in current_risk_topics or current_risk is None:
            continue
        key = ("historical-risk-omission", topic)
        if key in seen:
            continue
        seen.add(key)
        sources = [_baseline_narrative_source(row, section, topic) for row, section in baseline_matches]
        current_anchor_section = next(
            (
                section for section in current_sections.values()
                if topic in _narrative_topics(section.text)
            ),
            current_risk,
        )
        current_anchor = _section_topic_location(current_anchor_section, topic)
        historical_risks.append(_risk(
            title=f"既往重大风险本期未延续披露：{topic}",
            description=(
                f"历史定期报告的风险章节披露了“{topic}”相关风险，本期主要业务、核心竞争力或社会责任章节仍提及该事项，"
                "但本期风险章节未检索到对应风险说明。该变化不自动等同于遗漏披露，需核验风险是否已消除及其依据。"
            ),
            current=current_anchor,
            recommendation=(
                f"核对“{topic}”风险在本期是否仍然存在。若仍存在，应在风险章节补充风险表现、可能影响和应对措施；"
                "若已消除，应留存业务、财务或法律依据，并在必要时说明风险变化原因。"
            ),
            confidence=0.9,
            sources=sources,
            regulation_basis=FINANCIAL_CONSISTENCY_BASIS,
            level="needs_review",
            risk_type="定期报告文字一致性",
        ))

    current_business_text = "\n".join(
        current_sections[key].text
        for key in ("main_business", "business_overview", "core_competitiveness")
        if key in current_sections
    )
    current_business_topics = _narrative_topics(current_business_text)
    required_baseline_count = len(baseline_sections)
    if required_baseline_count:
        for topic in sorted(BUSINESS_HISTORY_TOPICS - current_business_topics):
            matches: list[tuple[dict[str, Any], NarrativeSection]] = []
            matched_documents: set[str] = set()
            for row, sections in baseline_sections:
                for key in ("main_business", "business_overview", "core_competitiveness"):
                    section = sections.get(key)
                    if section and topic in _narrative_topics(section.text):
                        matches.append((row, section))
                        matched_documents.add(str(row.get("id") or row.get("title") or ""))
                        break
            checked += len(matches)
            if len(matched_documents) < required_baseline_count:
                continue
            key = ("historical-business-change", topic)
            if key in seen:
                continue
            seen.add(key)
            anchor_section = (
                current_sections.get("main_business")
                or current_sections.get("business_overview")
                or current_sections.get("core_competitiveness")
            )
            anchor = anchor_section.location if anchor_section else _first_document_location(current, topic)
            historical_risks.append(_risk(
                title=f"主要业务历史表述发生重大变化待解释：{topic}",
                description=(
                    f"选取的历史定期报告均在主要业务或核心竞争力章节提及“{topic}”，本报告对应章节未检索到该主题。"
                    "这可能源于业务终止、分类口径调整或章节改写，需要形成可核验说明。"
                ),
                current=anchor,
                recommendation=(
                    f"确认“{topic}”是否已终止、出售、重分类或不再构成主要业务；如发生重大变化，应在业务概述中说明变化时间、原因、"
                    "财务影响及后续安排；如业务仍在持续，应补回相应业务和竞争力表述。"
                ),
                confidence=0.88,
                sources=[_baseline_narrative_source(row, section, topic) for row, section in matches],
                regulation_basis=FINANCIAL_CONSISTENCY_BASIS,
                level="needs_review",
                risk_type="定期报告文字一致性",
            ))

    matrix: list[dict[str, Any]] = []
    for spec in NARRATIVE_SECTION_SPECS:
        key = str(spec["key"])
        current_section = current_sections.get(key)
        current_topics = _narrative_topics(current_section.text) if current_section else set()
        baseline_items = []
        for row, sections in baseline_sections:
            baseline = sections.get(key)
            baseline_topics = _narrative_topics(baseline.text) if baseline else set()
            baseline_items.append({
                "documentId": str(row.get("id") or ""),
                "title": str(row.get("title") or ""),
                "sourceUrl": str(row.get("source_url") or ""),
                "found": baseline is not None,
                "page": baseline.location.page if baseline else None,
                "similarity": round(_narrative_similarity(current_section.text, baseline.text), 4)
                if current_section and baseline else None,
                "addedTopics": sorted(current_topics - baseline_topics),
                "removedTopics": sorted(baseline_topics - current_topics),
            })
            if current_section and baseline:
                checked += 1
        matrix.append({
            "key": key,
            "label": str(spec["label"]),
            "found": current_section is not None,
            "page": current_section.location.page if current_section else None,
            "paragraphIndex": current_section.location.paragraph if current_section else None,
            "topics": sorted(current_topics),
            "baselines": baseline_items,
        })

    return historical_risks, internal_risks, {
        "sections": matrix,
        "sectionsChecked": len(NARRATIVE_SECTION_SPECS),
        "sectionsFound": len(current_sections),
        "comparisons": checked,
        "historicalChanges": len(historical_risks),
        "internalConflicts": len(internal_risks),
    }


def compare_periodic_report(
    current: ParsedDocument,
    filename: str,
    baseline_rows: Iterable[dict[str, Any]],
    baseline_loader: Callable[[dict[str, Any]], ParsedDocument] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    identity = detect_periodic_report_identity(filename, current)
    if not identity:
        return [], {"status": "not_periodic", "baselines": [], "checkedItems": 0, "mismatches": 0}

    selected = select_baseline_rows(baseline_rows, identity)
    loaded: list[tuple[dict[str, Any], ParsedDocument, PeriodicReportIdentity | None]] = []
    failures: list[dict[str, str]] = []
    for row in selected:
        try:
            if baseline_loader is not None:
                parsed = baseline_loader(row)
                path = Path(str(row.get("file_path") or ""))
            else:
                path = Path(str(row.get("file_path") or ""))
                if not path.is_file():
                    raise FileNotFoundError("本地公告原文件不存在")
                parsed = parse_document(path.name.split("_", 1)[-1], path.read_bytes())
            loaded.append((row, parsed, detect_periodic_report_identity(str(row.get("title") or path.name), parsed)))
        except Exception as error:
            failures.append({"title": str(row.get("title") or ""), "error": str(error)})

    risks: list[dict[str, Any]] = []
    checked = 0
    seen: set[tuple[str, str]] = set()
    current_metrics = extract_summary_metrics(current)
    current_balance = extract_statement_rows(current, "1、合并资产负债表", "2、母公司资产负债表")
    current_income = extract_statement_rows(
        current, "3、合并利润表", "4、母公司利润表", INCOME_STATEMENT_LABELS,
    )
    current_cash_flow = extract_statement_rows(
        current, "5、合并现金流量表", "6、母公司现金流量表", CASH_FLOW_LABELS,
    )
    comparison_basis = HALF_YEAR_COMPARATIVE_BASIS if identity.kind == "half-year" else FINANCIAL_CONSISTENCY_BASIS

    for row, baseline, baseline_identity in loaded:
        if not baseline_identity:
            continue
        citation = _baseline_citation(row)
        baseline_metrics = extract_summary_metrics(baseline)
        if baseline_identity.kind == identity.kind:
            for label in SAME_PERIOD_METRICS:
                current_item = current_metrics.get(_normalize_label(label))
                baseline_item = baseline_metrics.get(_normalize_label(label))
                if not current_item or not baseline_item or len(current_item.values) < 2 or not baseline_item.values:
                    continue
                checked += 1
                _append_difference_risk(
                    risks, seen, "same-period", label,
                    current_item.values[1], current_item.raw_values[1],
                    baseline_item.values[0], baseline_item.raw_values[0],
                    current_item, citation, baseline_item,
                    "本报告列示的上年同期数与上年同期官方报告列示的本期数不一致",
                    "核对是否属于前期差错更正、会计政策变更或口径调整；如不是，应统一本报告比较数、财务报表、附注和经营分析中的对应数据。",
                    comparison_basis,
                )

            for section_name, current_rows, start_heading, end_heading in (
                ("合并利润表", current_income, "3、合并利润表", "4、母公司利润表"),
                ("合并现金流量表", current_cash_flow, "5、合并现金流量表", "6、母公司现金流量表"),
            ):
                baseline_rows_for_section = extract_statement_rows(
                    baseline,
                    start_heading,
                    end_heading,
                    INCOME_STATEMENT_LABELS if section_name == "合并利润表" else CASH_FLOW_LABELS,
                )
                for label in sorted(set(current_rows) & set(baseline_rows_for_section)):
                    current_item = current_rows[label]
                    baseline_item = baseline_rows_for_section[label]
                    if len(current_item.values) < 2 or not baseline_item.values:
                        continue
                    checked += 1
                    _append_difference_risk(
                        risks, seen, "same-period", current_item.label,
                        current_item.values[1], current_item.raw_values[1],
                        baseline_item.values[0], baseline_item.raw_values[0],
                        current_item, citation, baseline_item,
                        f"本报告{section_name}列示的上年同期数与上年同期官方报告本期数不一致",
                        "核对前期差错更正、会计政策变更及同一控制下合并等调整依据；无重述依据时，应统一本报告比较数、附注和经营分析。",
                        comparison_basis,
                    )

        if baseline_identity.kind == "annual":
            for label in ("总资产（元）", "归属于上市公司股东的净资产（元）"):
                current_item = current_metrics.get(_normalize_label(label))
                baseline_item = baseline_metrics.get(_normalize_label(label))
                if not current_item or not baseline_item or len(current_item.values) < 2 or not baseline_item.values:
                    continue
                checked += 1
                _append_difference_risk(
                    risks, seen, "year-end-summary", label,
                    current_item.values[1], current_item.raw_values[1],
                    baseline_item.values[0], baseline_item.raw_values[0],
                    current_item, citation, baseline_item,
                    "本报告列示的上年度末数与上年度官方年报列示的期末数不一致",
                    "核对年初数是否依法重述；如有调整，应披露原因、依据及影响金额，如无调整依据，应统一本报告比较数。",
                    comparison_basis,
                )

            baseline_balance = extract_statement_rows(baseline, "1、合并资产负债表", "2、母公司资产负债表")
            for label in sorted(set(current_balance) & set(baseline_balance)):
                current_item = current_balance[label]
                baseline_item = baseline_balance[label]
                if len(current_item.values) < 2 or not baseline_item.values:
                    continue
                checked += 1
                _append_difference_risk(
                    risks, seen, "balance-opening", current_item.label,
                    current_item.values[1], current_item.raw_values[1],
                    baseline_item.values[0], baseline_item.raw_values[0],
                    current_item, citation, baseline_item,
                    "本期合并资产负债表期初余额与上年度官方年报期末余额不一致",
                    "逐项核对期初余额与上年末余额；存在会计政策变更、前期差错更正或合并范围追溯调整的，应在附注披露调整原因和金额，否则应统一数据。",
                    comparison_basis,
                )

    narrative_historical_risks, narrative_internal_risks, narrative_review = _review_narrative_sections(
        current, loaded, current_balance, seen,
    )
    risks.extend(narrative_historical_risks)
    checked += int(narrative_review.get("comparisons") or 0)
    historical_mismatches = len(risks)
    current_document_risks = _current_document_consistency_risks(
        current, current_balance, current_income, current_cash_flow, seen,
    )
    current_document_risks.extend(narrative_internal_risks)
    risks.extend(current_document_risks)
    summary = {
        "status": "completed" if loaded else "missing_baseline",
        "reportYear": identity.year,
        "reportKind": identity.kind,
        "baselines": [
            {
                "documentId": str(row.get("id") or ""),
                "title": str(row.get("title") or ""),
                "date": str(row.get("publication_date") or ""),
                "sourceUrl": str(row.get("source_url") or ""),
            }
            for row, _, _ in loaded
        ],
        "checkedItems": checked,
        "mismatches": len(risks),
        "historicalMismatches": historical_mismatches,
        "internalMismatches": len(current_document_risks),
        "narrativeSectionsChecked": narrative_review["sectionsChecked"],
        "narrativeSectionsFound": narrative_review["sectionsFound"],
        "narrativeHistoricalChanges": narrative_review["historicalChanges"],
        "narrativeInternalConflicts": narrative_review["internalConflicts"],
        "narrativeReview": narrative_review,
        "failures": failures,
    }
    return risks, summary


def extract_summary_metrics(parsed: ParsedDocument) -> dict[str, ValueLocation]:
    results: dict[str, ValueLocation] = {}
    for block in parsed.blocks:
        if "主要会计数据和财务指标" not in block.section and "主要会计数据和财务指标" not in block.text:
            continue
        for line in block.text.splitlines():
            compact = line.strip().lstrip("|").strip()
            normalized = _normalize_label(compact)
            for label in METRIC_LABELS:
                normalized_label = _normalize_label(label)
                if not normalized.startswith(normalized_label):
                    continue
                raw_values = tuple(NUMBER_PATTERN.findall(compact[len(label):]))
                values = tuple(value for value in (_parse_number(item) for item in raw_values) if value is not None)
                if values:
                    results.setdefault(normalized_label, ValueLocation(
                        label, values, raw_values[:len(values)], block.page, block.paragraph_index,
                        block.section, line.strip(),
                    ))
                break
    return results


def extract_statement_rows(
    parsed: ParsedDocument,
    start_heading: str,
    end_heading: str,
    allowed_labels: set[str] | None = None,
) -> dict[str, ValueLocation]:
    start = next((index for index, block in enumerate(parsed.blocks) if block.text.strip().startswith(start_heading)), None)
    if start is None:
        return {}
    end = next(
        (index for index, block in enumerate(parsed.blocks[start + 1:], start + 1)
         if block.text.strip().startswith(end_heading)),
        len(parsed.blocks),
    )
    results: dict[str, ValueLocation] = {}
    normalized_allowed = {
        _normalize_label(item) for item in (allowed_labels or BALANCE_SHEET_LABELS)
    }
    for block in parsed.blocks[start + 1:end]:
        for line in block.text.splitlines():
            parsed_row = _parse_statement_line(line)
            if not parsed_row:
                continue
            label, raw_values, values = parsed_row
            normalized = _normalize_label(label)
            if normalized not in normalized_allowed:
                continue
            candidate = ValueLocation(
                label.strip(), values, raw_values, block.page, block.paragraph_index, block.section, line.strip(),
            )
            existing = results.get(normalized)
            if existing is None or _financial_row_score(candidate) > _financial_row_score(existing):
                results[normalized] = candidate
    return results


def _financial_row_score(item: ValueLocation) -> tuple[int, float]:
    """Prefer the populated row when statement templates repeat the same label."""
    return sum(not _numbers_equal(value, 0.0) for value in item.values), sum(abs(value) for value in item.values)


def _current_document_consistency_risks(
    parsed: ParsedDocument,
    balance: dict[str, ValueLocation],
    income: dict[str, ValueLocation],
    cash_flow: dict[str, ValueLocation],
    seen: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    monetary = balance.get(_normalize_label("货币资金"))
    note_candidates = [
        index for index, block in enumerate(parsed.blocks) if block.text.strip() == "1、货币资金"
    ]
    note_start = note_candidates[-1] if note_candidates else None
    if monetary and note_start is not None:
        note_heading = parsed.blocks[note_start].text.strip()
        for block in parsed.blocks[note_start + 1:]:
            if block.block_type == "heading" and block.text.strip() != note_heading:
                break
            if block.section.strip() != note_heading:
                break
            detail_labels = ("库存现金", "银行存款", "其他货币资金")
            if sum(label in block.text for label in detail_labels) < 2:
                continue
            for line in block.text.splitlines():
                if not re.match(r"\s*(合\s*计|合计)\s*(?:\||\s)", line):
                    continue
                values = tuple(value for value in (_parse_number(item) for item in NUMBER_PATTERN.findall(line)) if value is not None)
                raw = tuple(NUMBER_PATTERN.findall(line))
                if values and not _numbers_equal(values[0], monetary.values[0]):
                    key = ("intra-document", "货币资金")
                    if key not in seen:
                        seen.add(key)
                        note_total = ValueLocation(
                            "货币资金附注合计", values, raw, block.page,
                            block.paragraph_index, block.section, line.strip(),
                        )
                        risks.append(_risk(
                            title="货币资金附注合计与资产负债表不一致",
                            description=(
                                f"合并资产负债表列示货币资金期末余额 {monetary.raw_values[0]}，"
                                f"货币资金附注合计为 {raw[0]}，差额 {_format_number(values[0] - monetary.values[0])}。"
                            ),
                            current=note_total,
                            recommendation=(
                                "先按银行对账单和财务底稿核对差额是否属于定期存款、大额存单或受限资金的报表重分类。"
                                "若相关款项已从货币资金重分类至一年内到期的非流动资产或其他报表项目，应从本附注明细中剔除，"
                                "或明确披露附注统计口径及与资产负债表的调节过程；若不属于重分类，则逐项核对库存现金、"
                                "银行存款、其他货币资金和未到期应收利息，统一本表、资产负债表、现金流量表及相关附注。"
                            ),
                            confidence=0.99,
                            regulation_basis=FINANCIAL_STATEMENT_NOTE_BASIS,
                            locations=[
                                ("合并资产负债表：货币资金期末余额", monetary),
                                ("货币资金附注：合计", note_total),
                            ],
                        ))
                break
    for block in parsed.blocks:
        if "现金和现金等价物的构成" not in block.section and "现金和现金等价物的构成" not in block.text:
            continue
        row_values: dict[str, tuple[float, str]] = {}
        for line in block.text.splitlines():
            cells = [cell.strip() for cell in line.strip(" |").split("|")]
            if len(cells) < 2:
                continue
            value = _parse_number(cells[1])
            if value is None:
                continue
            if cells[0].startswith("一、现金"):
                row_values["cash"] = (value, cells[1])
            elif cells[0].startswith("三、期末现金及现金等价物余额"):
                row_values["ending"] = (value, cells[1])
        cash = row_values.get("cash")
        ending = row_values.get("ending")
        if not cash or not ending:
            continue
        if cash and ending and not _numbers_equal(cash[0], ending[0]):
            key = ("intra-document", "现金及现金等价物构成")
            if key not in seen:
                seen.add(key)
                risks.append(_risk(
                    title="现金及现金等价物构成表内部不一致",
                    description=(
                        f"现金和现金等价物构成表列示“一、现金”为 {cash[1]}，"
                        f"“三、期末现金及现金等价物余额”为 {ending[1]}，"
                        f"差额 {_format_number(cash[0] - ending[0])}。当前表内未列示能够解释该差额的现金等价物项目。"
                    ),
                    current=ValueLocation(
                        "期末现金及现金等价物余额", (ending[0],), (ending[1],), block.page,
                        block.paragraph_index, block.section, block.text,
                    ),
                    recommendation=(
                        "核对现金流量表、现金流量表补充资料以及货币资金中受限或不属于现金等价物的明细；"
                        "按底稿重新计算现金及现金等价物期末余额，并统一本表各行及现金净增加额。"
                    ),
                    confidence=0.99,
                    regulation_basis=FINANCIAL_STATEMENT_NOTE_BASIS,
                ))
        break
    operating_percentages = _extract_operating_percentages(parsed)
    for block in parsed.blocks:
        for label, disclosed_location in operating_percentages.items():
            match = re.search(
                rf"{re.escape(label)}为[^。；]{{0,50}}?同比(增长|下降)(\d+(?:\.\d+)?)%",
                block.text,
            )
            if not match:
                continue
            disclosed = disclosed_location.values[0]
            narrative = float(match.group(2)) * (1 if match.group(1) == "增长" else -1)
            if _numbers_equal(narrative, disclosed):
                continue
            key = ("narrative-percentage", label)
            if key in seen:
                continue
            seen.add(key)
            narrative_location = ValueLocation(
                label, (narrative,), (match.group(2) + "%",), block.page,
                block.paragraph_index, block.section, block.text,
            )
            risks.append(_risk(
                title=f"文字分析与表格同比比例不一致：{label}",
                description=(
                    f"主营业务分析表列示 {label} 同比 {disclosed:.2f}%，文字分析列示"
                    f"{match.group(1)} {abs(narrative):.2f}%，两处相差 {abs(disclosed - narrative):.2f} 个百分点。"
                ),
                current=narrative_location,
                recommendation=(
                    "以财务底稿中的本期数、上期数重新计算同比比例，确认正确数值后同步修改主营业务分析表、"
                    "管理层讨论文字、摘要和相关图表。"
                ),
                confidence=0.99,
                level="medium",
                locations=[
                    ("主营业务分析表：同比比例", disclosed_location),
                    ("主营业务文字分析：同比说明", narrative_location),
                ],
            ))

    risks.extend(_statement_equation_risks(balance, income, cash_flow, seen))
    risks.extend(_operating_statement_consistency_risks(parsed, income, cash_flow, seen))
    risks.extend(_operating_percentage_calculation_risks(parsed, seen))
    return risks


def _operating_statement_consistency_risks(
    parsed: ParsedDocument,
    income: dict[str, ValueLocation],
    cash_flow: dict[str, ValueLocation],
    seen: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    mappings = {
        "营业收入": ("合并利润表", income, "营业收入"),
        "营业成本": ("合并利润表", income, "营业成本"),
        "销售费用": ("合并利润表", income, "销售费用"),
        "管理费用": ("合并利润表", income, "管理费用"),
        "财务费用": ("合并利润表", income, "财务费用"),
        "所得税费用": ("合并利润表", income, "所得税费用"),
        "经营活动产生的现金流量净额": ("合并现金流量表", cash_flow, "经营活动产生的现金流量净额"),
        "投资活动产生的现金流量净额": ("合并现金流量表", cash_flow, "投资活动产生的现金流量净额"),
        "筹资活动产生的现金流量净额": ("合并现金流量表", cash_flow, "筹资活动产生的现金流量净额"),
        "现金及现金等价物净增加额": ("合并现金流量表", cash_flow, "现金及现金等价物净增加额"),
    }
    normalized_mappings = {_normalize_label(label): value for label, value in mappings.items()}
    for block in parsed.blocks:
        if "主营业务分析" not in block.section:
            continue
        for line in block.text.splitlines():
            cells = [cell.strip() for cell in line.strip(" |").split("|")]
            if len(cells) < 3:
                continue
            mapping = normalized_mappings.get(_normalize_label(cells[0]))
            if not mapping:
                continue
            statement_name, statement_rows, statement_label = mapping
            statement_item = statement_rows.get(_normalize_label(statement_label))
            current_value = _parse_number(cells[1])
            prior_value = _parse_number(cells[2])
            if (
                statement_item is None or len(statement_item.values) < 2
                or current_value is None or prior_value is None
            ):
                continue
            current_mismatch = not _numbers_equal(current_value, statement_item.values[0])
            prior_mismatch = not _numbers_equal(prior_value, statement_item.values[1])
            if not current_mismatch and not prior_mismatch:
                continue
            key = ("operating-statement", _normalize_label(cells[0]))
            if key in seen:
                continue
            seen.add(key)
            operating_item = ValueLocation(
                cells[0], (current_value, prior_value), (cells[1], cells[2]), block.page,
                block.paragraph_index, block.section, line.strip(),
            )
            differences = []
            if current_mismatch:
                differences.append(
                    f"本期差额 {_format_number(current_value - statement_item.values[0])}"
                )
            if prior_mismatch:
                differences.append(
                    f"上期差额 {_format_number(prior_value - statement_item.values[1])}"
                )
            risks.append(_risk(
                title=f"主营业务分析表与{statement_name}不一致：{cells[0]}",
                description=(
                    f"主营业务分析表列示本期 {cells[1]}、上期 {cells[2]}；{statement_name}列示本期 "
                    f"{statement_item.raw_values[0]}、上期 {statement_item.raw_values[1]}，"
                    f"{'、'.join(differences)}。"
                ),
                current=operating_item,
                recommendation=(
                    "以财务底稿和合并财务报表为准逐位核对金额及正负号；修正后同步更新主营业务分析表、"
                    "同比比例、变动原因、摘要和相关图表，并重新执行现金流及同比勾稽。"
                ),
                confidence=0.99,
                regulation_basis=FINANCIAL_CONSISTENCY_BASIS,
                locations=[
                    ("主营业务分析表", operating_item),
                    (statement_name, statement_item),
                ],
            ))
    return risks


def _statement_equation_risks(
    balance: dict[str, ValueLocation],
    income: dict[str, ValueLocation],
    cash_flow: dict[str, ValueLocation],
    seen: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []

    def item(rows: dict[str, ValueLocation], label: str) -> ValueLocation | None:
        return rows.get(_normalize_label(label))

    def add_equation(
        key: str,
        title: str,
        result: ValueLocation | None,
        components: list[tuple[ValueLocation | None, float]],
        formula: str,
    ) -> None:
        if not result or not result.values or any(component is None or not component.values for component, _ in components):
            return
        expected = sum(component.values[0] * factor for component, factor in components if component)
        actual = result.values[0]
        if _numbers_equal(actual, expected) or ("equation", key) in seen:
            return
        seen.add(("equation", key))
        risks.append(_risk(
            title=title,
            description=(
                f"按“{formula}”复算应为 {_format_number(expected)}，报表列示 {result.raw_values[0]}，"
                f"差额 {_format_number(actual - expected)}。"
            ),
            current=result,
            recommendation="回查财务底稿和组成项目，修正错误数值后同步更新合计行、附注、摘要和相关文字分析，并重新执行整表勾稽。",
            confidence=0.99,
            regulation_basis=FINANCIAL_CONSISTENCY_BASIS,
            locations=[
                (f"计算结果：{result.label}", result),
                *[(f"组成项目：{component.label}", component) for component, _ in components if component],
            ],
        ))

    add_equation(
        "assets-components",
        "资产合计勾稽不一致",
        item(balance, "资产总计"),
        [(item(balance, "流动资产合计"), 1), (item(balance, "非流动资产合计"), 1)],
        "流动资产合计 + 非流动资产合计 = 资产总计",
    )
    add_equation(
        "liabilities-components",
        "负债合计勾稽不一致",
        item(balance, "负债合计"),
        [(item(balance, "流动负债合计"), 1), (item(balance, "非流动负债合计"), 1)],
        "流动负债合计 + 非流动负债合计 = 负债合计",
    )
    add_equation(
        "balance-sheet",
        "资产负债表恒等式不成立",
        item(balance, "资产总计"),
        [(item(balance, "负债合计"), 1), (item(balance, "所有者权益合计"), 1)],
        "负债合计 + 所有者权益合计 = 资产总计",
    )
    add_equation(
        "operating-profit",
        "利润总额勾稽不一致",
        item(income, "利润总额"),
        [(item(income, "营业利润"), 1), (item(income, "营业外收入"), 1), (item(income, "营业外支出"), -1)],
        "营业利润 + 营业外收入 - 营业外支出 = 利润总额",
    )
    add_equation(
        "net-profit",
        "净利润勾稽不一致",
        item(income, "净利润"),
        [(item(income, "利润总额"), 1), (item(income, "所得税费用"), -1)],
        "利润总额 - 所得税费用 = 净利润",
    )
    add_equation(
        "cash-ending",
        "期末现金及现金等价物余额勾稽不一致",
        item(cash_flow, "期末现金及现金等价物余额"),
        [(item(cash_flow, "期初现金及现金等价物余额"), 1), (item(cash_flow, "现金及现金等价物净增加额"), 1)],
        "期初现金及现金等价物余额 + 净增加额 = 期末余额",
    )
    add_equation(
        "cash-net-components",
        "现金及现金等价物净增加额勾稽不一致",
        item(cash_flow, "现金及现金等价物净增加额"),
        [
            (item(cash_flow, "经营活动产生的现金流量净额"), 1),
            (item(cash_flow, "投资活动产生的现金流量净额"), 1),
            (item(cash_flow, "筹资活动产生的现金流量净额"), 1),
            (item(cash_flow, "汇率变动对现金及现金等价物的影响"), 1),
        ],
        "经营活动净额 + 投资活动净额 + 筹资活动净额 + 汇率变动影响 = 现金及现金等价物净增加额",
    )
    return risks


def _operating_percentage_calculation_risks(
    parsed: ParsedDocument,
    seen: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    labels = {
        "营业收入", "营业成本", "销售费用", "管理费用", "研发投入", "研发费用", "财务费用", "所得税费用",
        "经营活动产生的现金流量净额", "投资活动产生的现金流量净额", "筹资活动产生的现金流量净额",
        "现金及现金等价物净增加额",
    }
    normalized_labels = {_normalize_label(label) for label in labels}
    for block in parsed.blocks:
        if "主营业务分析" not in block.section:
            continue
        for line in block.text.splitlines():
            cells = [cell.strip() for cell in line.strip(" |").split("|")]
            if len(cells) < 4 or _normalize_label(cells[0]) not in normalized_labels:
                continue
            try:
                calculation = calculate_financial_change(
                    cells[1],
                    cells[2],
                    semantic=("cash_flow" if _normalize_label(cells[0]) in {
                        _normalize_label(label) for label in CASH_FLOW_CHANGE_LABELS
                    } else "profit_loss"),
                    label=cells[0],
                )
                disclosed = decimal_value(cells[3].rstrip("%"))
            except ValueError:
                continue
            calculation_data = calculation.to_dict()
            if calculation.display_yoy_rate is None:
                key = ("percentage-semantics", cells[0])
                title = f"同比变动展示语义不当：{cells[0]}"
                description = (
                    f"本期 {cells[1]}、上期 {cells[2]}，应表述为“{calculation.display_change_text}”；"
                    f"表格当前列示 {cells[3]}。该场景不适合展示传统同比增长率或下降率。"
                )
                recommendation = (
                    f"将同比栏改为“{calculation.display_change_type}”或“不适用”，并在变动原因中列示本期数与上期数；"
                    "不得使用内部 raw_yoy_rate 生成增长、下降或涨跌幅文字。同步核对摘要、管理层讨论和相关图表。"
                )
            else:
                difference = abs(calculation.display_yoy_rate - disclosed)
                if difference < decimal_value("0.05"):
                    continue
                key = ("percentage-calculation", cells[0])
                title = f"同比比例计算不一致：{cells[0]}"
                description = (
                    f"按“（本期数－上年同期数）÷ 上年同期数 × 100%”复算："
                    f"本期 {cells[1]}、上期 {cells[2]}，{calculation.display_change_text}，"
                    f"表格列示 {cells[3]}，相差 {difference:.2f} 个百分点。"
                )
                recommendation = (
                    "以财务底稿确认本期数和上年同期数，仅在上年同期数为正且本期数非负时计算并展示同比比例；"
                    "修正后同步核对表格、文字分析、摘要和图表中的该比例。"
                )
            if key in seen:
                continue
            seen.add(key)
            risks.append(_risk(
                title=title,
                description=description,
                current=ValueLocation(
                    cells[0], (float(disclosed),), (cells[3],), block.page,
                    block.paragraph_index, block.section, line.strip(),
                ),
                recommendation=recommendation,
                confidence=0.99,
                regulation_basis=FINANCIAL_CONSISTENCY_BASIS,
                level="medium",
                calculation=calculation_data,
            ))
    return risks


def _extract_operating_percentages(parsed: ParsedDocument) -> dict[str, ValueLocation]:
    # Revenue and cost may appear for many individual business lines in the narrative;
    # limiting this check to unambiguous expense labels avoids cross-segment false positives.
    labels = ("销售费用", "管理费用", "研发费用")
    results: dict[str, ValueLocation] = {}
    for block in parsed.blocks:
        if "主营业务分析" not in block.section:
            continue
        for line in block.text.splitlines():
            cells = [cell.strip() for cell in line.strip(" |").split("|")]
            if len(cells) < 4 or cells[0] not in labels:
                continue
            try:
                calculation = calculate_financial_change(cells[1], cells[2], label=cells[0])
            except ValueError:
                continue
            if calculation.display_yoy_rate is None:
                continue
            value = _parse_number(cells[3].rstrip("%"))
            if value is not None:
                results.setdefault(cells[0], ValueLocation(
                    cells[0], (value,), (cells[3],), block.page,
                    block.paragraph_index, block.section, line.strip(),
                ))
    return results


def _append_difference_risk(
    risks: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    category: str,
    label: str,
    current_value: float,
    current_raw: str,
    baseline_value: float,
    baseline_raw: str,
    current_location: ValueLocation,
    citation: dict[str, Any],
    baseline_location: ValueLocation,
    reason: str,
    recommendation: str,
    regulation_basis: list[dict[str, Any]],
) -> None:
    key = (category, _normalize_label(label))
    if key in seen or _numbers_equal(current_value, baseline_value):
        return
    seen.add(key)
    source = {
        **citation,
        "page": baseline_location.page,
        "section": baseline_location.section,
        "content": baseline_location.text,
        "citation_kind": "period_comparison",
    }
    risks.append(_risk(
        title=f"跨期比较数不一致：{label}",
        description=(
            f"{reason}：本报告为 {current_raw}，对比基线为 {baseline_raw}，"
            f"差额 {_format_number(current_value - baseline_value)}。该差异不自动等同于违规，但必须有可核验的调整依据。"
        ),
        current=current_location,
        recommendation=recommendation,
        confidence=0.99,
        sources=[source],
        regulation_basis=regulation_basis,
    ))


def _risk(
    *,
    title: str,
    description: str,
    current: ValueLocation,
    recommendation: str,
    confidence: float,
    sources: list[dict[str, Any]] | None = None,
    regulation_basis: list[dict[str, Any]] | None = None,
    level: str = "high",
    locations: list[tuple[str, ValueLocation]] | None = None,
    risk_type: str = "跨期及勾稽一致性",
    calculation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    location_items = []
    seen_locations: set[tuple[int, str, str]] = set()
    for label, item in (locations or [(current.label, current)]):
        key = (item.paragraph, item.section, item.text)
        if key in seen_locations:
            continue
        seen_locations.add(key)
        location_items.append({
            "label": label,
            "page": item.page,
            "section": item.section,
            "paragraphIndex": item.paragraph,
            "text": item.text,
        })
    return {
        "level": level,
        "type": risk_type,
        "title": title,
        "description": description,
        "evidence": current.text,
        "source_text": current.text,
        "page": current.page,
        "section": current.section,
        "paragraph_index": current.paragraph,
        "location": {
            "page": current.page,
            "section": current.section,
            "paragraph": current.paragraph,
            "items": location_items,
        },
        "regulation_basis": [dict(item) for item in (regulation_basis or FINANCIAL_CONSISTENCY_BASIS)],
        "company_basis": [],
        "internal_rule_basis": [],
        "historical_cases": [],
        "source_documents": sources or [],
        "recommendation": recommendation,
        "confidence": confidence,
        "calculation": calculation or {},
    }


def _baseline_citation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(row.get("title") or ""),
        "document_id": str(row.get("id") or ""),
        "source": str(row.get("source") or "巨潮资讯网"),
        "source_url": str(row.get("source_url") or ""),
        "date": str(row.get("publication_date") or ""),
        "version": str(row.get("version") or "巨潮资讯网披露版本"),
        "document_type": "announcements",
    }


def _baseline_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    title = str(row.get("title") or "")
    preferred = 1 if "更新后" in title else 0
    return preferred, str(row.get("publication_date") or ""), str(row.get("announcement_id") or "")


def _parse_statement_line(line: str) -> tuple[str, tuple[str, ...], tuple[float, ...]] | None:
    line = line.strip().strip("|").strip()
    if not line:
        return None
    if "|" in line:
        cells = [cell.strip() for cell in line.split("|")]
        label = cells[0].strip(" ：:")
        raw_values = tuple(
            cell for cell in cells[1:]
            if NUMBER_PATTERN.fullmatch(cell.replace(" ", ""))
        )[:2]
        parsed_values = tuple(_parse_number(value) for value in raw_values)
        if label and len(parsed_values) >= 2 and all(value is not None for value in parsed_values):
            return label, raw_values, tuple(float(value) for value in parsed_values if value is not None)
        return None
    matches = list(re.finditer(r"(?<!\S)\(?[+\-−—－]?\d[\d,]*(?:\.\d+)?\)?(?=\s|$)", line))
    if len(matches) < 2:
        return None
    label = line[:matches[0].start()].strip(" |：:")
    if not label or re.fullmatch(r"[年月日\d\s]+", label):
        return None
    raw_values = tuple(match.group(0) for match in matches[:2])
    parsed_values = tuple(_parse_number(value) for value in raw_values)
    if any(value is None for value in parsed_values):
        return None
    return label, raw_values, tuple(float(value) for value in parsed_values if value is not None)


def _normalize_label(value: str) -> str:
    normalized = re.sub(r"[\s|：:]", "", value).replace("其中：", "其中")
    normalized = re.sub(r"^(?:[一二三四五六七八九十]+、|\d+[、.])", "", normalized)
    return normalized


def _parse_number(value: str) -> float | None:
    normalized = value.strip().replace(",", "").replace("−", "-").replace("—", "-").replace("－", "-")
    negative_parentheses = normalized.startswith("(") and normalized.endswith(")")
    normalized = normalized.strip("()")
    try:
        number = float(normalized)
    except ValueError:
        return None
    return -abs(number) if negative_parentheses else number


def _numbers_equal(left: float, right: float) -> bool:
    tolerance = max(0.011, abs(right) * 1e-9)
    return abs(left - right) <= tolerance


def _format_number(value: float) -> str:
    return f"{value:,.2f}"


__all__ = [
    "PeriodicReportIdentity",
    "compare_periodic_report",
    "detect_periodic_report_identity",
    "extract_statement_rows",
    "extract_summary_metrics",
    "select_baseline_rows",
]
