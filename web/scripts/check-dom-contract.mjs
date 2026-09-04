import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';


const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(scriptDirectory, '..');
const [javascript, html] = await Promise.all([
  readFile(path.join(webRoot, 'app.js'), 'utf8'),
  readFile(path.join(webRoot, 'index.html'), 'utf8')
]);

const selectors = [...javascript.matchAll(/querySelector\(['"]#([A-Za-z0-9_-]+)/g)].map((match) => match[1]);
const ids = new Set([...html.matchAll(/\bid=["']([^"']+)["']/g)].map((match) => match[1]));
const dynamicallyCreatedOrShadowed = new Set([
  'toggle-saved-rule',
  'compare-rule-versions',
  'periodic-total',
  'rule-pack-count',
  'financial-open-source'
]);
const missing = [...new Set(selectors)].filter((id) => !ids.has(id) && !dynamicallyCreatedOrShadowed.has(id));

if (missing.length) {
  console.error(`DOM 契约检查失败，缺少元素：${missing.join(', ')}`);
  process.exitCode = 1;
} else {
  console.log(`DOM 契约检查通过：${new Set(selectors).size} 个 ID 选择器均存在。`);
}

const checkboxFunctionStart = javascript.indexOf('function restoreLegacyDocxCheckboxes(html)');
const checkboxFunctionEnd = javascript.indexOf('\n  function renderDocumentTable', checkboxFunctionStart);
if (checkboxFunctionStart < 0 || checkboxFunctionEnd < 0) {
  console.error('复选框显示检查失败：未找到 restoreLegacyDocxCheckboxes。');
  process.exitCode = 1;
} else {
  const checkboxFunctionSource = javascript.slice(checkboxFunctionStart, checkboxFunctionEnd);
  const restoreLegacyDocxCheckboxes = Function(
    `${checkboxFunctionSource}; return restoreLegacyDocxCheckboxes;`
  )();
  const explicitEmptyPairs = [
    '□适用 □不适用',
    '□是 □否',
    '<button class="inline-risk">□适用 □不适用</button>',
    '□<button class="inline-risk">适用 □不适用</button>'
  ];
  const changedEmptyPair = explicitEmptyPairs.find(
    (value) => restoreLegacyDocxCheckboxes(value) !== value
  );
  if (changedEmptyPair) {
    console.error(`复选框显示检查失败：空白选项被错误改写：${changedEmptyPair}`);
    process.exitCode = 1;
  } else {
    console.log('复选框显示检查通过：两个原始空框保持不变。');
  }
}
