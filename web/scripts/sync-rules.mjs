import http from 'node:http';
import { mkdir, rename, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const categories = [
  { id: 'law', group: '法律法规', name: '法律', channel: 'law_news', url: 'https://www.szse.cn/lawrules/rules/law/index.html' },
  { id: 'regulation', group: '法律法规', name: '行政法规', channel: 'adminregu_news', url: 'https://www.szse.cn/lawrules/rules/regu/index.html' },
  { id: 'judicial', group: '法律法规', name: '司法解释', channel: 'judicial_news', url: 'https://www.szse.cn/lawrules/rules/judicial/index.html' },
  { id: 'csrc-command', group: '证监会规章和规范性文件', name: '证监会令', channel: 'csrccommand', url: 'https://www.szse.cn/lawrules/csrcrules/command/index.html' },
  { id: 'csrc-notice', group: '证监会规章和规范性文件', name: '证监会公告', channel: 'csrcnotice', url: 'https://www.szse.cn/lawrules/csrcrules/notice/index.html' },
  { id: 'csrc-guide', group: '证监会规章和规范性文件', name: '监管规则适用指引', channel: 'csrcrulesGuide_news', url: 'https://www.szse.cn/lawrules/csrcrules/guide/index.html' },
  { id: 'latest', group: '本所业务规则', name: '最新规则', channel: 'szserulesAllRulesBuss', url: 'https://www.szse.cn/lawrules/rule/new/index.html' },
  { id: 'general', group: '本所业务规则', name: '综合类', channel: 'szserulesAlltype', url: 'https://www.szse.cn/lawrules/rule/all/index.html' },
  { id: 'stock', group: '本所业务规则', name: '股票类', channel: 'szserulesStock_news', url: 'https://www.szse.cn/lawrules/rule/stock/audit/index.html' },
  { id: 'bond', group: '本所业务规则', name: '固收类', channel: 'szserulesBond_news', url: 'https://www.szse.cn/lawrules/rule/bond/bonds/list/index.html' },
  { id: 'fund', group: '本所业务规则', name: '基金类', channel: 'szserulesFund_news', url: 'https://www.szse.cn/lawrules/rule/fund/list/index.html' },
  { id: 'reits', group: '本所业务规则', name: 'REITs类', channel: 'szserulesReits_news', url: 'https://www.szse.cn/lawrules/rule/reits/index.html' },
  { id: 'derivative', group: '本所业务规则', name: '衍生品类', channel: 'szserulesDerivative_news', url: 'https://www.szse.cn/lawrules/rule/derivative/index.html' },
  { id: 'trade', group: '本所业务规则', name: '交易类', channel: 'szserulesTrade_news', url: 'https://www.szse.cn/lawrules/rule/trade/current/index.html' },
  { id: 'member', group: '本所业务规则', name: '会员管理类', channel: 'szserulesMember_news', url: 'https://www.szse.cn/lawrules/rule/memberty/index.html' },
  { id: 'innovation', group: '本所业务规则', name: '跨境创新类', channel: 'szserulesInnovation_news', url: 'https://www.szse.cn/lawrules/rule/inno/szhk/index.html' },
  { id: 'discipline', group: '本所业务规则', name: '纪律处分与内部救济类', channel: 'szserulesPunishmentRelief_news', url: 'https://www.szse.cn/lawrules/rule/pr/index.html' },
  { id: 'all-business', group: '本所业务规则', name: '全部规则', channel: 'szserulesAllRulesBuss', url: 'https://www.szse.cn/lawrules/rule/allrules/bussiness/index.html' },
  { id: 'rule-compilation', group: '本所业务规则', name: '规则汇编下载', channel: 'szserulesAllRulesDownload', url: 'https://www.szse.cn/lawrules/rule/allrules/rulejoin/index.html' },
  { id: 'repealed', group: '本所业务规则', name: '规则废止公告', channel: 'szserules_gzfzgg', url: 'https://www.szse.cn/lawrules/rule/repeal/announcement/index.html' },
  { id: 'repealed-text', group: '本所业务规则', name: '已废止规则文本', channel: 'szserules_yfzgzwb', url: 'https://www.szse.cn/lawrules/rule/repeal/rules/index.html' },
  { id: 'guide-stock', group: '本所业务指南', name: '股票类', channel: 'shareType_news', url: 'https://www.szse.cn/lawrules/service/share/index.html' },
  { id: 'guide-bond', group: '本所业务指南', name: '固收类', channel: 'bondType_news', url: 'https://www.szse.cn/lawrules/service/bond/index.html' },
  { id: 'guide-fund', group: '本所业务指南', name: '基金类', channel: 'fundType_news', url: 'https://www.szse.cn/lawrules/service/fund/index.html' },
  { id: 'guide-reits', group: '本所业务指南', name: 'REITs类', channel: 'szseserviceReits_news', url: 'https://www.szse.cn/lawrules/service/reits/index.html' },
  { id: 'guide-derivative', group: '本所业务指南', name: '衍生品类', channel: 'szseserviceDerivative_news', url: 'https://www.szse.cn/lawrules/service/derivative/index.html' },
  { id: 'guide-member-trade', group: '本所业务指南', name: '会员与交易类', channel: 'memberTradeType_news', url: 'https://www.szse.cn/lawrules/service/member/index.html' },
  { id: 'guide-cross-border', group: '本所业务指南', name: '跨境创新类', channel: 'crossBorderInnovation_news', url: 'https://www.szse.cn/lawrules/service/cross/index.html' },
  { id: 'guide-other', group: '本所业务指南', name: '其他类', channel: 'otherType_news', url: 'https://www.szse.cn/lawrules/service/oth/index.html' },
  { id: 'public-advice', group: '公开征求意见', name: '公开征求意见', channel: 'publicadvice', url: 'https://www.szse.cn/lawrules/publicadvice/index.html' }
];

const pageSize = 50;

function postForm(path, fields) {
  const body = new URLSearchParams(fields).toString();
  return new Promise((resolvePromise, rejectPromise) => {
    const request = http.request({
      hostname: 'www.szse.cn',
      path,
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Content-Length': Buffer.byteLength(body),
        Referer: 'http://www.szse.cn/lawrules/rule/new/index.html',
        'User-Agent': 'Mozilla/5.0 (compatible; XinpizhishenMVP/1.0)'
      }
    }, (response) => {
      let raw = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { raw += chunk; });
      response.on('end', () => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          rejectPromise(new Error(`SZSE returned ${response.statusCode}`));
          return;
        }
        try {
          resolvePromise(JSON.parse(raw));
        } catch (error) {
          rejectPromise(new Error(`Invalid SZSE response: ${error.message}`));
        }
      });
    });
    request.setTimeout(20000, () => request.destroy(new Error('SZSE request timed out')));
    request.on('error', rejectPromise);
    request.write(body);
    request.end();
  });
}

