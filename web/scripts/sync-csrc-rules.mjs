import https from 'node:https';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const categories = [
  {
    id: 'laws-regulations-judicial',
    name: '法律、行政法规和司法解释',
    group: '证监会官方法规',
    dataId: '00a2d3863f014abfb8be3cb5e470abc3'
  },
  {
    id: 'listed-company-rules',
    name: '上市公司类部门规章和规范性文件',
    group: '证监会官方法规',
    dataId: '26c6fc2ad5ee49e2ab2d14ede3ae6fc2'
  }
];

const sourceRoot = 'https://neris.csrc.gov.cn/falvfagui/';
const includeFullText = process.env.CSRC_INCLUDE_FULL_TEXT === '1';
const fullTextConcurrency = Math.max(1, Math.min(Number(process.env.CSRC_FULL_TEXT_CONCURRENCY || 4), 6));
const scriptDir = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(scriptDir, '..');
const dataDir = resolve(webDir, 'data');
const runtimeImportDir = resolve(webDir, 'runtime', 'imports');
const jsPath = resolve(webDir, 'csrc-rules-data.js');
const jsonPath = resolve(dataDir, 'csrc-rules.json');
const bodyCachePath = resolve(runtimeImportDir, 'csrc-rule-bodies.json');
const statusMap = {
  0: { id: 'pending-effective', label: '已颁布未施行' },
  1: { id: 'current-effective', label: '现行有效' },
  2: { id: 'amended', label: '已被修改' },
  3: { id: 'repealed', label: '已被废止' }
};

function sleep(milliseconds) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));
}

let sessionCookie = '';

function mergeCookies(values = []) {
  const cookies = new Map();
  for (const value of values) {
    const pair = String(value || '').split(';', 1)[0];
    const separator = pair.indexOf('=');
    if (separator <= 0) continue;
    cookies.set(pair.slice(0, separator), pair.slice(separator + 1));
  }
  return [...cookies.entries()].map(([key, value]) => `${key}=${value}`).join('; ');
}

function getPage(path) {
  return new Promise((resolvePromise, rejectPromise) => {
    const request = https.request({
      hostname: 'neris.csrc.gov.cn',
      path,
      method: 'GET',
      headers: {
        Accept: 'text/html,application/xhtml+xml',
        'User-Agent': 'Mozilla/5.0 (compatible; XinpizhishenMVP/1.0)'
      }
    }, (response) => {
      response.resume();
      response.on('end', () => {
        if (response.statusCode < 200 || response.statusCode >= 400) {
          rejectPromise(new Error(`CSRC session page returned ${response.statusCode}`));
          return;
        }
        resolvePromise(response.headers['set-cookie'] ?? []);
      });
    });
    request.setTimeout(30000, () => request.destroy(new Error('CSRC session request timed out')));
    request.on('error', rejectPromise);
    request.end();
  });
}

async function initializeSession(recordId, force = false) {
  if (sessionCookie && !force) return;
  const detailPath = `/falvfagui/rdqsHeader/mainbody?navbarId=2&secFutrsLawId=${encodeURIComponent(recordId)}`;
  sessionCookie = mergeCookies(await getPage(detailPath));
  if (!sessionCookie) throw new Error('CSRC detail page did not provide a session cookie');
}

function postForm(path, fields, headers = {}) {
  const body = new URLSearchParams(fields).toString();
  return new Promise((resolvePromise, rejectPromise) => {
    const request = https.request({
      hostname: 'neris.csrc.gov.cn',
      path,
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Content-Length': Buffer.byteLength(body),
        Origin: 'https://neris.csrc.gov.cn',
        Referer: sourceRoot,
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0 (compatible; XinpizhishenMVP/1.0)',
        ...headers
      }
    }, (response) => {
      let raw = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { raw += chunk; });
      response.on('end', () => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          rejectPromise(new Error(`CSRC returned ${response.statusCode}`));
          return;
        }
        try {
          resolvePromise(JSON.parse(raw));
        } catch (error) {
          rejectPromise(new Error(`Invalid CSRC response: ${error.message}`));
        }
      });
    });
    request.setTimeout(30000, () => request.destroy(new Error('CSRC request timed out')));
    request.on('error', rejectPromise);
    request.write(body);
    request.end();
  });
}

async function requestWithRetry(path, fields, attempts = 3, headers = {}, onRetry = null) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await postForm(path, fields, headers);
    } catch (error) {
      lastError = error;
      if (onRetry) await onRetry(attempt, error);
      if (attempt < attempts) await sleep(500 * attempt);
    }
  }
  throw lastError;
}

function plainText(value = '') {
  return String(value)
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/\r\n/g, '\n')
    .trim();
}

function dateValue(value) {
  if (typeof value === 'number' || /^\d{13}$/.test(String(value || ''))) {
    const date = new Date(Number(value));
    if (!Number.isNaN(date.getTime())) return date.toISOString().slice(0, 10);
  }
  const text = String(value || '').trim();
  if (!text) return null;
  const match = text.match(/\d{4}[-/.]\d{1,2}[-/.]\d{1,2}/);
  return match ? match[0].replace(/[/.]/g, '-').replace(/-(\d)(?=-|$)/g, '-0$1') : text;
}

