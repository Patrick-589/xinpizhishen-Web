import http from 'node:http';
import { mkdir, rename, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const companies = [
  {
    secCode: '003032',
    orgId: 'gfbj0839976',
    column: 'szse',
    plate: 'sz',
    sourceUrl: 'https://www.cninfo.com.cn/new/disclosure/stock?stockCode=003032&orgId=gfbj0839976&sjstsBond=false#latestAnnouncement'
  },
  {
    secCode: '605098',
    orgId: 'gfbj0831891',
    column: 'sse',
    plate: 'sh',
    sourceUrl: 'https://www.cninfo.com.cn/new/disclosure/stock?stockCode=605098&orgId=gfbj0831891#latestAnnouncement'
  }
];

const pageSize = 30;
const startYear = 2017;

function sleep(milliseconds) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));
}

function postForm(path, fields) {
  const body = new URLSearchParams(fields).toString();
  return new Promise((resolvePromise, rejectPromise) => {
    const request = http.request({
      hostname: 'www.cninfo.com.cn',
      path,
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Content-Length': Buffer.byteLength(body),
        Referer: 'http://www.cninfo.com.cn/',
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0 (compatible; XinpizhishenMVP/1.0)'
      }
    }, (response) => {
      let raw = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { raw += chunk; });
      response.on('end', () => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          rejectPromise(new Error(`CNINFO returned ${response.statusCode}`));
          return;
        }
        try {
          resolvePromise(JSON.parse(raw));
        } catch (error) {
          rejectPromise(new Error(`Invalid CNINFO response: ${error.message}`));
        }
      });
    });
    request.setTimeout(25000, () => request.destroy(new Error('CNINFO request timed out')));
    request.on('error', rejectPromise);
    request.write(body);
    request.end();
  });
}

async function requestWithRetry(fields, attempts = 3) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await postForm('/new/hisAnnouncement/query', fields);
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await sleep(400 * attempt);
    }
  }
  throw lastError;
}