function plainText(value = '') {
  return value.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
}

function normalizeUrl(value = '') {
  if (!value) return '';
  return value.replace(/^http:\/\/www\.szse\.cn/i, 'https://www.szse.cn');
}

function reviewScopes(item) {
  const text = `${plainText(item.doctitle)} ${plainText(item.doccontent)} ${plainText(item.navigation)}`;
  const scopes = new Set();
  const periodicReportPatterns = [
    /创业板股票上市规则（2026年修订）/,
    /创业板上市公司规范运作（2026年修订）/,
    /创业板上市公司自律监管指南第1号——业务办理（2026年修订）/,
    /创业板上市公司自律监管指南第2号——公告格式（2026年7月修订）/,
    /信息披露内容与格式准则第2号——年度报告的内容与格式/,
    /信息披露内容与格式准则第3号——半年度报告的内容与格式/,
    /信息披露编报规则第15号——财务报告的一般规定（2023年修订）/,
    /信息披露编报规则第13号——季度报告的内容与格式（2016年修订）/
  ];
  const financialAccountingPatterns = [
    /监管规则适用指引——会计类第[一二三四1-4]号/,
    /信息披露编报规则第15号——财务报告的一般规定/,
    /企业财务会计报告条例/
  ];
  if (periodicReportPatterns.some((pattern) => pattern.test(text))) scopes.add('periodic-report');
  if (financialAccountingPatterns.some((pattern) => pattern.test(text))) {
    scopes.add('financial-accounting');
    scopes.add('periodic-report');
  }
  return [...scopes];
}

function issuingAuthority(category) {
  if (category.id.startsWith('csrc-')) return '中国证券监督管理委员会';
  if (category.group === '本所业务规则' || category.group === '本所业务指南' || category.group === '公开征求意见') {
    return '深圳证券交易所';
  }
  return '';
}