function listRecords(result) {
  const candidates = [result?.pageUtil?.pageList, result?.data?.list, result?.data?.rows, result?.data, result?.list, result?.rows, result?.result];
  return candidates.find((value) => Array.isArray(value)) ?? [];
}

function totalRecords(result) {
  const candidates = [result?.pageUtil?.rowCount, result?.data?.total, result?.data?.totalSize, result?.total, result?.totalSize, result?.totalCount];
  return Number(candidates.find((value) => Number.isFinite(Number(value))) ?? 0);
}

async function fetchCategory(category) {
  const rawRecords = [];
  let expectedTotal = null;
  for (let pageNo = 1; pageNo <= 100; pageNo += 1) {
    const result = await requestWithRetry('/falvfagui/classifyController/indexData', {
      pageNo: String(pageNo),
      tab: '1',
      dataId: category.dataId
    });
    if (result?.success === false) throw new Error(`${category.name} returned success=false`);
    if (expectedTotal == null) expectedTotal = totalRecords(result);
    const records = listRecords(result);
    rawRecords.push(...records);
    if (!records.length || rawRecords.length >= expectedTotal) break;
    await sleep(90);
  }
  const unique = new Map(rawRecords.map((record) => [String(record.secFutrsLawId), record]));
  if (!expectedTotal || unique.size !== expectedTotal) throw new Error(`${category.name} expected ${expectedTotal} records, received ${unique.size}`);
  console.log(`${category.name}: ${unique.size} records`);
  return [...unique.values()];
}

function flattenEntries(entries = []) {
  const sections = [];
  for (const entry of entries) {
    const title = plainText(entry.title || '');
    const content = plainText(entry.cntnt || '');
    if (title || content) sections.push({ id: String(entry.secFutrsLawEntryId || sections.length + 1), title, content });
    for (const item of entry.itemList ?? []) {
      const itemTitle = plainText(item.title || '');
      const itemContent = plainText(item.cntnt || '');
      if (itemTitle || itemContent) sections.push({ id: String(item.secFutrsLawEntryId || `${entry.secFutrsLawEntryId || sections.length}-${sections.length + 1}`), title: itemTitle, content: itemContent });
    }
  }
  return sections;
}

async function fetchFullText(record) {
  const recordId = String(record.secFutrsLawId);
  const referer = `${sourceRoot}rdqsHeader/mainbody?navbarId=2&secFutrsLawId=${encodeURIComponent(recordId)}`;
  await initializeSession(recordId);
  const requestHeaders = { Cookie: sessionCookie, Referer: referer };
  const result = await requestWithRetry('/falvfagui/rdqsHeader/lawlist', {
    body: '',
    secFutrsLawId: recordId,
    secFutrsLawEntryId: '',
    navbarId: '2',
    lawEntryClsfCde: '',
    pageNo: '0',
    relativeType: 'law'
  }, 5, requestHeaders, async () => {
    await initializeSession(recordId, true);
    requestHeaders.Cookie = sessionCookie;
  });
  if (result?.success === false || !result?.lawlist) throw new Error(`full text unavailable for ${record.secFutrsLawId}`);
  const law = result.lawlist.law ?? {};
  const sections = flattenEntries(result.lawlist.lawEntryVOs ?? []);
  const body = plainText([law.bodyAgoCntnt, law.body, law.bodyAftCntnt].filter(Boolean).join('\n'));
  return { body, sections, bodyStatus: body || sections.length ? 'full-text' : 'index-only' };
}

async function mapWithConcurrency(values, limit, mapper) {
  const results = new Array(values.length);
  let cursor = 0;
  async function worker() {
    while (cursor < values.length) {
      const index = cursor;
      cursor += 1;
      results[index] = await mapper(values[index]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, values.length) }, () => worker()));
  return results;
}

const categoryResults = [];
for (const category of categories) {
  const records = await fetchCategory(category);
  categoryResults.push({ category, records });
}

const sourceRecords = new Map();
for (const { category, records } of categoryResults) {
  for (const record of records) {
    const id = String(record.secFutrsLawId);
    const existing = sourceRecords.get(id);
    const categoryRef = { id: `csrc:${category.id}`, name: category.name, group: category.group };
    if (existing) {
      existing.categories.push(categoryRef);
    } else {
      sourceRecords.set(id, { raw: record, categories: [categoryRef] });
    }
  }
}

let previousRecords = new Map();
try {
  const previousPayload = JSON.parse(await readFile(jsonPath, 'utf8'));
  previousRecords = new Map((previousPayload.records ?? []).map((record) => [String(record.id), record]));
} catch {
  previousRecords = new Map();
}

