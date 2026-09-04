import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const pageUrl = `${pathToFileURL(path.resolve('web/index.html')).href}#decision`;
const browser = await chromium.launch({ executablePath: edgePath, headless: true });

async function assertPage(page, label) {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  await page.goto(pageUrl, { waitUntil: 'load' });
  await page.waitForSelector('#result-title');
  if (errors.length) throw new Error(`${label} browser errors: ${errors.join(' | ')}`);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (overflow > 1) throw new Error(`${label} horizontal overflow: ${overflow}px`);
}

const desktop = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
await assertPage(desktop, 'desktop');
await desktop.locator('[data-view="data"]').click();
const expectedCompanyTotal = await desktop.evaluate(() => String(window.HEIMA_COMPANY_DATA.stats.total));
const expectedPeriodicTotal = await desktop.evaluate(() => String(window.HEIMA_COMPANY_DATA.stats.periodicTotal));
const expected2017Total = await desktop.evaluate(() => String(window.HEIMA_COMPANY_DATA.stats.yearlyCounts['2017']));
if ((await desktop.locator('#announcement-result-count').textContent()).replaceAll(',', '') !== expectedCompanyTotal) throw new Error('Announcement archive total is incorrect');
await desktop.locator('[data-announcement-scope="periodic"]').click();
if ((await desktop.locator('#announcement-result-count').textContent()).replaceAll(',', '') !== expectedPeriodicTotal) throw new Error('Periodic report total is incorrect');
await desktop.locator('#clear-announcement-filter').click();
await desktop.locator('#announcement-year-select').selectOption('2017');
if ((await desktop.locator('#announcement-result-count').textContent()).replaceAll(',', '') !== expected2017Total) throw new Error('2017 announcement total is incorrect');
await desktop.locator('#clear-announcement-filter').click();
await desktop.locator('#announcement-search').fill('年度报告');
if (Number((await desktop.locator('#announcement-result-count').textContent()).replaceAll(',', '')) < 10) throw new Error('Announcement search did not return annual reports');
await desktop.locator('#clear-announcement-filter').click();
if ((await desktop.locator('#peer-announcement-total').textContent()).trim() === '待同步') throw new Error('Peer announcement index did not load');
await desktop.locator('[data-announcement-source="peer"]').click();
if (await desktop.locator('#peer-company-switch[hidden]').count()) throw new Error('Peer company switch did not open');
if (await desktop.locator('[data-peer-code]').count() !== 2) throw new Error('Peer company selection is incomplete');
if (Number((await desktop.locator('#announcement-result-count').textContent()).replaceAll(',', '')) <= 0) throw new Error('First peer announcement archive is empty');
await desktop.locator('[data-peer-code="605098"]').click();
if (Number((await desktop.locator('#announcement-result-count').textContent()).replaceAll(',', '')) <= 0) throw new Error('Second peer announcement archive is empty');
await desktop.locator('[data-announcement-source="company"]').click();
await desktop.screenshot({ path: 'web/research/data-center-desktop.png', fullPage: true });

await desktop.locator('.nav-item[data-view="rules"]').click();
await desktop.locator('[data-rule-source="csrc"]').click();
if (Number((await desktop.locator('#rule-result-count').textContent()).replaceAll(',', '')) !== 579) throw new Error('CSRC rule index total is incorrect');
await desktop.locator('#rule-search').fill('上市公司监管指引第10号');
if (Number((await desktop.locator('#rule-result-count').textContent()).replaceAll(',', '')) < 1) throw new Error('CSRC rule search did not return the official rule');
if (!(await desktop.locator('#rule-detail').textContent()).includes('上市公司监管指引第10号')) throw new Error('CSRC rule detail did not render');
if (!(await desktop.locator('#rule-detail a').last().getAttribute('href')).includes('neris.csrc.gov.cn')) throw new Error('CSRC rule detail does not point to the official source');
await desktop.screenshot({ path: 'web/research/rules-csrc-desktop.png', fullPage: true });

await desktop.locator('[data-view="decision"]').click();
if (await desktop.locator('#base-main-revenue').count()) throw new Error('Main-business-revenue editor should not be visible');
if ((await desktop.locator('#transaction-amount').getAttribute('value')) !== '45000000') throw new Error('Decision inputs are not using yuan');
if (!(await desktop.locator('#result-title').textContent()).includes('需董事会审议')) throw new Error('Default equity example did not reach board review');
if (await desktop.locator('.calculation-state.hit').count() < 3) throw new Error('Default equity example did not hit three disclosure metrics');

