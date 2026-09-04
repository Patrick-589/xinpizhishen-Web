import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDirectory, '..', '..');
const scanOnly = process.argv.includes('--scan-only');

const ignoredDirectories = new Set([
  '.git',
  'node_modules',
  'assets',
  'data',
  'research',
  'runtime',
  '发布包',
  '.tmp'
]);

const scannedExtensions = new Set([
  '.cjs',
  '.html',
  '.js',
  '.json',
  '.mjs',
  '.py',
  '.ps1',
  '.ts',
  '.tsx',
  '.yaml',
  '.yml'
]);

const secretPatterns = [
  {
    name: '通用 API Key 赋值',
    pattern: /\b(?:api[_-]?key|access[_-]?token|client[_-]?secret)\b\s*[:=]\s*["']([^"']{12,})["']/gi
  },
  {
    name: 'Bearer 凭据',
    pattern: /\bauthorization\b\s*[:=]\s*["']bearer\s+([a-z0-9._-]{16,})["']/gi
  },
  {
    name: '常见模型服务密钥',
    pattern: /\b(sk-[a-z0-9_-]{20,}|AIza[a-z0-9_-]{30,}|AKIA[A-Z0-9]{16})\b/g
  }
];

const obviousPlaceholders = /^(?:change-?me|demo|example|fake|placeholder|replace-?me|test|your[-_])/i;

async function collectSourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    if (entry.isDirectory() && ignoredDirectories.has(entry.name)) continue;
    if (entry.name.startsWith('.env')) continue;

    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...await collectSourceFiles(fullPath));
    } else if (scannedExtensions.has(path.extname(entry.name).toLowerCase())) {
      files.push(fullPath);
    }
  }

  return files;
}

async function scanForHardcodedSecrets() {
  const findings = [];
  const files = await collectSourceFiles(projectRoot);

  for (const file of files) {
    const content = await readFile(file, 'utf8');

    for (const { name, pattern } of secretPatterns) {
      pattern.lastIndex = 0;
      for (const match of content.matchAll(pattern)) {
        const candidate = match[1] || match[0];
        if (obviousPlaceholders.test(candidate)) continue;

        const line = content.slice(0, match.index).split(/\r?\n/).length;
        findings.push({
          file: path.relative(projectRoot, file),
          line,
          type: name
        });
      }
    }
  }

  if (findings.length > 0) {
    console.error('安全校验失败：发现疑似硬编码凭据。仅报告位置，不显示凭据内容。');
    for (const finding of findings) {
      console.error(`- ${finding.file}:${finding.line} (${finding.type})`);
    }
    process.exitCode = 1;
    return false;
  }

  console.log(`密钥扫描通过：已检查 ${files.length} 个源码文件，未发现疑似硬编码凭据。`);
  return true;
}

function validateProductionEnvironment() {
  const aiMode = (process.env.AI_MODE || 'local_rag').trim().toLowerCase();
  const appSecret = process.env.APP_SECRET?.trim();
  const adminPassword = process.env.BOOTSTRAP_ADMIN_PASSWORD?.trim();
  const apiKey = process.env.ALIYUN_API_KEY?.trim();
  const keySource = process.env.COMPANY_AI_API_KEY_SOURCE?.trim().toLowerCase();
  const baseUrl = process.env.ALIYUN_BASE_URL?.trim();
  const model = process.env.ALIYUN_MODEL?.trim();
  const localLlmModel = process.env.LOCAL_LLM_MODEL?.trim();
  const localLlmBaseUrl = (process.env.LOCAL_LLM_BASE_URL || 'http://127.0.0.1:11434/v1').trim();
  const localEmbeddingModel = (process.env.LOCAL_EMBEDDING_MODEL || 'BAAI/bge-m3').trim();
  const localEmbeddingProvider = (process.env.LOCAL_EMBEDDING_PROVIDER || 'bge_m3').trim().toLowerCase();
  const vectorBackend = (process.env.VECTOR_BACKEND || 'faiss').trim().toLowerCase();

  const errors = [];
  if (!['cloud', 'local_rag', 'local_llm'].includes(aiMode)) errors.push('AI_MODE 仅支持 cloud、local_rag 或 local_llm');
  if (!appSecret || appSecret.length < 32 || obviousPlaceholders.test(appSecret)) {
    errors.push('APP_SECRET 必须是至少 32 位的非示例随机值');
  }
  if (!adminPassword || adminPassword.length < 8 || obviousPlaceholders.test(adminPassword)) {
    errors.push('BOOTSTRAP_ADMIN_PASSWORD 必须至少 8 位且不能使用示例值');
  }
  if (!localEmbeddingModel) errors.push('缺少 LOCAL_EMBEDDING_MODEL');
  if (!['bge_m3', 'sentence_transformers'].includes(localEmbeddingProvider)) errors.push('生产环境必须使用本地 Embedding Provider');
  if (!['faiss', 'sqlite', 'pgvector'].includes(vectorBackend)) errors.push('VECTOR_BACKEND 仅支持 faiss、sqlite 或 pgvector');
  if (vectorBackend === 'pgvector' && !(process.env.VECTOR_DB_URL?.trim() || process.env.DATABASE_URL?.trim())) {
    errors.push('pgvector 模式必须配置 VECTOR_DB_URL 或 DATABASE_URL');
  }
  if (aiMode === 'cloud') {
    if (!apiKey || apiKey.length < 12 || obviousPlaceholders.test(apiKey)) errors.push('ALIYUN_API_KEY 缺失、过短或仍是示例值');
    if (!['company', 'personal', 'operator', 'deployment'].includes(keySource)) {
      errors.push('COMPANY_AI_API_KEY_SOURCE 必须标记为 company、personal、operator 或 deployment');
    }
    if (!model) errors.push('缺少 ALIYUN_MODEL');
    if (!baseUrl) errors.push('缺少 ALIYUN_BASE_URL');
  }
  if (aiMode === 'local_llm') {
    if (!localLlmModel) errors.push('local_llm 模式缺少 LOCAL_LLM_MODEL');
    try {
      const localUrl = new URL(localLlmBaseUrl);
      if (!['127.0.0.1', 'localhost', '[::1]'].includes(localUrl.hostname)) errors.push('LOCAL_LLM_BASE_URL 只允许本机回环地址');
    } catch {
      errors.push('LOCAL_LLM_BASE_URL 不是有效 URL');
    }
  }
  if (baseUrl) {
    try {
      const url = new URL(baseUrl);
      if (url.protocol !== 'https:') errors.push('生产环境 ALIYUN_BASE_URL 必须使用 HTTPS');
    } catch {
      errors.push('ALIYUN_BASE_URL 不是有效 URL');
    }
  }

  if (errors.length > 0) {
    console.error('生产环境 AI 配置校验失败：');
    for (const error of errors) console.error(`- ${error}`);
    console.error('校验过程未输出密钥内容。');
    process.exitCode = 1;
    return false;
  }

  console.log(`生产环境配置通过：AI_MODE=${aiMode}，未输出任何密钥内容。`);
  return true;
}

const sourceIsClean = await scanForHardcodedSecrets();
if (sourceIsClean && !scanOnly) validateProductionEnvironment();
