import { createRequire } from 'node:module';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const browser = await chromium.launch({ executablePath: edgePath, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const errors = [];

page.on('pageerror', (error) => errors.push(error.message));
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(message.text());
});

await page.goto('http://127.0.0.1:8767/index.html#tasks', { waitUntil: 'load' });
await page.locator('#open-task-dialog').click();
await page.locator('[name="taskName"]').fill('MVP 文档上传验收');
await page.locator('[name="taskType"]').selectOption({ label: '临时公告通用审查' });
await page.locator('[name="document"]').setInputFiles(path.resolve('测试文档_金额比例与表述风险.txt'));
await page.locator('#submit-task').click();
await page.locator('#view-review.is-active').waitFor({ timeout: 15000 });

const reviewFile = (await page.locator('#review-file-name').textContent()).trim();
const pendingRisks = (await page.locator('#pending-risk-count').textContent()).trim();
const highRisks = (await page.locator('#risk-high-count').textContent()).trim();
const reason = (await page.locator('#risk-reason').textContent()).trim();
const highlightedSources = await page.locator('#review-document-paper [data-risk-id]').count();
const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

if (reviewFile !== '测试文档_金额比例与表述风险.txt') throw new Error(`Unexpected review file: ${reviewFile}`);
if (pendingRisks !== '5') throw new Error(`Unexpected risk total: ${pendingRisks}`);
if (highRisks !== '高 1') throw new Error(`Unexpected high risk total: ${highRisks}`);
if (!reason.includes('35.00%')) throw new Error(`Numeric consistency result is missing: ${reason}`);
if (highlightedSources < 2) throw new Error(`Expected highlighted source text, found ${highlightedSources}`);
if (overflow > 1) throw new Error(`Upload review horizontal overflow: ${overflow}px`);
if (errors.length) throw new Error(`Browser errors: ${errors.join(' | ')}`);

await page.screenshot({ path: 'web/research/upload-review-desktop.png', fullPage: true });

console.log(JSON.stringify({
  reviewFile,
  pendingRisks: Number(pendingRisks),
  highRisks,
  highlightedSources,
  overflow,
  browserErrors: errors.length
}, null, 2));

await browser.close();
