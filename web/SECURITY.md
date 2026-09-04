# AI 与本地向量安全

## 本地 Embedding

- 文档解析、Chunk、Embedding、FAISS 检索和 metadata 持久化全部在本机执行。
- 运行代码只实现 `LocalEmbeddingProvider` 和测试用 `MockEmbeddingProvider`，没有 `AliyunEmbeddingProvider`。
- BGE-M3 首次允许下载；下载完成后通过 `local_files_only=True`、`HF_HUB_OFFLINE=1` 和 `TRANSFORMERS_OFFLINE=1` 加载。
- `AI_MODE=cloud` 也必须先使用本地 Embedding 与本地 FAISS，只允许把 RAG 选出的必要上下文交给阿里云对话模型。
- `AI_MODE=local_rag` 不调用任何外部 AI；`AI_MODE=local_llm` 只允许连接 `127.0.0.1`、`localhost` 或 `::1` 上的本机模型服务。

## 密钥

- `ALIYUN_API_KEY` 只能由服务器进程从环境变量或未提交的 `.env` 读取；`COMPANY_AI_API_KEY_SOURCE` 只填写 `personal`、`operator`、`company` 或 `deployment` 等来源标签，不填写密钥内容。
- 禁止把密钥写入 HTML、前端 JavaScript、源码、URL、日志、报告或浏览器存储。
- 浏览器只调用本系统后端，不得直接调用模型厂商接口。
- `.env.example` 只保留空占位，真实 `.env` 已由 `.gitignore` 排除。

## 独立运行与网络边界

- `web/runtime/venv` 是退出 Codex 后使用的项目独立 Python 环境；通过 `安装信披智审_Windows.cmd` 创建。
- `设置信披智审开机与更新_Windows.cmd` 只注册当前 Windows 用户的登录启动和每日更新任务，不会创建公网服务。
- 服务绑定 `0.0.0.0:8767` 仅为受控局域网访问；防火墙脚本只放行 Windows 专用网络的本地子网。跨网络访问必须经过公司 VPN 或同等受控私网，不得直接端口转发到公网。
- 自动更新失败时保留上一次已成功的索引和正文，错误写入 `web/runtime/logs/auto-update.log`，不会用残缺结果覆盖可用知识库。

生产环境阿里云对话模型变量：

```text
ALIYUN_API_KEY=
COMPANY_AI_API_KEY_SOURCE=personal
ALIYUN_BASE_URL=
ALIYUN_MODEL=
```

Embedding 不读取以上变量。模型名称和本地路径由服务器端的 `LOCAL_EMBEDDING_MODEL`、`LOCAL_EMBEDDING_MODEL_DIR` 配置。

## 校验

```powershell
node .\web\scripts\validate-production-env.mjs --scan-only
python .\web\scripts\verify_offline_retrieval.py
```

第二条命令会禁止网络连接，再执行本地 Embedding 和 FAISS 检索。输出 `EXTERNAL_EMBEDDING_API: BLOCKED_AND_NOT_USED` 才算通过。
