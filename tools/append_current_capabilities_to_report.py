from pathlib import Path
import shutil

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_BREAK
from docx.shared import Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


SOURCE = Path(r"C:\Users\PC\Documents\xwechat_files\wxid_7yl550r0scou12_8323\msg\file\2026-08\AI证券合规风险管理与智能审阅平台可行性研究报告(2).docx")
OUTPUT = Path(r"C:\Users\PC\Documents\ChatGPT\创业黑马\AI证券合规风险管理与智能审阅平台可行性研究报告_最终更新版.docx")


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=90, start=110, bottom=90, end=110):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_borders(table, color="D9D9D9", size="6"):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = qn(f"w:{edge}")
        element = borders.find(tag)
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), color)


def set_run_font(run, name="等线", size=10.5, bold=False, color="000000"):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)


def add_body(doc, text, bold_prefix=None):
    p = doc.add_paragraph(style="Normal")
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.15
    if bold_prefix and text.startswith(bold_prefix):
        lead = p.add_run(bold_prefix)
        set_run_font(lead, bold=True)
        rest = p.add_run(text[len(bold_prefix):])
        set_run_font(rest)
    else:
        run = p.add_run(text)
        set_run_font(run)
    return p


def add_bullet(doc, text):
    p = doc.add_paragraph(style="Normal")
    p.paragraph_format.left_indent = Pt(14)
    p.paragraph_format.first_line_indent = Pt(-10)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.12
    run = p.add_run("• " + text)
    set_run_font(run)
    return p


def add_heading(doc, text):
    p = doc.add_paragraph(style="Heading 2")
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(text)
    set_run_font(run, size=13, bold=True)
    return p


def add_subheading(doc, text):
    style_name = "Heading 3" if "Heading 3" in [s.name for s in doc.styles] else "Heading 2"
    p = doc.add_paragraph(style=style_name)
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    set_run_font(run, size=11.5, bold=True)
    return p


def add_steps_table(doc):
    table = doc.add_table(rows=1, cols=3)
    table.autofit = True
    table.style = "Table Grid"
    set_table_borders(table)
    headers = ["步骤", "操作", "完成标志"]
    for cell, value in zip(table.rows[0].cells, headers):
        set_cell_shading(cell, "333333")
        set_cell_margins(cell)
        cell.vertical_alignment = 1
        paragraph = cell.paragraphs[0]
        paragraph.alignment = 1
        run = paragraph.add_run(value)
        set_run_font(run, size=10, bold=True, color="FFFFFF")

    rows = [
        ("1", "将完整项目文件夹复制到新电脑。若要保留现有账号、资料、模型和索引，必须一并复制 web/runtime 文件夹。", "项目目录完整"),
        ("2", "首次运行 安装信披智审_Windows.cmd。按提示安装项目自带运行环境和依赖；本地模型首次安装可运行 web\\install-local-embedding.ps1。", "安装脚本无报错"),
        ("3", "双击 打开信披智审_Windows.cmd，启动本机服务并在浏览器打开首页。", "看到登录页面"),
        ("4", "双击 设置信披智审开机与更新_Windows.cmd，注册 Windows 登录后自动启动和每日资料库更新任务。", "任务状态为 Ready"),
        ("5", "如需让同一局域网手机或其他电脑访问，以管理员身份执行：powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\web\\register-windows-tasks.ps1 -InstallFirewall。", "8767 端口放行"),
        ("6", "在 web\\runtime\\access-url.txt 查看当前 LAN URL，并在其他设备浏览器访问该地址。设备需连接同一局域网。", "其他设备显示登录页"),
        ("7", "重启新电脑并登录 Windows，等待服务启动后再次访问 LAN URL。电脑关机时其他设备不能访问。", "无需手工启动服务"),
    ]
    for step, action, done in rows:
        cells = table.add_row().cells
        for cell in cells:
            set_cell_margins(cell)
            cell.vertical_alignment = 1
        cells[0].paragraphs[0].alignment = 1
        for cell, value in zip(cells, (step, action, done)):
            run = cell.paragraphs[0].add_run(value)
            set_run_font(run, size=9.5, bold=(cell is cells[0]))
        if len(table.rows) % 2 == 0:
            for cell in cells:
                set_cell_shading(cell, "F7F7F7")
    return table


