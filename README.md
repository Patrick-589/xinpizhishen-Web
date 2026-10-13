# 信披智审

信披智审是面向上市公司证券合规工作的本地审阅平台。项目目前以某科技有限公司（证券代码：******）的公开资料和业务场景为基础，支持事项合规判断、披露文件审查、财务勾稽、资料检索与文书起草。系统提供风险线索和依据定位，最终披露、审批及合规结论仍须由业务人员核实。

## 主要功能

- **事项判断**：录入日常经营合同、股权买卖或对外投资事项，按金额、财务基准、关联关系等信息提示披露和审议义务，并展示规则依据。
- **文档审查**：上传公告或报告，查看风险项、原文位置、适用规则与修改建议；支持人工确认和审计留痕。
- **财务勾稽**：对定期报告及对比材料进行本地结构化取数、金额复算和一致性检查。
- **资料与规则库**：检索公司公告、对标公司公告、监管规则及导入的本地资料；管理员可维护共享知识库。
- **文书起草与对话**：根据已知事实和可检索资料生成草稿，或在个人工作区查询资料；缺失的事实保留待补充提示。
- **账号隔离**：各账号的任务、上传文件、对话和用量独立保存，公共法规底库供授权用户共同检索。

## 快速开始（Windows 11）

首次安装需要联网获取 Python 依赖和本地 Embedding 模型。请保留整个项目文件夹，不要单独移动根目录的 `.cmd` 文件。

1. 克隆仓库，或从 GitHub 下载 ZIP 并解压：

   ```powershell
   git clone https://github.com/Patrick-589/app.git
   cd app
   ```

2. 在**首次启动前**创建根目录 `.env`，并设置独立的管理员密码和应用密钥：

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

   至少填写 `BOOTSTRAP_ADMIN_PASSWORD`（不少于 8 位）和 `APP_SECRET`（至少 32 个字符）。源码在开发模式下有后备管理员口令，因此不要跳过这一步后将服务开放给其他设备。已初始化的管理员密码不会因随后修改 `.env` 而自动变更，应登录后在账号设置中修改。

3. 双击 `安装信披智审_Windows.cmd`。安装器会准备项目独立的 Python 环境、依赖和模型，并创建桌面快捷方式；缺少 Python 或 Node.js 时会尝试通过 `winget` 安装。以后可双击桌面快捷方式或 `打开信披智审_Windows.cmd` 启动。

4. 打开 [http://127.0.0.1:8767/index.html#tasks](http://127.0.0.1:8767/index.html#tasks)，使用管理员账号登录，或在允许注册时创建个人账号。启动器默认使用 `8767` 端口；端口被占用时会提示错误。

安装器会尝试安装 Poppler，用于扫描 PDF 的本地 OCR；普通文本型 PDF、Word 和 Excel 文档不依赖它。安装与局域网访问细节见 [Windows 使用说明](web/README.md)。

## 日常使用

1. 在“文档审查”中新建任务，选择审查类型并上传文件。界面支持 PDF、DOC/DOCX、XLS/XLSX、CSV、TXT、MD 和 JSON；旧版 `.doc` 的正文提取依赖 Windows IFilter。默认单文件上限为 20 MB，可通过 `MAX_UPLOAD_BYTES` 调整。
2. 在审阅结果中核对风险、原文和规则出处，并由人工确认处理结果。定期报告任务还可查看“财务勾稽”。
3. 在“资料与规则库”中检索公开规则与公告；管理员可导入共享资料。个人审查材料不会自动变成其他账号可见的共享知识。
4. 需要更新公开公告和规则索引时，在项目根目录运行：

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\web\update-data.ps1
   ```

数据来源、更新范围和失败处理见 [数据更新说明](web/DATA_UPDATE.md)。

## AI 与数据处理

默认使用 `BAAI/bge-m3` 在本机生成 Embedding，并由 FAISS 保存和检索向量。文档解析、扫描 PDF 的 OCR、规则计算及本地索引均在运行机器上执行。首次安装模型需要联网；安装完成后，本地检索可离线运行。

| `AI_MODE` | 行为 |
| --- | --- |
| `local_rag`（默认） | 本地检索与确定性规则检查，不调用外部 AI，也不提供模型推理结论。 |
| `local_llm` | 本地检索后调用仅限回环地址的本机 LLM 服务，需配置 `LOCAL_LLM_MODEL` 等变量。 |
| `cloud` | 先完成本地检索，再将回答所需的检索上下文发送给已配置的阿里云对话模型；Embedding 仍在本机。 |

配置项以 [.env.example](.env.example) 为准。阿里云密钥只应放在未提交的 `.env` 或服务器环境变量中，不能写入前端或提交到 Git。`web/runtime/` 存放本地数据库、上传文件、模型和索引，已被 Git 忽略。更多边界见 [安全说明](web/SECURITY.md)。

## 项目结构

| 路径 | 用途 |
| --- | --- |
| `web/index.html`、`web/styles.css`、`web/app.js` | 原生 HTML/CSS/JavaScript 前端。 |
| `web/server.py`、`web/backend/` | Python 本地 HTTP 服务、账号、解析、规则、RAG 和审阅逻辑。 |
| `web/data/`、`web/*-data.js` | 随仓库提供的公告与规则索引数据。 |
| `web/scripts/` | 数据同步、知识导入、索引维护和验证脚本。 |
| `web/tests/` | 后端自动化测试。 |
| `web/runtime/` | 本机运行数据；安装后生成，不提交到仓库。 |

## 开发与验证

项目没有前端构建步骤。已安装依赖后，可在项目根目录启动本地服务；默认只绑定回环地址：

```powershell
python .\web\server.py --bind 127.0.0.1 --port 8767
```

常用检查命令：

```powershell
python -m unittest discover -s web\tests -v
node web\scripts\check-dom-contract.mjs
node web\scripts\validate-production-env.mjs --scan-only
```

完整安装流程、检索模式和测试步骤见 [web/README.md](web/README.md) 与 [MVP 测试说明](web/MVP_TESTING.md)。

## 使用边界

本项目的规则、公告和财务基准需要结合最新官方文件及公司制度复核。自动审查结果是工作辅助，不应直接作为法律意见、审批结论或最终披露文本。跨设备访问仅应通过可信局域网或受控私网进行，不应把本地服务端口直接映射到公网。
