# 信披智审

本目录运行《上市公司证券合规风险管理与 AI 智能审阅平台》的本机服务。

## Windows 启动

双击项目根目录的 `打开信披智审_Windows.cmd`。启动器默认在 `8767` 端口启动并打开登录页；如果该端口被其他程序占用，会先提示占用情况。

要完全脱离 Codex 运行，首次在这台 Windows 电脑上双击项目根目录的 `安装信披智审_Windows.cmd`。它会自动检测或安装 Python 3.11/3.12、Node.js LTS 和项目依赖，在 `web/runtime/venv` 创建项目独立环境；安装完成后会在桌面创建“信披智审”快捷方式，双击即可用独立应用窗口打开，不依赖 Codex 的运行时。Poppler 用于扫描 PDF 页面渲染，安装器会在可用时自动安装；普通 PDF、Word、Excel 不依赖 Poppler。

需要开机（登录 Windows 后）自动启动，并每天自动更新公告、规则正文和本地 RAG 的，可双击 `设置信披智审开机与更新_Windows.cmd`。它注册两个当前用户计划任务：`信披智审 - 开机启动服务` 和 `信披智审 - 每日更新资料库`（每天 09:00，本机时区）。每日任务会调用现有官方同步脚本，然后执行 `rebuild_embeddings.py --missing-only`，只补建缺失或中断的向量，不重复计算已完成内容。日志位于 `web/runtime/logs/auto-update.log`。