def main():
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, OUTPUT)
    # Some downloaded Word attachments carry the Windows read-only attribute.
    # Clear it on the working copy before python-docx rewrites the package.
    OUTPUT.chmod(0o666)
    doc = Document(OUTPUT)

    # Keep the new material visually separate from the original report.
    page_break = doc.add_paragraph()
    page_break.add_run().add_break(WD_BREAK.PAGE)

    add_heading(doc, "十一、当前应用能力")
    add_body(doc, "当前版本已形成可在 Windows 本机独立运行的证券合规审阅应用。系统不依赖 Codex 才能启动，当前本地模式不调用任何外部大模型或 Embedding API；阿里云大模型仅保留为后续经公司批准后的可选推理接口。")
    add_bullet(doc, "账号与权限：支持注册、登录、修改密码和注销账号；管理员可维护账号及共享资料，普通用户可使用共享知识库但不能修改知识库。不同账号的审查任务、上传文件、风险、对话和任务记忆相互隔离。")
    add_bullet(doc, "资料导入与解析：支持 PDF、扫描 PDF、DOC/DOCX、XLS/XLSX、CSV、TXT、MD 和 JSON 文件，支持批量或文件夹导入；扫描 PDF 使用本地 OCR。")
    add_bullet(doc, "本地知识库与 RAG：资料、规则、公告和上传文件统一保存在本地知识库；使用 BAAI/bge-m3 本地 Embedding、FAISS 向量索引，并保留关键词检索、语义检索和可扩展的混合检索。")
    add_bullet(doc, "可追溯审阅：对风险、原文、页码、章节、文件和法规依据建立关联；点击风险可回到原文位置，支持人工确认、取消确认和审计留痕。")
    add_bullet(doc, "财务与多文档核对：支持文档与 XLS/XLSX 数据勾稽、多个参考文档对比、数字和日期差异提示，并统一处理正负数、由负转正、亏损收窄或扩大等同比边界。")
    add_bullet(doc, "文书起草：可基于本地资料和既有案例模板起草会议通知、议案、决议、签到或汇报文稿，结果可下载后继续人工修改。")
    add_bullet(doc, "运行与维护：支持真实处理进度、增量 Embedding、失败重试和索引重建；已配置 Windows 登录后启动服务及每日资料库更新任务，并支持局域网电脑和手机访问。")

    add_subheading(doc, "当前使用边界")
    add_body(doc, "系统输出属于合规辅助审阅结果，不替代公司证券部、董秘办、法务或有权机构的最终判断。跨不同网络访问需要部署到公司服务器或经批准的安全网络环境；当前局域网地址依赖运行服务的电脑开机，电脑关机时其他设备无法访问。法规和公告自动更新需要更新时具备网络连接，更新完成后的本地检索可断网运行。")

    add_heading(doc, "十二、未来可以跟进的方向")
    add_bullet(doc, "企业级部署：迁移到公司内网服务器，增加 HTTPS、反向代理、备份恢复、监控告警和更严格的网络访问控制。")
    add_bullet(doc, "模型增强：在公司完成数据权限、预算和安全评估后，接入公司批准的阿里云 LLM；LLM 只能基于已检索、已核验的事实和证据组织文字，不直接替代规则判断。")
    add_bullet(doc, "规则与版本管理：持续补齐深交所、证监会、财政部及公司制度正文，增加版本差异对比、生效状态管理和更新异常提醒。")
    add_bullet(doc, "解析质量：继续优化复杂表格、合并单元格、负号、公式、脚注和扫描件 OCR，扩大财务报表与披露文本的自动勾稽覆盖范围。")
    add_bullet(doc, "审阅流程：增加审阅任务分派、多人协作、审批流、意见汇总、可追踪 Word 修订和批注导出，形成从初审到终审的闭环。")
    add_bullet(doc, "资料治理：建立版本审批、重复资料识别、定期备份、归档策略和知识库质量抽检，降低过期或来源不明资料影响判断的风险。")

    add_heading(doc, "十三、新电脑安装与开机自启操作步骤")
    add_body(doc, "交付时应将完整项目文件夹作为一个整体复制到新电脑。以下步骤只需在新电脑执行一次；完成后，应用可以脱离 Codex 独立运行。")
    add_steps_table(doc)
    add_body(doc, "补充说明：局域网 URL 可能因路由器 DHCP 分配而变化，每次启动后以 web\\runtime\\access-url.txt 中的 LAN URL 为准。若公司需要固定地址或跨网络访问，应由公司 IT 配置固定内网地址、DNS 或正式部署环境，不建议直接把开发服务暴露到公网。")

    # Ensure the appended paragraphs use the existing document's readable defaults.
    for style_name in ("Normal", "Heading 1", "Heading 2", "Heading 3"):
        try:
            style = doc.styles[style_name]
        except KeyError:
            continue
        style.font.name = "等线"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "等线")

    doc.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