await desktop.locator('[data-decision-type="contract"]').click();
await desktop.locator('#transaction-amount').fill('170000000');
await desktop.locator('#decision-form button[type="submit"]').click();
if (!(await desktop.locator('#result-title').textContent()).includes('达到日常经营重大合同披露标准')) throw new Error('Sales contract example did not trigger guideline article 7.3.1');
if (!(await desktop.locator('#result-summary').textContent()).includes('规范运作指引第 7.3.1 条第（二）项')) throw new Error('Contract result does not cite the correct guideline clause');
if (!(await desktop.locator('#result-source-link').getAttribute('href')).includes('szse-chinext-standard-operation-2026.pdf#page=98')) throw new Error('Contract result does not link to PDF page 98');
if ((await desktop.locator('#decision-evidence').textContent()).includes('8.7.5')) throw new Error('Obsolete listing-rule citation remains in contract evidence');
await desktop.locator('#contract-category').selectOption('purchase');
await desktop.locator('#decision-form button[type="submit"]').click();
if (!(await desktop.locator('#result-title').textContent()).includes('未触发量化披露线')) throw new Error('Purchase contract incorrectly used the main-revenue baseline');
if (await desktop.locator('#result-source-link').isHidden()) throw new Error('Untriggered purchase contract did not show its rule source');
if (!(await desktop.locator('#result-source-link').getAttribute('href')).includes('szse-chinext-standard-operation-2026.pdf#page=98')) throw new Error('Untriggered purchase contract does not link to PDF page 98');
if (!(await desktop.locator('#result-source-link-text').textContent()).includes('第 7.3.1 条第（一）项')) throw new Error('Purchase contract source does not cite article 7.3.1(1)');
await desktop.locator('#contract-category').selectOption('sales');
await desktop.locator('#transaction-amount').fill('90000000');
await desktop.locator('#decision-form button[type="submit"]').click();
const contractLowTitle = await desktop.locator('#result-title').textContent();
if (!contractLowTitle.includes('未触发量化披露线')) {
  const state = await desktop.evaluate(() => ({
    value: document.querySelector('#transaction-amount').value,
    valid: document.querySelector('#decision-form').checkValidity(),
    invalid: [...document.querySelector('#decision-form').elements].filter((element) => !element.checkValidity()).map((element) => ({ id: element.id, value: element.value, message: element.validationMessage }))
  }));
  throw new Error(`Sub-threshold contract result is incorrect: ${contractLowTitle} / ${JSON.stringify(state)}`);
}
if (await desktop.locator('#result-source-link').isHidden()) throw new Error('Untriggered sales contract did not show its rule source');
if (!(await desktop.locator('#result-source-link').getAttribute('href')).includes('szse-chinext-standard-operation-2026.pdf#page=98')) throw new Error('Untriggered sales contract does not link to PDF page 98');
if (!(await desktop.locator('#result-source-link-text').textContent()).includes('第 7.3.1 条第（二）项')) throw new Error('Sales contract source does not cite article 7.3.1(2)');
await desktop.locator('[data-result-font="large"]').click();
if ((await desktop.locator('.decision-result-panel').getAttribute('data-font-size')) !== 'large') throw new Error('Result font-size control did not apply');
if ((await desktop.locator('[data-result-font="large"]').getAttribute('aria-pressed')) !== 'true') throw new Error('Result font-size control state is incorrect');
await desktop.locator('[data-result-font="normal"]').click();

await desktop.locator('[data-decision-type="equity"]').click();
if (await desktop.locator('#result-source-link').isHidden()) throw new Error('Equity result did not show its rule source');
if (!(await desktop.locator('#result-source-link-text').textContent()).includes('第 7.1.2、7.1.3 条')) throw new Error('Equity result source does not cite articles 7.1.2 and 7.1.3');
await desktop.locator('#related-kind').selectOption('entity');
await desktop.locator('#decision-form button[type="submit"]').click();
if (!(await desktop.locator('#result-title').textContent()).includes('股东会审议标准')) throw new Error('Related equity overlay did not reach shareholder review');
await desktop.screenshot({ path: 'web/research/decision-desktop.png', fullPage: true });

await desktop.locator('[data-view="usage"]').click();
if ((await desktop.locator('#usage-analysis-total').textContent()).trim() !== '179') throw new Error('Default 7-day AI usage total is incorrect');
if (!(await desktop.locator('#usage-cost-total').textContent()).startsWith('¥')) throw new Error('AI cost estimate is missing');
if (await desktop.locator('.usage-chart-column').count() !== 7) throw new Error('Default AI usage chart range is incorrect');
await desktop.locator('[data-usage-range="14"]').click();
if (await desktop.locator('.usage-chart-column').count() !== 14) throw new Error('14-day AI usage range did not render');
const usageDesktopOverflow = await desktop.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
if (usageDesktopOverflow > 1) throw new Error(`desktop AI usage horizontal overflow: ${usageDesktopOverflow}px`);
await desktop.screenshot({ path: 'web/research/usage-desktop.png', fullPage: true });

const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
await assertPage(mobile, 'mobile');
await mobile.screenshot({ path: 'web/research/decision-mobile.png', fullPage: true });
await mobile.locator('[data-view="data"]').click();
const mobileDataOverflow = await mobile.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
if (mobileDataOverflow > 1) throw new Error(`mobile data center horizontal overflow: ${mobileDataOverflow}px`);
await mobile.screenshot({ path: 'web/research/data-center-mobile.png', fullPage: true });
await mobile.locator('[data-view="usage"]').click();
if ((await mobile.locator('#usage-analysis-total').textContent()).trim() !== '179') throw new Error('Mobile AI usage total is incorrect');
const mobileUsageOverflow = await mobile.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
if (mobileUsageOverflow > 1) throw new Error(`mobile AI usage horizontal overflow: ${mobileUsageOverflow}px`);
await mobile.screenshot({ path: 'web/research/usage-mobile.png', fullPage: true });

console.log(JSON.stringify({
  desktopTitle: await desktop.locator('#result-title').textContent(),
  mobileTitle: await mobile.locator('#result-title').textContent(),
  desktopOverflow: await desktop.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
  mobileOverflow: await mobile.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
}, null, 2));

await browser.close();