手机或另一台电脑访问时，使用启动器输出的 `LAN URL`，并确保设备与本机处于同一可信“专用网络”。如果 Windows 防火墙阻止访问，请以管理员身份运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\web\register-windows-tasks.ps1 -InstallFirewall
```

该规则只允许专用网络的本地子网访问 8767 端口。不同网络不能直接使用局域网地址；应通过公司 VPN、Tailscale 等受控私网接入，或部署经过身份认证的反向代理，禁止直接端口映射公网。

首次进入可以直接注册个人账号，密码至少 8 位。注册后即可登录自己的工作区。不同账号之间的审查任务、上传资料、公司画像、对话、用量和审计记录相互隔离；公共法规底库由所有账号共同使用。

资料库支持批量导入 PDF、DOCX、CSV、TXT、MD 和 JSON。CSV 会保留原始行号与分组作为引用位置，便于关联方名录等表格资料溯源。

会议起草案例也可以作为共享的 `drafting_materials` 导入。案例只用于学习议案说明、会议结构和发言表达，不会被当作当前公司事实或法规结论。导入本轮提供的桌面案例：

```powershell
python .\web\scripts\import-meeting-cases.py <案例文件夹>
```

若资料来自多个 ZIP，先分别解压到同一个临时文件夹，再递归导入该文件夹内的全部支持格式（PDF、DOC/DOCX、XLS/XLSX、CSV、TXT、MD、JSON）：

```powershell
& '.\web\runtime\gpu-venv\Scripts\python.exe' .\web\scripts\import-meeting-materials.py <解压后的资料文件夹>
```

该命令保留文件夹相对路径、会议案例类型和原文溯源信息；可重复执行，已存在的同一文件会按哈希自动跳过。

起草页可选择“会议通知”“会议签到表”“会议议案”“主要议案概述”“会议记录”“授权委托书”“法律意见书”等类型。选择会议类文书后，可以在“本次会议参考文书”处上传本次议案、会议通知或决议；该文件只用于当前草稿，不会进入共享资料库，系统会保留原文页码和章节并生成对应文书。未从原文识别的姓名、日期、地点、票数和法律结论会保留为“待补充”。不上传本次文书时，其他会议起草类型仍会优先检索管理员维护的同类案例。

开发环境同时保留一个本机恢复管理员账号：

- 用户名：`admin`
- 密码：`Admin123!`

正式使用前必须通过环境变量修改管理员密码。管理员账号也不能通过业务接口查看其他账号的审查内容。

## 本地 Embedding 与检索

默认配置使用 `BAAI/bge-m3` 在 Windows 本机生成 1024 维语义向量，并使用 FAISS 做余弦相似度检索。文件内容和查询文本不会发送给任何 Embedding API。

Embedding 层只包含 `EmbeddingProvider` 抽象、生产使用的 `LocalEmbeddingProvider` 和自动化测试使用的 `MockEmbeddingProvider`。没有阿里云或其他远程 Embedding Provider。

首次安装需要联网下载 Python 依赖和模型：

```powershell
powershell -ExecutionPolicy Bypass -File .\web\install-local-embedding.ps1
```

模型完成下载后始终以 `local_files_only=True` 加载，断网也可进行文件解析、Embedding 和 FAISS 检索。默认路径：

- 模型：`web/runtime/models/bge-m3`
- FAISS：`web/runtime/faiss/local-BAAI-bge-m3-*/index.faiss`
- Metadata：与索引同目录的 `metadata.json`

检索模式通过 `RETRIEVAL_MODE` 切换：`semantic` 为 FAISS 语义检索，`keyword` 为本地关键词检索，`hybrid` 为两者融合。原有 SQLite 和 pgvector 后端仍保留，Windows 默认使用 `VECTOR_BACKEND=faiss`。

默认使用 CPU。配有受支持的 NVIDIA CUDA 环境时，可在服务器环境变量中设置 `LOCAL_EMBEDDING_DEVICE=cuda`；模型和业务代码无需修改。

资料管理页会显示当前模型、向量维度、已 Embedding 文档数、待处理文档数和失败数。Chunk 向量以 `content_hash + embedding_model` 缓存，重复文件和未变化文本不会重复计算。

## 已确认财务案例校准

`web/knowledge/cases/financial_annotation_case_2026.json` 保存了 2026 年半年度财务报表附注的 19 条人工确认批注。审阅引擎会把批注锚点作为案例依据，并将“重复指标不一致、必填金额缺失、专项折旧/租赁/权益法勾稽”等问题抽象为可复用的本地确定性检查；案例中的具体金额只作为证据，不会被硬编码为阈值。

导入新的“原始 DOCX + 批注版 DOCX + 勾稽表格”案例：

```powershell
& '.\\web\\runtime\\gpu-venv\\Scripts\\python.exe' .\\web\\scripts\\import-financial-case.py 原始.docx 批注版.docx 勾稽表格.xls
```

脚本只读取本地文件并更新 `web/knowledge/cases/*.json`，不调用任何外部 AI/API。重新启动服务后，新案例即可用于后续财务审阅与案例引用。

## 精准法规与 Word 修订批注

风险记录会保留全部命中的现行法规，但审查报告和审阅工作台默认只展示一条带明确条款号的“直接适用规则”；其余法规在“其他相关法规”折叠项中保留，便于审计追溯。下载 Word 时使用原始 DOCX 副本写入 Word 原生修订追踪（`w:ins`）和风险批注，原文件不被修改；在 Word 中可逐条接受或拒绝修订。没有明确替换文本的风险只插入带“修订建议”标记的建议，不会擅自删除原文。

定期报告起草会优先检索公司历史年度/半年度报告，将其章节顺序和披露措辞作为格式参考；历史报告中的金额、日期和事实不会直接复制，仍需以本次已确认底稿核实。

重新建立全部有效知识文档索引：

```powershell
python .\web\scripts\rebuild_embeddings.py
```

更换模型时修改服务器环境变量 `LOCAL_EMBEDDING_MODEL` 和 `LOCAL_EMBEDDING_MODEL_DIR`，重新运行下载与重建命令。模型路径只由后端读取，不进入前端代码。

## AI 模式

- `AI_MODE=local_rag`：本地解析、本地向量检索和确定性规则，不调用外部模型，不提供 AI 推理结论。
- `AI_MODE=local_llm`：本地解析、BGE-M3、FAISS 和本机 LLM。设置 `LOCAL_LLM_MODEL` 后可连接仅限回环地址的 Ollama OpenAI 兼容接口。
- `AI_MODE=cloud`：先在本机完成 BGE-M3 和 FAISS 检索，仅将 Top-K 必要上下文交给公司阿里云对话模型。缺少 Key 时仍可运行本地规则审查。

创建根目录 `.env` 可配置本机开发环境。真实 `ALIYUN_API_KEY` 只允许保存在服务器环境变量或未提交的 `.env` 中。

### 公司阿里云 API 接入

应用没有前端 API Key 输入框，也不会把密钥写入浏览器。退出 Codex 后，在运行这台服务器的 Windows 电脑上编辑根目录未提交的 `.env`，由服务端读取以下变量：

```text
AI_MODE=cloud
COMPANY_AI_API_KEY_SOURCE=personal
ALIYUN_API_KEY=由你本人或公司部署平台注入的真实密钥
ALIYUN_BASE_URL=https://公司提供的兼容接口地址
ALIYUN_MODEL=公司批准的对话模型名称
ALIYUN_CHAT_PATH=/chat/completions
```

`cloud` 模式始终先在本机完成文档解析、本地 BGE-M3 Embedding、FAISS 检索和规则检查，只向阿里云发送必要的检索上下文进行最终 LLM 推理。阿里云不参与 Embedding。没有配置密钥时，服务仍可启动并提供本地 RAG/确定性审查；需要云端推理时会明确提示配置不完整。配置完成后重启服务即可生效，业务代码无需修改。`COMPANY_AI_API_KEY_SOURCE` 只是记录密钥来源，可填 `personal`、`operator`、`company` 或 `deployment`。

## 验证命令

```powershell
python -m unittest discover -s web\tests -v
python .\web\scripts\verify_offline_retrieval.py
node web\scripts\check-dom-contract.mjs
node web\scripts\validate-production-env.mjs --scan-only
```

生产发布前去掉 `--scan-only`，并完整配置 `.env.example` 中要求的生产环境变量。