async function loadCategory(category) {
  const fetchPage = (currentPage) => postForm('/api/search/content', {
    keyword: '',
    time: '0',
    range: 'title',
    channelCode: category.channel,
    currentPage: String(currentPage),
    pageSize: String(pageSize)
  });
  const first = await fetchPage(1);
  const reportedCount = Number(first.totalSize ?? first.data?.length ?? 0);
  const totalPages = Math.max(1, Math.ceil(reportedCount / pageSize));
  const items = [...(first.data ?? [])];
  for (let currentPage = 2; currentPage <= totalPages; currentPage += 1) {
    const page = await fetchPage(currentPage);
    items.push(...(page.data ?? []));
  }
  const uniqueItems = [...new Map(items.map((item) => [String(item.id), item])).values()];
  if (uniqueItems.length !== reportedCount) {
    throw new Error(`${category.name} expected ${reportedCount} records but loaded ${uniqueItems.length}`);
  }
  return { items: uniqueItems, reportedCount, totalPages };
}

const recordsById = new Map();
const categoryResults = [];

for (const category of categories) {
  try {
    const result = await loadCategory(category);
    categoryResults.push({
      ...category,
      count: result.reportedCount,
      indexedCount: result.items.length,
      pages: result.totalPages,
      loaded: true
    });
    for (const item of result.items) {
      const id = String(item.id);
      const existing = recordsById.get(id);
      const categoryRef = { id: category.id, name: category.name, group: category.group };
      if (existing) {
        if (!existing.categories.some((entry) => entry.id === category.id)) existing.categories.push(categoryRef);
        if (!existing.issuingAuthority) existing.issuingAuthority = issuingAuthority(category);
        for (const scope of reviewScopes(item)) {
          if (!existing.reviewScopes.includes(scope)) existing.reviewScopes.push(scope);
        }
        continue;
      }
      recordsById.set(id, {
        id,
        title: plainText(item.doctitle),
        summary: plainText(item.doccontent).slice(0, 220),
        url: normalizeUrl(item.docpuburl),
        publishedAt: new Date(item.docpubtime).toISOString().slice(0, 10),
        navigation: plainText(item.navigation),
        doctype: item.doctype,
        categories: [categoryRef],
        reviewScopes: reviewScopes(item),
        issuingAuthority: issuingAuthority(category),
        source: '深圳证券交易所',
        sourceStatus: category.id === 'repealed' || category.id === 'repealed-text' ? 'repealed-list' : 'official-list'
      });
    }
  } catch (error) {
    categoryResults.push({ ...category, count: null, loaded: false, error: error.message });
  }
}

const payload = {
  generatedAt: new Date().toISOString(),
  sourceUrl: 'https://www.szse.cn/lawrules/rule/new/index.html',
  note: '本地索引来自深交所公开规则页面。规则效力、正文和最新版本以官方页面为准。',
  categories: categoryResults,
  records: [...recordsById.values()].sort((a, b) => b.publishedAt.localeCompare(a.publishedAt))
};

const failedCategories = categoryResults.filter((category) => !category.loaded);
if (failedCategories.length) {
  throw new Error(`SZSE sync failed for: ${failedCategories.map((category) => `${category.name} (${category.error})`).join(', ')}`);
}

const incompleteCategories = categoryResults.filter((category) => category.indexedCount !== category.count);
if (incompleteCategories.length) {
  throw new Error(`SZSE completeness check failed for: ${incompleteCategories.map((category) => category.name).join(', ')}`);
}

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(scriptDir, '..');
const dataDir = resolve(webDir, 'data');
const outputPath = resolve(webDir, 'rules-data.js');
const jsonPath = resolve(dataDir, 'szse-rules.json');
await mkdir(dataDir, { recursive: true });
await writeFile(`${outputPath}.tmp`, `window.SZSE_RULES_DATA = ${JSON.stringify(payload, null, 2)};\n`, 'utf8');
await writeFile(`${jsonPath}.tmp`, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
await rename(`${outputPath}.tmp`, outputPath);
await rename(`${jsonPath}.tmp`, jsonPath);
console.log(`Wrote ${payload.records.length} indexed rules across ${payload.categories.length} categories to ${outputPath}`);