let bodyCache = {};
try {
  const cachedPayload = JSON.parse(await readFile(bodyCachePath, 'utf8'));
  bodyCache = cachedPayload?.records && typeof cachedPayload.records === 'object'
    ? cachedPayload.records
    : {};
} catch {
  bodyCache = {};
}

let cacheWriteQueue = Promise.resolve();
let cacheUpdates = 0;
function checkpointBodyCache(force = false) {
  if (!force && cacheUpdates % 10 !== 0) return Promise.resolve();
  const snapshot = JSON.stringify({
    schemaVersion: 1,
    updatedAt: new Date().toISOString(),
    records: bodyCache
  });
  cacheWriteQueue = cacheWriteQueue.then(async () => {
    await mkdir(runtimeImportDir, { recursive: true });
    const temporary = `${bodyCachePath}.${process.pid}.tmp`;
    await writeFile(temporary, `${snapshot}\n`, 'utf8');
    await rename(temporary, bodyCachePath);
  });
  return cacheWriteQueue;
}

const fullTextFailures = [];
const recordsWithText = await mapWithConcurrency(
  [...sourceRecords.values()],
  includeFullText ? fullTextConcurrency : 16,
  async ({ raw, categories: categoryRefs }) => {
  const recordId = String(raw.secFutrsLawId);
  const previous = previousRecords.get(recordId);
  let fullText = { body: '', sections: [], bodyStatus: 'index-only' };
  if (includeFullText && previous?.bodyStatus === 'full-text' && (previous.body || previous.sections?.length)) {
    fullText = { body: previous.body ?? '', sections: previous.sections ?? [], bodyStatus: 'full-text' };
  } else if (includeFullText && bodyCache[recordId]?.bodyStatus === 'full-text') {
    fullText = bodyCache[recordId];
  } else if (includeFullText) {
    try {
      fullText = await fetchFullText(raw);
      bodyCache[recordId] = fullText;
      cacheUpdates += 1;
      await checkpointBodyCache();
      await sleep(120);
    } catch (error) {
      fullTextFailures.push({ id: recordId, error: error.message });
      fullText = { body: '', sections: [], bodyStatus: 'fetch-failed' };
    }
  }
  const status = statusMap[Number(raw.lawAthrtyStsCde)] ?? { id: 'official-list', label: '官方收录' };
  const title = plainText(raw.secFutrsLawName);
  return {
    id: String(raw.secFutrsLawId),
    title,
    summary: plainText(fullText.body || fullText.sections.map((section) => `${section.title} ${section.content}`).join('\n')).slice(0, 220),
    url: `https://neris.csrc.gov.cn/falvfagui/rdqsHeader/mainbody?navbarId=2&secFutrsLawId=${encodeURIComponent(raw.secFutrsLawId)}`,
    publishedAt: dateValue(raw.pubDate),
    effectiveAt: dateValue(raw.efctvDate),
    ineffectiveAt: dateValue(raw.inefctvDate),
    fileNumber: plainText(raw.fileno),
    source: plainText(raw.lawPubOrgName) || '中国证券监督管理委员会',
    sourceType: 'csrc',
    sourceStatus: status.id,
    statusLabel: status.label,
    categories: categoryRefs,
    bodyStatus: fullText.bodyStatus,
    body: fullText.body,
    sections: fullText.sections
  };
  },
);
if (includeFullText) await checkpointBodyCache(true);

const payload = {
  generatedAt: new Date().toISOString(),
  sourceUrl: sourceRoot,
  note: includeFullText
    ? `法规、规章及规范性文件来自中国证监会法规数据库。效力状态、正文和最新版本以证监会官方页面为准；本地全文仅用于浏览和检索准备，不替代官方文本。本次正文失败 ${fullTextFailures.length} 条。`
    : '法规、规章及规范性文件目录来自中国证监会法规数据库。效力状态、正文和最新版本以证监会官方页面为准；本次日常同步仅更新目录和官方原文入口。',
  categories: categoryResults.map(({ category, records }) => ({
    id: `csrc:${category.id}`,
    group: category.group,
    name: category.name,
    count: records.length,
    sourceType: 'csrc'
  })),
  records: recordsWithText.sort((left, right) => String(right.publishedAt || '').localeCompare(String(left.publishedAt || '')) || left.id.localeCompare(right.id))
};

await mkdir(dataDir, { recursive: true });
await writeFile(`${jsPath}.tmp`, `window.CSRC_RULES_DATA = ${JSON.stringify(payload, null, 2)};\n`, 'utf8');
await writeFile(`${jsonPath}.tmp`, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
await rename(`${jsPath}.tmp`, jsPath);
await rename(`${jsonPath}.tmp`, jsonPath);

console.log(`Wrote ${payload.records.length} CSRC rules to ${jsPath}`);
if (fullTextFailures.length) {
  console.error(`CSRC full-text fetch failed for ${fullTextFailures.length} records; successful bodies were checkpointed for retry.`);
  throw new Error(`CSRC full-text incomplete: ${fullTextFailures.length} records`);
}