function decodeText(value = '') {
  return String(value)
    .replace(/<[^>]*>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim();
}

function dateInShanghai(timestamp) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(new Date(timestamp));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function classifyAnnouncement(title) {
  if (/(公司章程|管理制度|议事规则|工作制度|内部控制|治理专项)/.test(title)) return { id: 'governance', name: '治理与制度' };
  const patterns = [
    { id: 'periodic', name: '定期报告', pattern: /(年度报告|半年度报告|第一季度报告|第三季度报告|季度报告)(?!.*问询函)/ },
    { id: 'performance', name: '业绩与分红', pattern: /(业绩预告|业绩快报|利润分配|权益分派|分红|业绩说明会)/ },
    { id: 'meeting', name: '三会公告', pattern: /(董事会|监事会|股东大会|股东会|独立董事|审计委员会).*?(公告|决议|意见|会议|报告)|召开.*?(股东大会|股东会)/ },
    { id: 'transaction', name: '交易与投资', pattern: /(收购|出售|购买.*?股权|转让.*?股权|对外投资|关联交易|重大合同|资产重组|增资|减资|合伙企业|委托贷款|担保|综合授信|财务资助)/ },
    { id: 'capital', name: '资本运作', pattern: /(发行.*?股票|募集资金|股份回购|股权激励|员工持股|限售股|可转债|公司债|非公开发行|向特定对象发行)/ },
    { id: 'equity', name: '股东与股份', pattern: /(股东|股份|持股|减持|增持|质押|解除质押|实际控制人|控制权)/ },
    { id: 'regulatory', name: '监管与风险', pattern: /(问询函|关注函|监管函|纪律处分|行政处罚|立案|诉讼|仲裁|风险提示|回复公告|更正公告|补充公告)/ },
    { id: 'investor', name: '投资者关系', pattern: /(投资者关系|调研活动|接待.*?调研|互动易|投资者保护)/ }
  ];
  return patterns.find((category) => category.pattern.test(title)) ?? { id: 'other', name: '其他公告' };
}

function normalizeAnnouncement(item) {
  const title = decodeText(item.announcementTitle || item.shortTitle);
  const category = classifyAnnouncement(title);
  const publishedAt = dateInShanghai(item.announcementTime);
  return {
    id: String(item.announcementId),
    title,
    publishedAt,
    year: Number(publishedAt.slice(0, 4)),
    categoryId: category.id,
    categoryName: category.name,
    isPeriodic: category.id === 'periodic',
    pdfUrl: `https://static.cninfo.com.cn/${String(item.adjunctUrl || '').replace(/^\//, '')}`,
    fileType: item.adjunctType || 'PDF',
    sizeKB: Number(item.adjunctSize || 0),
    announcementTypes: String(item.announcementType || '').split('||').filter(Boolean),
    source: '巨潮资讯网'
  };
}

async function fetchYear(company, year, endDate) {
  const records = [];
  let expectedTotal = null;
  for (let page = 1; page <= 100; page += 1) {
    const result = await requestWithRetry({
      pageNum: String(page),
      pageSize: String(pageSize),
      column: company.column,
      tabName: 'fulltext',
      plate: company.plate,
      stock: `${company.secCode},${company.orgId}`,
      searchkey: '',
      secid: '',
      category: '',
      trade: '',
      seDate: `${year}-01-01~${endDate}`,
      sortName: '',
      sortType: '',
      isHLtitle: 'true'
    });
    if (expectedTotal == null) expectedTotal = Number(result.totalAnnouncement || result.totalRecordNum || 0);
    const pageRecords = result.announcements ?? [];
    records.push(...pageRecords);
    if (!pageRecords.length || records.length >= expectedTotal) break;
    await sleep(80);
  }
  const uniqueCount = new Set(records.map((record) => String(record.announcementId))).size;
  if (expectedTotal !== uniqueCount) throw new Error(`${company.secCode} ${year} expected ${expectedTotal} announcements, received ${uniqueCount}`);
  console.log(`${company.secCode} ${year}: ${uniqueCount} announcements`);
  return records;
}

async function fetchCompany(config, currentYear, currentDate) {
  const allRawRecords = [];
  for (let year = startYear; year <= currentYear; year += 1) {
    const endDate = year === currentYear ? currentDate : `${year}-12-31`;
    allRawRecords.push(...await fetchYear(config, year, endDate));
  }
  const announcementsById = new Map();
  for (const item of allRawRecords) announcementsById.set(String(item.announcementId), normalizeAnnouncement(item));
  const announcements = [...announcementsById.values()].sort((left, right) => right.publishedAt.localeCompare(left.publishedAt) || right.id.localeCompare(left.id));
  const firstRawRecord = allRawRecords[0] ?? {};
  const categoryOrder = ['periodic', 'performance', 'meeting', 'transaction', 'capital', 'equity', 'governance', 'regulatory', 'investor', 'other'];
  const categoryNames = {
    periodic: '定期报告', performance: '业绩与分红', meeting: '三会公告', transaction: '交易与投资', capital: '资本运作',
    equity: '股东与股份', governance: '治理与制度', regulatory: '监管与风险', investor: '投资者关系', other: '其他公告'
  };
  return {
    company: {
      secCode: config.secCode,
      secName: decodeText(firstRawRecord.secName || firstRawRecord.secname || '') || `证券代码 ${config.secCode}`,
      orgId: config.orgId,
      market: config.column === 'sse' ? '上海证券交易所' : '深圳证券交易所'
    },
    sourceUrl: config.sourceUrl,
    stats: {
      total: announcements.length,
      periodicTotal: announcements.filter((record) => record.isPeriodic).length,
      earliestAt: announcements.at(-1)?.publishedAt ?? null,
      latestAt: announcements[0]?.publishedAt ?? null,
      latestId: announcements[0]?.id ?? null,
      yearlyCounts: Object.fromEntries([...new Set(announcements.map((record) => record.year))].sort((a, b) => b - a).map((year) => [year, announcements.filter((record) => record.year === year).length]))
    },
    categories: categoryOrder.map((id) => ({ id, name: categoryNames[id], count: announcements.filter((record) => record.categoryId === id).length })),
    announcements
  };
}

const now = new Date();
const currentYear = Number(new Intl.DateTimeFormat('en', { timeZone: 'Asia/Shanghai', year: 'numeric' }).format(now));
const currentDate = dateInShanghai(now.getTime());
const companyResults = [];
for (const company of companies) companyResults.push(await fetchCompany(company, currentYear, currentDate));

const payload = {
  generatedAt: new Date().toISOString(),
  note: '对标公司公告索引来自巨潮资讯网公开披露页面，仅作公开信息对比参考，不作为创业黑马公司事实、审批标准或合规结论依据。公告正文、披露时间及效力以巨潮资讯网原始 PDF 为准。',
  companies: companyResults
};

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(scriptDir, '..');
const dataDir = resolve(webDir, 'data');
await mkdir(dataDir, { recursive: true });

const jsPath = resolve(webDir, 'peer-data.js');
const jsonPath = resolve(dataDir, 'peer-announcements.json');
await writeFile(`${jsPath}.tmp`, `window.CNINFO_PEER_DATA = ${JSON.stringify(payload, null, 2)};\n`, 'utf8');
await writeFile(`${jsonPath}.tmp`, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
await rename(`${jsPath}.tmp`, jsPath);
await rename(`${jsonPath}.tmp`, jsonPath);

console.log(`Wrote ${companyResults.map((item) => `${item.company.secCode}: ${item.stats.total}`).join(', ')} announcements to ${jsPath}`);
