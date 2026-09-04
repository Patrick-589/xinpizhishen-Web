(() => {
  const data = window.SZSE_RULES_DATA || { categories: [], records: [], note: '', generatedAt: null };
  const companyData = window.HEIMA_COMPANY_DATA || { categories: [], announcements: [], stats: {}, company: {}, note: '', generatedAt: null };
  const peerData = window.CNINFO_PEER_DATA || { companies: [], note: '', generatedAt: null };
  const csrcData = window.CSRC_RULES_DATA || { categories: [], records: [], note: '', generatedAt: null };
  const mofData = window.MOF_RULES_DATA || { categories: [], records: [], note: '', generatedAt: null };
  const rules = [
    ...(data.records ?? []).map((rule) => ({ ...rule, categories: (rule.categories ?? []).map((category) => ({ ...category, id: `szse:${category.id}` })), uid: `szse:${rule.id}`, sourceType: 'szse' })),
    ...(csrcData.records ?? []).map((rule) => ({ ...rule, uid: `csrc:${rule.id}`, sourceType: 'csrc' })),
    ...(mofData.records ?? []).map((rule) => ({
      ...rule,
      categories: (rule.categories ?? [{ id: rule.categoryId, name: rule.categoryName, group: '财政部会计司' }]).map((category) => ({ ...category, id: category.id?.startsWith('mof:') ? category.id : `mof:${category.id}` })),
      uid: `mof:${rule.id}`,
      sourceType: 'mof'
    }))
  ];
  const ruleCategories = [
    ...(data.categories ?? []).map((category) => ({ ...category, id: `szse:${category.id}`, sourceType: 'szse' })),
    ...(csrcData.categories ?? []).map((category) => ({ ...category, sourceType: 'csrc' })),
    ...(mofData.categories ?? []).map((category) => ({ ...category, sourceType: 'mof', id: category.id?.startsWith('mof:') ? category.id : `mof:${category.id}` }))
  ];
  const storageKeys = {
    savedRules: 'xinpizhishen.savedRules',
    tasks: 'xinpizhishen.tasks',
    latestAnalysis: 'xinpizhishen.latestAnalysis',
    activeUser: 'xinpizhishen.activeUser',
    decisionFontSize: 'xinpizhishen.decisionFontSize'
  };

  const platformState = {
    connected: false,
    authenticated: false,
    user: null,
    permissions: [],
    health: null,
    tasks: [],
    knowledge: [],
    knowledgeCategories: [],
    conversations: [],
    users: [],
    drafts: [],
    activeConversationId: null,
    knowledgeType: 'all',
    knowledgeCategoryId: null,
    workspaceConversations: [],
    workspaceConversationId: null
  };

  const pageMeta = {
    decision: ['证券资本市场', '事项合规适用性与义务判断'],
    drafting: ['本地 RAG 工作台', '文书起草'],
    chat: ['本地 RAG 工作台', 'AI 对话'],
    data: ['数据同步', '公告与规则更新'],
    rules: ['资料与规则库', '官方规则与已入库资料'],
    tasks: ['证券合规', '材料审查与风险评估'],
    review: ['合规审阅', '原文溯源、风险防控与人工复核'],
    usage: ['个人统计', '我的 AI 用量'],
    accounts: ['管理员', '注册账号与状态'],
    'financial-audit': ['财务审计', '财务数据与表格勾稽'],
    audit: ['治理与追溯', '审计记录'],
    reports: ['审查归档', '审查报告']
  };

  const defaultTasks = [
    { id: 'XS-2026-008', name: '关于对外投资暨关联交易的公告', file: '关联交易公告_v3.docx', type: '关联交易专项审查', status: 'review', risks: 6, owner: '李明', updatedAt: '2026-08-18 10:24' },
    { id: 'XS-2026-007', name: '2026 年半年度业绩预告', file: '业绩预告_复核稿.pdf', type: '临时公告通用审查', status: 'processing', risks: 2, owner: '王雪', updatedAt: '2026-08-18 09:16' },
    { id: 'XS-2026-006', name: '第五届董事会第十二次会议决议公告', file: '董事会决议公告_终稿.docx', type: '重大事项披露审查', status: 'completed', risks: 4, owner: '李明', updatedAt: '2026-08-17 17:42' }
  ];

  let usageRecords = [
    { date: '2026-08-01', analyses: 9, inputTokens: 71000, outputTokens: 18000 },
    { date: '2026-08-02', analyses: 7, inputTokens: 54000, outputTokens: 13000 },
    { date: '2026-08-03', analyses: 5, inputTokens: 42000, outputTokens: 10000 },
    { date: '2026-08-04', analyses: 16, inputTokens: 118000, outputTokens: 29500 },
    { date: '2026-08-05', analyses: 18, inputTokens: 132000, outputTokens: 33800 },
    { date: '2026-08-06', analyses: 21, inputTokens: 148000, outputTokens: 37600 },
    { date: '2026-08-07', analyses: 19, inputTokens: 141000, outputTokens: 34900 },
    { date: '2026-08-08', analyses: 13, inputTokens: 97000, outputTokens: 24100 },
    { date: '2026-08-09', analyses: 8, inputTokens: 63000, outputTokens: 15400 },
    { date: '2026-08-10', analyses: 6, inputTokens: 47000, outputTokens: 11800 },
    { date: '2026-08-11', analyses: 24, inputTokens: 176000, outputTokens: 44100 },
    { date: '2026-08-12', analyses: 28, inputTokens: 205000, outputTokens: 51200 },
    { date: '2026-08-13', analyses: 31, inputTokens: 228000, outputTokens: 56900 },
    { date: '2026-08-14', analyses: 27, inputTokens: 197000, outputTokens: 48900 },
    { date: '2026-08-15', analyses: 30, inputTokens: 219000, outputTokens: 54800 },
    { date: '2026-08-16', analyses: 15, inputTokens: 111000, outputTokens: 27500 },
    { date: '2026-08-17', analyses: 22, inputTokens: 161000, outputTokens: 40200 },
    { date: '2026-08-18', analyses: 26, inputTokens: 192000, outputTokens: 47800 }
  ];

  let usageRates = { input: 4, output: 12 };

  const defaultRisks = {
    'risk-amount': {
      title: '金额与比例不一致',
      reason: '3,500 万元占 10,000 万元的 35%，与原文披露的 30% 不一致。该问题来自确定性算术校验。',
      evidenceTitle: '《上市公司信息披露管理办法》（证监会令第226号）',
      evidenceUrl: 'https://www.szse.cn/lawrules/csrcrules/command/P020250519335703471735.pdf',
      evidenceNote: '相关规则要求信息披露真实、准确、完整；具体适用条款须由复核人员确认。',
      suggestion: '核对出资金额或认缴比例，并同步检查董事会决议、投资协议及公告中所有相关数字。'
    },
    'risk-wording': {
      title: '确定性表述风险',
      reason: '“确保实现持续稳定增长”属于缺少充分依据的确定性预测，可能使投资者对未来经营结果产生误解。',
      evidenceTitle: '《上市公司信息披露管理办法》（证监会令第226号）',
      evidenceUrl: 'https://www.szse.cn/lawrules/csrcrules/command/P020250519335703471735.pdf',
      evidenceNote: '依据匹配由规则库提供，具体条款和适用性待人工复核。',
      suggestion: '建议改为“有助于完善产业布局，实际影响受市场环境、基金运作等因素影响”。'
    },
    'risk-related': {
      title: '关联方信息待补充',
      reason: '当前文档未完整披露关联关系的形成时间、控制链条及交易对方最近一年主要财务数据。',
      evidenceTitle: '《深圳证券交易所创业板股票上市规则（2026年修订）》',
      evidenceUrl: 'https://www.szse.cn/lawrules/rule/stock/supervision/chinext/t20260424_620189.html',
      evidenceNote: '该事项需结合关联交易具体章节和公告格式要求进一步确认。',
      suggestion: '补充关联关系说明、控制链条、形成时间和交易对方主要财务指标，并注明数据是否经审计。'
    }
  };

  let risks = structuredClone(defaultRisks);
  const demoReviewMarkup = document.querySelector('#view-review').innerHTML;
  let latestAnalysisState = readSessionJson(storageKeys.latestAnalysis, null);
  let currentReviewTaskId = 'XS-2026-008';
  let currentReviewDocument = null;
  let financialAuditState = null;
  let financialAuditTaskId = '';
  let financialAuditStatus = 'all';
  let financialAuditCategory = 'all';
  let selectedFinancialCheckId = '';

  let selectedCategory = 'all';
  let selectedRuleId = null;
  let selectedRiskId = 'risk-amount';
  let taskFilter = 'all';
  const selectedTaskIds = new Set();
  let rulePage = 1;
  let announcementPage = 1;
  let announcementCategory = 'all';
  let announcementYear = 'all';
  let announcementScope = 'all';
  let announcementSource = 'company';
  let selectedPeerCode = peerData.companies?.[0]?.company?.secCode ?? null;
  let selectedRuleSource = 'all';
  let selectedRulePreset = 'all';
  let libraryPanel = 'rules';
  let knowledgeSearch = '';
  let usageRange = '7';
  let documentZoom = 1;
  let reviewReaderMode = 'annotated';
  let originalDocumentUrl = '';
  let originalDocumentFilename = '';
  let originalDocumentPage = null;
  let originalDocumentPreview = null;
  let currentRuleComparisonPayload = null;
  let toastTimer = null;
  const rulePageSize = 20;
  const announcementPageSize = 25;
  const resolvedRisks = new Set();
  const savedRules = new Set();

  function readJson(key, fallback) {
    try {
      const value = localStorage.getItem(key);
      return value ? JSON.parse(value) : fallback;
    } catch {
      return fallback;
    }
  }

  function writeJson(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Local storage may be disabled. */ }
  }

  function readSessionJson(key, fallback) {
    try {
      const value = sessionStorage.getItem(key);
      return value ? JSON.parse(value) : fallback;
    } catch {
      return fallback;
    }
  }

  function writeSessionJson(key, value) {
    try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* Large extracted documents may exceed browser storage. */ }
  }

  function userStorageKey(key) {
    return platformState.user?.id ? `${key}.${platformState.user.id}` : key;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, (character) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    })[character]);
  }

  function safeUrl(value) {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && url.hostname.endsWith('szse.cn') ? url.href : '#';
    } catch {
      return '#';
    }
  }

  function safeOfficialUrl(value) {
    try {
      const url = new URL(value);
      const allowed = ['szse.cn', 'cninfo.com.cn', 'csrc.gov.cn', 'mof.gov.cn'].some((domain) => url.hostname === domain || url.hostname.endsWith(`.${domain}`));
      return url.protocol === 'https:' && allowed ? url.href : '#';
    } catch {
      return '#';
    }
  }

  function safeCitationUrl(value) {
    const officialUrl = safeOfficialUrl(value);
    if (officialUrl !== '#') return officialUrl;
    try {
      const url = new URL(value, window.location.origin);
      const isKnowledgeDocument = /^\/api\/knowledge\/[^/]+\/document$/.test(url.pathname);
      const isDraftReference = /^\/api\/drafts\/[^/]+\/reference-document$/.test(url.pathname);
      return url.origin === window.location.origin && (isKnowledgeDocument || isDraftReference) && !url.search && !url.hash
        ? url.pathname
        : '#';
    } catch {
      return '#';
    }
  }

  function refreshIcons() {
    if (window.lucide?.createIcons) window.lucide.createIcons({ attrs: { 'stroke-width': 1.8 } });
  }

  function showToast(message) {
    const toast = document.querySelector('#toast');
    document.querySelector('#toast-message').textContent = message;
    toast.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('is-visible'), 2400);
  }

  async function apiFetch(path, options = {}) {
    let response;
    try {
      response = await fetch(path, { credentials: 'same-origin', ...options });
    } catch (error) {
      if (error instanceof TypeError) {
        throw new Error('无法连接本地审查服务，请重新运行 Windows 启动器后刷新页面。');
      }
      throw error;
    }
    const payload = response.status === 204 ? {} : await response.json().catch(() => ({}));
    if (response.status === 401) showAuthGate();
    if (!response.ok) throw new Error(payload.error || payload.message || `请求失败（${response.status}）`);
    return payload;
  }

  function roleLabel(role) {
    return ({ admin: '管理员', securities: '证券部', legal: '法务', leader: '领导', user: '个人账号' })[role] || role || '未知角色';
  }

  function resetPrivateClientState() {
    latestAnalysisState = null;
    currentReviewTaskId = null;
    currentReviewDocument = null;
    platformState.tasks = [];
    platformState.knowledge = [];
    platformState.knowledgeCategories = [];
    platformState.conversations = [];
    platformState.users = [];
    platformState.drafts = [];
    platformState.activeConversationId = null;
    platformState.workspaceConversations = [];
    platformState.workspaceConversationId = null;
    savedRules.clear();
    sessionStorage.removeItem(storageKeys.latestAnalysis);
  }

  function setAuthMode(mode) {
    const target = mode === 'register' && platformState.health?.registrationEnabled !== false ? 'register' : 'login';
    document.querySelectorAll('[data-auth-mode]').forEach((button) => {
      const active = button.dataset.authMode === target;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', String(active));
    });
    document.querySelectorAll('[data-auth-form]').forEach((form) => { form.hidden = form.dataset.authForm !== target; });
    const error = document.querySelector('#auth-error');
    error.hidden = true;
    const form = document.querySelector(`[data-auth-form="${target}"]`);
    form?.querySelector('input')?.focus();
  }

  function showAuthGate(message = '') {
    platformState.authenticated = false;
    document.querySelector('#app-shell').hidden = true;
    document.querySelector('#auth-gate').hidden = false;
    const error = document.querySelector('#auth-error');
    error.textContent = message;
    error.hidden = !message;
    const activeForm = document.querySelector('[data-auth-form]:not([hidden])');
    activeForm?.querySelector('input')?.focus();
    refreshIcons();
  }

  function showApplication() {
    platformState.authenticated = true;
    document.querySelector('#auth-gate').hidden = true;
    document.querySelector('#app-shell').hidden = false;
    const user = platformState.user || {};
    const previousUser = sessionStorage.getItem(storageKeys.activeUser);
    if (previousUser && previousUser !== user.id) resetPrivateClientState();
    sessionStorage.setItem(storageKeys.activeUser, user.id || '');
    savedRules.clear();
    readJson(userStorageKey(storageKeys.savedRules), []).forEach((ruleId) => savedRules.add(ruleId));
    document.querySelector('#current-user-name').textContent = user.display_name || user.username || '当前用户';
    document.querySelector('#current-user-role').textContent = user.username === '123' ? '测试账号' : roleLabel(user.role);
    document.querySelector('#current-user-avatar').textContent = (user.display_name || user.username || '用').slice(0, 1);
    const canAudit = platformState.permissions.includes('audit');
    const canKnowledge = platformState.permissions.includes('knowledge');
    const canUsers = platformState.permissions.includes('users');
    const canAnalyze = platformState.permissions.includes('analyze');
    const usageNav = document.querySelector('[data-view="usage"]');
    if (usageNav) usageNav.hidden = !canAudit;
    document.body.classList.toggle('is-admin', user.role === 'admin');
    document.querySelectorAll('[data-admin-only]').forEach((item) => { item.hidden = !canKnowledge; });
    document.querySelectorAll('[data-users-only]').forEach((item) => { item.hidden = !canUsers; });
    document.querySelectorAll('[data-analyze-only]').forEach((item) => { item.hidden = !canAnalyze; });
    document.querySelector('#open-knowledge-dialog').hidden = !canKnowledge;
    document.querySelector('#open-drafting-material-dialog').hidden = !canKnowledge;
    document.querySelector('#knowledge-dialog').dataset.allowed = String(canKnowledge);
    showLibraryPanel(libraryPanel, false);
    renderEmptyReview();
    usageRecords = [];
    renderUsage();
    updateRulePackCount();
    refreshIcons();
  }

  function updatePlatformStatus() {
    const health = platformState.health || {};
    const chip = document.querySelector('#ai-mode-chip');
    const mode = health.aiMode || 'local_rag';
    const modeLabel = mode === 'cloud' ? '阿里云 AI 增强' : (mode === 'local_llm' ? '完全本地 AI' : '本地 RAG');
    chip.innerHTML = `<i data-lucide="${mode === 'local_rag' ? 'database' : 'sparkles'}" aria-hidden="true"></i><span>${modeLabel}</span>`;
    document.querySelector('#assistant-mode-note').textContent = mode === 'local_rag'
      ? '本地检索仅返回原文与来源，不进行 AI 推理'
      : (mode === 'local_llm' ? 'Embedding、检索和推理均在本机完成' : '所有回答均先在本机检索当前任务与知识库');
    const dimension = Number(health.embeddingDimension || 0);
    document.querySelector('#knowledge-embedding-model').textContent = `${health.embeddingProvider || '等待 Embedding'}${dimension ? ` · ${dimension} 维` : ''} · ${health.vectorStore || '向量库待连接'}`;
    document.querySelector('#knowledge-embedded-count').textContent = `已 Embedding ${Number(health.embeddingDocuments || 0)}`;
    document.querySelector('#knowledge-pending-count').textContent = `待处理 ${Number(health.embeddingPendingDocuments || 0)}`;
    document.querySelector('#knowledge-failed-count').textContent = `失败 ${Number(health.embeddingFailedDocuments || 0)}`;
    const sharedStatus = document.querySelector('#library-shared-status span');
    if (sharedStatus) {
      const docs = Number(health.knowledgeDocuments || 0).toLocaleString('zh-CN');
      const chunks = Number(health.indexedChunks || 0).toLocaleString('zh-CN');
      sharedStatus.textContent = `${health.embeddingProvider || '本地 Embedding'} · ${dimension || '未知'} 维 · ${health.vectorStore || '向量库'}；共享底库 ${docs} 份文档 / ${chunks} 个已向量化 Chunk`;
    }
    const registerTab = document.querySelector('[data-auth-mode="register"]');
    if (registerTab) registerTab.hidden = health.registrationEnabled === false;
    const uploadStatus = document.querySelector('#upload-file-status');
    if (uploadStatus && health.ocrAvailable) uploadStatus.textContent = '最大 20MB，扫描 PDF 自动使用 Windows 本地 OCR';
    refreshIcons();
  }

  async function loadPlatformData() {
    const jobs = [loadServerTasks()];
    if (platformState.permissions.includes('knowledge')) jobs.push(loadKnowledge());
    if (platformState.permissions.includes('audit')) jobs.push(loadUsage());
    if (platformState.permissions.includes('users')) jobs.push(loadUsers());
    if (platformState.permissions.includes('analyze')) jobs.push(loadDrafts());
    await Promise.allSettled(jobs);
  }

  async function establishSession() {
    const session = await apiFetch('/api/auth/me');
    platformState.user = session.user;
    platformState.permissions = session.permissions || [];
    showApplication();
    await loadPlatformData();
    const requestedView = location.hash.replace('#', '');
    showView(requestedView === 'knowledge' ? 'knowledge' : (pageMeta[requestedView] ? requestedView : 'tasks'), false);
  }

  function initAuthentication() {
    const shell = document.querySelector('#app-shell');
    const loginForm = document.querySelector('#login-form');
    const registerForm = document.querySelector('#register-form');
    shell.hidden = true;
    document.querySelectorAll('[data-auth-mode]').forEach((button) => button.addEventListener('click', () => setAuthMode(button.dataset.authMode)));
    loginForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!loginForm.reportValidity()) return;
      const submit = loginForm.querySelector('button[type="submit"]');
      const error = document.querySelector('#auth-error');
      submit.disabled = true;
      error.hidden = true;
      try {
        const fields = new FormData(loginForm);
        await apiFetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: fields.get('username'), password: fields.get('password') })
        });
        loginForm.elements.password.value = '';
        await establishSession();
        showToast('已进入内部工作台');
      } catch (loginError) {
        showAuthGate(loginError.message);
      } finally {
        submit.disabled = false;
      }
    });
    registerForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!registerForm.reportValidity()) return;
      const submit = registerForm.querySelector('button[type="submit"]');
      const error = document.querySelector('#auth-error');
      submit.disabled = true;
      error.hidden = true;
      try {
        const fields = new FormData(registerForm);
        await apiFetch('/api/auth/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            display_name: fields.get('display_name'),
            username: fields.get('username'),
            password: fields.get('password'),
            password_confirm: fields.get('password_confirm')
          })
        });
        registerForm.reset();
        await establishSession();
        showToast('个人账号已创建');
      } catch (registerError) {
        error.textContent = registerError.message;
        error.hidden = false;
      } finally {
        submit.disabled = false;
      }
    });
    document.querySelector('#logout-button').addEventListener('click', async () => {
      try { await apiFetch('/api/auth/logout', { method: 'POST' }); } catch { /* Session may already be expired. */ }
      platformState.user = null;
      resetPrivateClientState();
      sessionStorage.removeItem(storageKeys.activeUser);
      setAuthMode('login');
      showAuthGate('已安全退出。');
    });

    const passwordDialog = document.querySelector('#password-dialog');
    const passwordForm = document.querySelector('#password-form');
    const passwordStatus = document.querySelector('#password-status');
    document.querySelector('#open-password-dialog').addEventListener('click', () => {
      passwordForm.reset();
      passwordStatus.hidden = true;
      passwordDialog.showModal();
      passwordForm.elements.current_password.focus();
    });
    document.querySelector('#close-password-dialog').addEventListener('click', () => passwordDialog.close());
    document.querySelector('#cancel-password-dialog').addEventListener('click', () => passwordDialog.close());
    passwordForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!passwordForm.reportValidity()) return;
      const submit = document.querySelector('#submit-password');
      const fields = new FormData(passwordForm);
      submit.disabled = true;
      passwordStatus.hidden = true;
      try {
        const result = await apiFetch('/api/auth/change-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            current_password: fields.get('current_password'),
            new_password: fields.get('new_password'),
            new_password_confirm: fields.get('new_password_confirm')
          })
        });
        platformState.user = result.user || platformState.user;
        passwordForm.reset();
        passwordDialog.close();
        showToast('密码已修改，其他设备的旧会话已退出');
      } catch (error) {
        passwordStatus.textContent = error.message;
        passwordStatus.hidden = false;
      } finally {
        submit.disabled = false;
      }
    });

    const deleteAccountDialog = document.querySelector('#delete-account-dialog');
    const deleteAccountForm = document.querySelector('#delete-account-form');
    const deleteAccountStatus = document.querySelector('#delete-account-status');
    document.querySelector('#open-delete-account-dialog').addEventListener('click', () => {
      deleteAccountForm.reset();
      deleteAccountStatus.hidden = true;
      deleteAccountDialog.showModal();
      deleteAccountForm.elements.current_password.focus();
    });
    document.querySelector('#close-delete-account-dialog').addEventListener('click', () => deleteAccountDialog.close());
    document.querySelector('#cancel-delete-account-dialog').addEventListener('click', () => deleteAccountDialog.close());
    deleteAccountForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!deleteAccountForm.reportValidity()) return;
      const submit = document.querySelector('#submit-delete-account');
      const fields = new FormData(deleteAccountForm);
      submit.disabled = true;
      deleteAccountStatus.hidden = true;
      try {
        await apiFetch('/api/auth/delete-account', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            current_password: fields.get('current_password'),
            confirmation: fields.get('confirmation')
          })
        });
        deleteAccountDialog.close();
        platformState.user = null;
        resetPrivateClientState();
        sessionStorage.removeItem(storageKeys.activeUser);
        setAuthMode('login');
        showAuthGate('账号已注销，相关私有数据已清理。');
      } catch (error) {
        deleteAccountStatus.textContent = error.message;
        deleteAccountStatus.hidden = false;
      } finally {
        submit.disabled = false;
      }
    });
  }

  async function initPlatform() {
    initAuthentication();
    if (location.protocol === 'file:') {
      window.location.replace(`http://127.0.0.1:8767/index.html${location.hash || '#tasks'}`);
      return;
    }
    try {
      platformState.health = await apiFetch('/api/health');
      platformState.connected = true;
      updatePlatformStatus();
      await establishSession();
    } catch (error) {
      if (platformState.connected) showAuthGate(error.message.includes('身份') ? '' : error.message);
      else showAuthGate('本地服务未启动，请运行 Windows 启动器后重试。');
    }
  }

  function getUsageCost(record) {
    return (record.inputTokens * usageRates.input + record.outputTokens * usageRates.output) / 1000000;
  }

  function formatTokens(value, compact = false) {
    if (!compact) return new Intl.NumberFormat('zh-CN').format(value);
    if (value >= 10000) return `${(value / 10000).toFixed(value >= 1000000 ? 1 : 2).replace(/\.0$/, '')} 万`;
    return new Intl.NumberFormat('zh-CN').format(value);
  }

  function getVisibleUsageRecords() {
    if (usageRange === 'month') return usageRecords;
    return usageRecords.slice(-Number(usageRange));
  }

  function renderUsage() {
    const records = getVisibleUsageRecords();
    const totals = records.reduce((summary, record) => ({
      analyses: summary.analyses + record.analyses,
      inputTokens: summary.inputTokens + record.inputTokens,
      outputTokens: summary.outputTokens + record.outputTokens,
      cost: summary.cost + getUsageCost(record)
    }), { analyses: 0, inputTokens: 0, outputTokens: 0, cost: 0 });
    const totalTokens = totals.inputTokens + totals.outputTokens;
    const inputShare = totalTokens ? (totals.inputTokens / totalTokens) * 100 : 0;
    const outputShare = totalTokens ? 100 - inputShare : 0;
    const maxAnalyses = Math.max(...records.map((record) => record.analyses), 1);
    const analysisDivisor = totals.analyses || 1;
    const dayDivisor = records.length || 1;

    document.querySelector('#usage-analysis-total').textContent = new Intl.NumberFormat('zh-CN').format(totals.analyses);
    document.querySelector('#usage-analysis-average').textContent = `日均 ${(totals.analyses / dayDivisor).toFixed(1)} 次`;
    document.querySelector('#usage-input-total').textContent = formatTokens(totals.inputTokens, true);
    document.querySelector('#usage-input-average').textContent = `单次平均 ${formatTokens(Math.round(totals.inputTokens / analysisDivisor))}`;
    document.querySelector('#usage-output-total').textContent = formatTokens(totals.outputTokens, true);
    document.querySelector('#usage-output-average').textContent = `单次平均 ${formatTokens(Math.round(totals.outputTokens / analysisDivisor))}`;
    document.querySelector('#usage-cost-total').textContent = `¥${totals.cost.toFixed(2)}`;
    document.querySelector('#usage-period-label').textContent = records.length ? `${records[0].date} 至 ${records.at(-1).date}` : '暂无模型调用记录';
    document.querySelector('#usage-record-count').textContent = `${records.length} 个统计日`;
    document.querySelector('#usage-input-share').textContent = `${inputShare.toFixed(1)}%`;
    document.querySelector('#usage-output-share').textContent = `${outputShare.toFixed(1)}%`;
    document.querySelector('#usage-input-meter').style.width = `${inputShare}%`;
    document.querySelector('#usage-output-meter').style.width = `${outputShare}%`;

    document.querySelector('#usage-analysis-chart').innerHTML = records.map((record) => {
      const height = Math.max(8, (record.analyses / maxAnalyses) * 100);
      const dateLabel = record.date.slice(5).replace('-', '/');
      return `<div class="usage-chart-column" title="${record.date}：${record.analyses} 次" aria-label="${record.date}，${record.analyses} 次分析">
        <strong>${record.analyses}</strong><div class="usage-bar-track"><span style="height:${height.toFixed(1)}%"></span></div><small>${dateLabel}</small>
      </div>`;
    }).join('');

    document.querySelector('#usage-table-body').innerHTML = [...records].reverse().map((record) => {
      const total = record.inputTokens + record.outputTokens;
      return `<tr><td><strong>${record.date}</strong></td><td>${record.analyses}</td><td>${formatTokens(record.inputTokens)}</td><td>${formatTokens(record.outputTokens)}</td><td>${formatTokens(total)}</td><td class="usage-cost-cell">¥${getUsageCost(record).toFixed(2)}</td></tr>`;
    }).join('');
  }

  function exportUsageCsv() {
    const records = getVisibleUsageRecords();
    if (!records.length) {
      showToast('当前没有可导出的 AI 用量记录');
      return;
    }
    const rows = [
      ['日期', '分析次数', '输入 Token', '输出 Token', '总 Token', '估算成本（元）'],
      ...records.map((record) => [record.date, record.analyses, record.inputTokens, record.outputTokens, record.inputTokens + record.outputTokens, getUsageCost(record).toFixed(2)])
    ];
    const csv = `\uFEFF${rows.map((row) => row.join(',')).join('\r\n')}`;
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `AI用量统计_${records[0].date}_${records.at(-1).date}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    showToast('AI 用量明细已导出');
  }

  function initUsageControls() {
    document.querySelectorAll('[data-usage-range]').forEach((button) => button.addEventListener('click', () => {
      usageRange = button.dataset.usageRange;
      document.querySelectorAll('[data-usage-range]').forEach((control) => control.classList.toggle('is-active', control === button));
      renderUsage();
    }));
    document.querySelector('#export-usage').addEventListener('click', exportUsageCsv);
    renderUsage();
  }

  function showView(view, updateHash = true) {
    const legacyKnowledgeView = view === 'knowledge';
    let target = legacyKnowledgeView ? 'rules' : (pageMeta[view] ? view : 'tasks');
    if (legacyKnowledgeView && !platformState.permissions.includes('knowledge')) target = 'tasks';
    if (target === 'accounts' && !platformState.permissions.includes('users')) target = 'tasks';
    document.querySelectorAll('[data-view-panel]').forEach((panel) => panel.classList.toggle('is-active', panel.dataset.viewPanel === target));
    document.querySelectorAll('.nav-item').forEach((item) => {
      const isCurrent = item.dataset.view === target;
      const isDocumentReviewParent = item.dataset.view === 'tasks' && ['review', 'financial-audit'].includes(target);
      item.classList.toggle('is-active', isCurrent);
      item.classList.toggle('is-parent-active', isDocumentReviewParent);
    });
    document.querySelector('#page-eyebrow').textContent = pageMeta[target][0];
    document.querySelector('#page-title').textContent = pageMeta[target][1];
    if (target === 'rules' && legacyKnowledgeView) showLibraryPanel('knowledge');
    if (target === 'chat' && platformState.authenticated) loadWorkspaceConversations().catch((error) => showToast(error.message));
    if (target === 'financial-audit') prepareFinancialAuditView();
    if (updateHash) history.replaceState(null, '', `#${target}`);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function initNavigation() {
    document.querySelectorAll('[data-view], [data-nav-view]').forEach((control) => {
      control.addEventListener('click', () => {
        const view = control.dataset.view || control.dataset.navView;
        showView(view);
        if (control.dataset.filterSaved === 'true') {
          document.querySelector('#rule-status-filter').value = 'saved';
          renderRuleList();
        }
      });
    });
    const initialView = location.hash.replace('#', '');
    showView(initialView === 'knowledge' ? 'knowledge' : (pageMeta[initialView] ? initialView : 'tasks'), false);
  }

  const decisionSources = {
    listingRules: 'https://www.szse.cn/lawrules/rule/stock/supervision/chinext/t20260424_620189.html',
    standardOperation: 'https://www.szse.cn/lawrules/rule/stock/supervision/chinext/t20260424_620195.html',
    standardOperationArticle731: '/research/szse-chinext-standard-operation-2026.pdf#page=98',
    annualReport: 'https://static.cninfo.com.cn/finalpage/2026-04-08/1225082514.PDF',
    quarterlyReport: 'https://static.cninfo.com.cn/finalpage/2026-04-24/1225159400.PDF',
    articles: 'https://static.cninfo.com.cn/finalpage/2025-08-26/1224568792.PDF',
    investmentPolicy: 'https://static.cninfo.com.cn/finalpage/2025-08-26/1224568799.PDF',
    relatedPolicy: 'https://static.cninfo.com.cn/finalpage/2025-08-26/1224568797.PDF',
    contractExample: 'https://static.cninfo.com.cn/finalpage/2023-09-08/1217814058.PDF'
  };
  const auditedMainBusinessRevenue = 137743966.49;

  let decisionType = 'equity';

  function numberValue(selector) {
    const value = Number(document.querySelector(selector)?.value);
    return Number.isFinite(value) ? value : 0;
  }

  function optionalNumberValue(selector) {
    const input = document.querySelector(selector);
    if (!input || String(input.value || '').trim() === '') return null;
    const value = Number(input.value);
    return Number.isFinite(value) ? value : null;
  }

  function absolute(value) {
    return Math.abs(Number(value) || 0);
  }

  function ratio(value, base) {
    return absolute(base) > 0 ? (absolute(value) / absolute(base)) * 100 : 0;
  }

  function formatAmount(value) {
    return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatCurrency(value) {
    return `¥${formatAmount(value)}`;
  }

  function formatRatio(value) {
    return `${Number(value || 0).toFixed(2)}%`;
  }

  function assessContractMaterialImpact(amount, base, contractCategory, newBusiness) {
    const assetsRatio = ratio(amount, base.assets);
    const revenueRatio = ratio(amount, base.mainRevenue);
    const netAssetsRatio = ratio(amount, base.netAssets);
    const absoluteTrigger = amount > 100000000;
    const quantitativeTrigger = contractCategory === 'sales'
      ? absoluteTrigger && revenueRatio >= 50
      : contractCategory === 'purchase'
        ? absoluteTrigger && assetsRatio >= 50
        : false;
    const qualitativeSignals = [];
    if (assetsRatio >= 10) qualitativeSignals.push(`占审计总资产 ${formatRatio(assetsRatio)}`);
    if (revenueRatio >= 10) qualitativeSignals.push(`占主营业务收入 ${formatRatio(revenueRatio)}`);
    if (netAssetsRatio >= 10) qualitativeSignals.push(`占归母净资产 ${formatRatio(netAssetsRatio)}`);
    if (absoluteTrigger) qualitativeSignals.push('金额超过 1 亿元');
    if (newBusiness) qualitativeSignals.push('属于新业务或首次重大合作');
    const likely = quantitativeTrigger || (contractCategory === 'other' && (
      absoluteTrigger || assetsRatio >= 10 || revenueRatio >= 10 || netAssetsRatio >= 10 ||
      (newBusiness && amount >= 10000000)
    ));
    const basis = qualitativeSignals.length
      ? qualitativeSignals.join('、')
      : '金额及审计基准暂未显示明显重大性指标';
    return {
      likely,
      quantitativeTrigger,
      assetsRatio,
      revenueRatio,
      netAssetsRatio,
      basis,
      text: likely
        ? `系统识别为“可能产生重大影响”：${basis}。应补充财务影响测算并由证券部复核。`
        : `系统暂未识别为“可能产生重大影响”：${basis}。如合同存在特殊履约、亏损、资产减值或经营模式影响，仍应人工补充说明。`
    };
  }

  function renderMaterialImpactAssessment(assessment) {
    const text = document.querySelector('#material-impact-auto-text');
    const badge = document.querySelector('#material-impact-auto-badge');
    if (!text || !badge || !assessment) return;
    text.textContent = assessment.text;
    badge.textContent = assessment.likely ? '可能重大' : '暂未识别';
    badge.className = `auto-field-badge ${assessment.likely ? 'hit' : 'clear'}`;
  }

  function getDecisionBaseline() {
    return {
      assets: numberValue('#base-assets'),
      netAssets: numberValue('#base-net-assets'),
      revenue: numberValue('#base-revenue'),
      mainRevenue: auditedMainBusinessRevenue,
      profit: numberValue('#base-profit')
    };
  }

  function updateBaselineDisplay() {
    const base = getDecisionBaseline();
    const displayValues = {
      '#baseline-assets-display': formatCurrency(base.assets),
      '#baseline-net-assets-display': formatCurrency(base.netAssets),
      '#baseline-revenue-display': formatCurrency(base.revenue),
      '#baseline-profit-display': `${base.profit < 0 ? '-' : ''}${formatCurrency(absolute(base.profit))}`
    };
    Object.entries(displayValues).forEach(([selector, value]) => {
      const element = document.querySelector(selector);
      if (element) element.textContent = value;
    });
    const metricNotes = document.querySelectorAll('.baseline-metrics small');
    const noteValues = [
      `披露线 10%：${formatCurrency(base.assets * 0.1)}`,
      `成交额披露线：${formatCurrency(Math.max(base.netAssets * 0.1, 10000000))}`,
      `标的收入披露线：${formatCurrency(Math.max(base.revenue * 0.1, 10000000))}`
    ];
    noteValues.forEach((value, index) => {
      if (metricNotes[index]) metricNotes[index].textContent = value;
    });
  }

  function renderCalculationRows(rows) {
    document.querySelector('#calculation-body').innerHTML = rows.map((row) => {
      const state = row.stateLabel
        ? [row.stateLabel, row.stateClass || 'candidate']
        : row.shareholder ? ['股东会', 'shareholder'] : row.disclosure ? ['披露', 'hit'] : ['未触发', 'clear'];
      return `<tr>
        <td><strong>${escapeHtml(row.name)}</strong><small>${escapeHtml(row.note || '')}</small></td>
        <td>${escapeHtml(row.value)}</td>
        <td>${escapeHtml(row.ratio)}</td>
        <td>${escapeHtml(row.disclosureLine)}</td>
        <td>${escapeHtml(row.shareholderLine)}</td>
        <td><span class="calculation-state ${state[1]}">${state[0]}</span></td>
      </tr>`;
    }).join('');
  }

  function renderApprovalPath(level, contractApprovalUnconfirmed = false) {
    const levels = ['manager', 'board', 'shareholder'];
    const currentIndex = levels.indexOf(level);
    const items = contractApprovalUnconfirmed ? [
      ['manager', 'briefcase-business', '经营层', '签署权限与审议程序待核'],
      ['board', 'users', '董事会', '披露标准不等于审议标准'],
      ['shareholder', 'landmark', '股东会', '本条未直接要求']
    ] : [
      ['manager', 'briefcase-business', '经营层', level === 'manager' ? '总经理审批/授权核对' : '项目论证完成'],
      ['board', 'users', '董事会', level === 'board' ? '应审议并披露' : currentIndex > 1 ? '审议通过后提交' : '本次未触发'],
      ['shareholder', 'landmark', '股东会', level === 'shareholder' ? '应提交审议' : '本次未触发']
    ];
    document.querySelector('#approval-path').innerHTML = items.map((item, index) => {
      const itemIndex = levels.indexOf(item[0]);
      const state = itemIndex < currentIndex ? 'is-complete' : itemIndex === currentIndex ? 'is-current' : '';
      const step = `<div class="approval-step ${state}"><span><i data-lucide="${item[1]}" aria-hidden="true"></i></span><strong>${item[2]}</strong><small>${item[3]}</small></div>`;
      return index < items.length - 1 ? `${step}<i data-lucide="chevron-right" aria-hidden="true"></i>` : step;
    }).join('');
  }

  function renderDecisionEvidence(items) {
    document.querySelector('#decision-evidence').innerHTML = items.map((item) => `
      <article>
        <span class="evidence-article">${escapeHtml(item.article)}</span>
        <div><strong>${escapeHtml(item.title)}</strong><div class="evidence-actions"><a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer"><i data-lucide="book-open-check" aria-hidden="true"></i>${item.location ? '查看原文位置' : '打开来源'}</a>${item.officialUrl ? `<a href="${escapeHtml(item.officialUrl)}" target="_blank" rel="noreferrer"><i data-lucide="external-link" aria-hidden="true"></i>官方发布页</a>` : ''}</div><p>${escapeHtml(item.detail)}</p><small>${escapeHtml(item.source)}${item.location ? ` · ${escapeHtml(item.location)}` : ''}</small></div>
      </article>`).join('');
  }

  function renderReviewFlags(flags) {
    document.querySelector('#review-flag-count').textContent = `${flags.length} 项`;
    document.querySelector('#review-flags').innerHTML = flags.map((flag) => `<div class="review-flag ${flag.level || ''}"><i data-lucide="${flag.level === 'warning' ? 'triangle-alert' : 'circle-help'}" aria-hidden="true"></i><span><strong>${escapeHtml(flag.title)}</strong><small>${escapeHtml(flag.detail)}</small></span></div>`).join('');
  }

  function getRelatedOverlay(amount, base) {
    const kind = document.querySelector('#related-kind').value;
    const cumulativeAmount = amount + numberValue('#prior-related-amount');
    const netAssetsRatio = ratio(cumulativeAmount, base.netAssets);
    const board = kind === 'person'
      ? cumulativeAmount > 300000
      : kind === 'entity' && cumulativeAmount > 3000000 && netAssetsRatio >= 0.5;
    const shareholder = kind !== 'none' && cumulativeAmount > 30000000 && netAssetsRatio >= 5;
    return { kind, cumulativeAmount, netAssetsRatio, board, shareholder };
  }

  function analyzeEquityDecision(base, amount, related) {
    const changeRatio = Math.min(100, Math.max(0, numberValue('#equity-change')));
    const scopeChange = document.querySelector('#scope-change').checked;
    const factor = scopeChange ? 1 : changeRatio / 100;
    const effectiveAssets = absolute(numberValue('#target-assets')) * factor;
    const effectiveRevenue = absolute(numberValue('#target-revenue')) * factor;
    const effectiveProfit = absolute(numberValue('#target-profit')) * factor;
    const transactionProfit = absolute(numberValue('#transaction-profit'));
    const metrics = [
      { name: '标的资产总额', value: effectiveAssets, base: base.assets, disclosureAmount: 0, disclosureRatio: 10, shareholderAmount: 0, shareholderRatio: 50, note: scopeChange ? '合并范围变化，按全量口径' : `按权益变动 ${formatRatio(changeRatio)} 计算` },
      { name: '标的营业收入', value: effectiveRevenue, base: base.revenue, disclosureAmount: 10000000, disclosureRatio: 10, shareholderAmount: 50000000, shareholderRatio: 50, note: '比例与绝对金额须同时满足' },
      { name: '标的净利润', value: effectiveProfit, base: base.profit, disclosureAmount: 1000000, disclosureRatio: 10, shareholderAmount: 5000000, shareholderRatio: 50, note: '负值按绝对值计算' },
      { name: '成交金额', value: amount, base: base.netAssets, disclosureAmount: 10000000, disclosureRatio: 10, shareholderAmount: 50000000, shareholderRatio: 50, note: '含承担债务和费用' },
      { name: '交易产生利润', value: transactionProfit, base: base.profit, disclosureAmount: 1000000, disclosureRatio: 10, shareholderAmount: 5000000, shareholderRatio: 50, note: '负值按绝对值计算' }
    ].map((metric) => {
      const metricRatio = ratio(metric.value, metric.base);
      return {
        ...metric,
        metricRatio,
        disclosure: metricRatio >= metric.disclosureRatio && metric.value > metric.disclosureAmount,
        shareholder: metricRatio >= metric.shareholderRatio && metric.value > metric.shareholderAmount
      };
    });

    const priorAssetCumulative = numberValue('#prior-asset-cumulative');
    const purchaseSaleHighValue = Math.max(effectiveAssets, amount) + priorAssetCumulative;
    const purchaseSaleRatio = ratio(purchaseSaleHighValue, base.assets);
    const purchaseSale30 = purchaseSaleRatio >= 30;
    const internalRevenueConflict = ratio(effectiveRevenue, base.revenue) >= 10 && effectiveRevenue > 1000000 && effectiveRevenue <= 10000000;
    const needsShareholder = metrics.some((metric) => metric.shareholder) || purchaseSale30 || related.shareholder;
    const legalDisclosure = metrics.some((metric) => metric.disclosure) || purchaseSale30 || related.board || related.shareholder;
    const needsBoard = legalDisclosure || internalRevenueConflict;
    const approvalLevel = needsShareholder ? 'shareholder' : needsBoard ? 'board' : 'manager';

    const rows = metrics.map((metric) => ({
      name: metric.name,
      note: metric.note,
      value: formatCurrency(metric.value),
      ratio: formatRatio(metric.metricRatio),
      disclosureLine: metric.disclosureAmount ? `≥10% 且 >${formatCurrency(metric.disclosureAmount)}` : '≥10%',
      shareholderLine: metric.shareholderAmount ? `≥50% 且 >${formatCurrency(metric.shareholderAmount)}` : '≥50%',
      disclosure: metric.disclosure,
      shareholder: metric.shareholder
    }));
    rows.push({
      name: '购买/出售资产累计高值',
      note: '本次资产总额与成交额孰高，加近 12 个月同类累计',
      value: formatCurrency(purchaseSaleHighValue),
      ratio: formatRatio(purchaseSaleRatio),
      disclosureLine: '达到 30% 应披露',
      shareholderLine: '≥30% · 2/3 表决',
      disclosure: purchaseSale30,
      shareholder: purchaseSale30
    });
    if (related.kind !== 'none') {
      rows.push({
        name: related.kind === 'person' ? '关联自然人累计成交额' : '关联法人累计成交额',
        note: '连续 12 个月同一关联人/同一标的累计',
        value: formatCurrency(related.cumulativeAmount),
        ratio: formatRatio(related.netAssetsRatio),
        disclosureLine: related.kind === 'person' ? '>¥300,000' : '>¥3,000,000 且 ≥0.5%',
        shareholderLine: '>¥30,000,000 且 ≥5%',
        disclosure: related.board,
        shareholder: related.shareholder
      });
    }

    let title;
    let summary;
    let badge;
    let badgeClass;
    if (needsShareholder) {
      title = '达到披露及股东会审议标准';
      summary = `本次${document.querySelector('#deal-direction').value === 'buy' ? '购买' : '出售'}股权至少命中一项股东会标准，应先经董事会审议后提交股东会。`;
      badge = '需要披露';
      badgeClass = 'disclosure';
    } else if (legalDisclosure) {
      const hitNames = metrics.filter((metric) => metric.disclosure).map((metric) => metric.name);
      title = '达到披露标准 · 需董事会审议';
      summary = `${hitNames.length ? `本次股权交易触发${hitNames.join('、')}指标` : '本次交易触发关联交易披露指标'}，暂未达到股东会审议线。`;
      badge = '需要披露';
      badgeClass = 'disclosure';
    } else if (internalRevenueConflict) {
      title = '交易所披露线未触发 · 内部制度需复核';
      summary = '公司《对外投资管理制度》的营业收入绝对金额口径更低且与章程不一致，按内部文本已触发董事会线，披露义务须由证券部确认。';
      badge = '制度冲突';
      badgeClass = 'review';
    } else {
      title = '未触发量化披露线 · 需重大性复核';
      summary = '按当前输入未达到量化披露或股东会标准；仍须确认累计交易、关联关系、重大影响及内部授权是否完整。';
      badge = '需人工复核';
      badgeClass = 'review';
    }

    const flags = [
      { title: '核对股权指标口径', detail: scopeChange ? '确认交易确实导致合并范围变化，并使用标的公司全量指标。' : '确认权益变动比例准确，标的财务指标已按该比例换算。' },
      { title: '检查连续十二个月累计', detail: '同一类别且标的相关的交易须累计；已披露但未履行股东会程序的事项仍可能纳入。' },
      { title: '完成关联关系穿透', detail: related.kind === 'none' ? '当前按非关联方计算，仍需核对交易对方、实控人及过去/未来十二个月安排。' : '已启用关联交易口径，需履行独立董事专门会议及关联方回避程序。' },
      { title: '公司制度口径冲突', detail: '对外投资管理制度第六条（二）的人民币 1,000,000 元口径与公司章程及上市规则的人民币 10,000,000 元口径不一致。', level: 'warning' }
    ];
    if (needsShareholder) flags.push({ title: '准备审计或评估文件', detail: '股权标的达到股东会标准时，审计截止日距股东会召开日不得超过六个月。', level: 'warning' });
    if (priorAssetCumulative > 0) flags.push({ title: '复核累计输入完整性', detail: '当前累计值仅用于资产总额/成交金额高值测试，历次标的收入、利润等指标需另行逐笔复核。', level: 'warning' });

    return {
      title, summary, badge, badgeClass, approvalLevel, rows, flags,
      contractApprovalUnconfirmed: false,
      legalDisclosure, needsShareholder,
      primarySource: {
        url: decisionSources.listingRules,
        label: '查看创业板股票上市规则第 7.1.2、7.1.3 条'
      }
    };
  }

  function analyzeInvestmentDecision(base, amount, related) {
    const investmentKind = document.querySelector('#investment-kind')?.value || 'new_company';
    const targetAssets = optionalNumberValue('#investment-target-assets');
    const targetRevenue = optionalNumberValue('#investment-target-revenue');
    const targetProfit = optionalNumberValue('#investment-target-profit');
    const investmentProfit = optionalNumberValue('#investment-profit');
    const makeMetric = (name, value, metricBase, boardAmount, shareholderAmount, note, options = {}) => {
      const available = value !== null;
      const metricRatio = available ? ratio(value, metricBase) : null;
      const board = available && metricRatio >= 10 && (options.boardRequiresAmount === false || Math.abs(value) > boardAmount);
      const shareholder = available && metricRatio >= 50 && (options.shareholderRequiresAmount === false || Math.abs(value) > shareholderAmount);
      const legalBoard = available && metricRatio >= 10 && (options.legalAmount === 0 || Math.abs(value) > options.legalAmount);
      const policyOnly = board && !legalBoard;
      const policyDisclosureLine = options.boardRequiresAmount === false
        ? '≥10%'
        : `≥10% 且 >${formatCurrency(boardAmount)}`;
      const legalDisclosureLine = options.boardRequiresAmount === false
        ? '≥10%'
        : `≥10% 且 >${formatCurrency(options.legalAmount ?? boardAmount)}`;
      const disclosureLine = policyDisclosureLine === legalDisclosureLine
        ? legalDisclosureLine
        : `制度：${policyDisclosureLine}；法定：${legalDisclosureLine}`;
      return {
        name, value, note, available, metricRatio, board, shareholder, legalBoard, policyOnly,
        displayValue: available ? formatCurrency(value) : '资料未提供',
        displayRatio: available ? formatRatio(metricRatio) : '资料不足',
        disclosureLine,
        shareholderLine: options.shareholderRequiresAmount === false ? '≥50%' : `≥50% 且 >${formatCurrency(shareholderAmount)}`,
      };
    };
    const metrics = [
      makeMetric('交易涉及资产总额', targetAssets, base.assets, 0, 0, '同时有账面值和评估值时取较高者', { boardRequiresAmount: false, shareholderRequiresAmount: false, legalAmount: 0 }),
      makeMetric('交易标的年度营业收入', targetRevenue, base.revenue, 1000000, 50000000, '标的最近一个会计年度相关营业收入；制度第六条（二）为 100 万元，法定披露线按 1,000 万元', { legalAmount: 10000000 }),
      makeMetric('交易标的年度净利润', targetProfit, base.profit, 1000000, 5000000, '涉及负值时按绝对值计算', { legalAmount: 1000000 }),
      makeMetric('交易成交金额', amount, base.netAssets, 10000000, 50000000, '含承担债务和费用', { legalAmount: 10000000 }),
      makeMetric('交易产生的利润', investmentProfit, base.profit, 1000000, 5000000, '涉及负值时按绝对值计算', { legalAmount: 1000000 })
    ];
    const availableMetrics = metrics.filter((metric) => metric.available);
    const missingMetrics = metrics.filter((metric) => !metric.available && metric.name !== '交易成交金额');
    const policyBoard = metrics.some((metric) => metric.board);
    const policyShareholder = metrics.some((metric) => metric.shareholder);
    const legalBoard = metrics.some((metric) => metric.legalBoard);
    const policyOnly = metrics.some((metric) => metric.policyOnly);
    const assetOrEquityPurchase = investmentKind === 'acquire_equity';
    const purchaseSaleHighValue = assetOrEquityPurchase ? Math.max(Math.abs(targetAssets || 0), amount) : 0;
    const purchaseSaleRatio = assetOrEquityPurchase ? ratio(purchaseSaleHighValue, base.assets) : 0;
    const purchaseSale30 = assetOrEquityPurchase && purchaseSaleRatio >= 30;
    const needsShareholder = policyShareholder || purchaseSale30 || related.shareholder;
    const needsBoard = policyBoard || needsShareholder || related.board;
    const legalDisclosure = legalBoard || purchaseSale30 || related.board || related.shareholder || policyOnly;
    const investmentDisclosure = policyBoard || purchaseSale30;
    const approvalLevel = needsShareholder ? 'shareholder' : needsBoard ? 'board' : 'manager';
    const relationTriggered = related.board || related.shareholder;
    const rows = metrics.map((metric) => ({
      name: metric.name,
      note: metric.note,
      value: metric.displayValue,
      ratio: metric.displayRatio,
      disclosureLine: metric.disclosureLine,
      shareholderLine: metric.shareholderLine,
      disclosure: metric.available && (metric.legalBoard || metric.policyOnly),
      shareholder: metric.available && metric.shareholder,
      stateLabel: metric.available ? undefined : '资料不足',
      stateClass: metric.available ? undefined : 'candidate'
    }));
    if (purchaseSaleHighValue > 0) {
      rows.push({
        name: '购买/出售资产累计高值',
        note: '取得股权类投资按资产总额与成交金额孰高；连续十二个月达到总资产 30%时触发股东会',
        value: formatCurrency(purchaseSaleHighValue),
        ratio: formatRatio(purchaseSaleRatio),
        disclosureLine: '达到 30% 应披露',
        shareholderLine: '≥30% · 2/3 表决',
        disclosure: purchaseSale30,
        shareholder: purchaseSale30
      });
    }
    if (related.kind !== 'none') {
      rows.push({
        name: related.kind === 'person' ? '关联自然人累计成交额' : '关联法人累计成交额',
        note: '连续 12 个月同一关联人/同一标的累计',
        value: formatCurrency(related.cumulativeAmount),
        ratio: formatRatio(related.netAssetsRatio),
        disclosureLine: related.kind === 'person' ? '>¥300,000' : '>¥3,000,000 且 ≥0.5%',
        shareholderLine: '>¥30,000,000 且 ≥5%',
        disclosure: related.board,
        shareholder: related.shareholder,
        stateLabel: related.shareholder ? '股东会' : related.board ? '关联交易披露' : '已识别关联交易',
        stateClass: related.shareholder ? 'shareholder' : related.board ? 'hit' : 'candidate'
      });
    }
    let title;
    let summary;
    let badge;
    let badgeClass;
    if (needsShareholder) {
      title = relationTriggered && related.shareholder ? '对外投资触发关联交易及股东会标准' : '对外投资达到股东会审议标准';
      summary = purchaseSale30
        ? '取得股权类投资按连续十二个月资产交易口径达到总资产 30%，应经董事会审议后提交股东会，并由出席股东所持表决权三分之二以上通过。'
        : relationTriggered
          ? '本次对外投资叠加关联交易口径达到股东会标准，应履行关联董事/股东回避、独立董事程序并及时披露。'
          : '根据《对外投资管理制度》第五条，至少一项指标达到股东会标准，应经董事会审议后提交股东会，并及时披露。';
      badge = '需要披露';
      badgeClass = 'disclosure';
    } else if (needsBoard) {
      title = relationTriggered ? '对外投资触发关联交易董事会标准' : '对外投资达到董事会审议标准';
      summary = policyOnly
        ? '根据《对外投资管理制度》第六条，内部审批指标已触发董事会并要求及时披露；其中部分收入指标尚未达到上市规则法定金额线，按较严内部制度执行并提示口径差异。'
        : relationTriggered
          ? '本次对外投资达到关联交易董事会披露标准，应履行关联交易审议、回避和披露程序。'
          : '根据《对外投资管理制度》第六条，至少一项指标达到董事会标准，应经董事会审议并及时披露。';
      badge = '需要披露';
      badgeClass = 'disclosure';
    } else if (missingMetrics.length) {
      title = '对外投资暂未命中 · 资料不足需补充';
      summary = '交易金额当前未达到已提供指标的董事会/股东会标准，但标的财务数据不完整，不能据此确认未触发；请补充资产、收入、净利润和交易产生利润后重新判断。';
      badge = '资料不足';
      badgeClass = 'review';
    } else {
      title = '对外投资未触发量化标准';
      summary = '按《对外投资管理制度》第九条，未达到第五、六条标准的其他投资事项由总经理审批；仍须核对关联关系、连续十二个月累计和其他强制披露事项。';
      badge = '暂不披露';
      badgeClass = 'review';
    }
    const flags = [
      { title: '对外投资审批层级', detail: needsShareholder ? '董事会审议通过后提交股东会；股东会标准依据制度第五条。' : needsBoard ? '应提交董事会审议并及时披露；依据制度第六条。' : '未达到制度第五、六条量化标准，按制度第九条由总经理审批。' },
      { title: '关联交易自动识别', detail: related.kind === 'none' ? '当前选择非关联方，系统未启用关联交易金额线；仍须核对交易对方、控股股东、实际控制人及董监高关系。' : related.shareholder ? '已识别关联交易，且累计金额超过 3,000 万元并占净资产 5%以上，触发股东会审议及披露口径。' : related.board ? '已识别关联交易，且已达到董事会披露标准；关联董事/股东回避和独立董事程序需同步核对。' : '已识别关联交易，但当前累计金额未达到董事会/股东会金额披露线；关联交易性质仍须在材料中披露并核对累计口径。' },
      { title: '数字资料完整性', detail: missingMetrics.length ? `尚缺：${missingMetrics.map((metric) => metric.name).join('、')}；资料补齐前不得以“未触发”作为最终结论。` : '用于制度第五、六条的标的财务数据已填写。' },
      { title: '连续十二个月及投资性质', detail: assetOrEquityPurchase ? '取得或增加股权类投资已启用购买/出售资产 30%股东会口径；还需补充近 12 个月同类交易累计值。' : '新设、项目合作、股票基金及债权投资不自动套用购买/出售资产 30%口径，仍按具体投资性质和制度条款核对。', level: assetOrEquityPurchase ? 'warning' : undefined }
    ];
    if (policyOnly) flags.push({ title: '内部制度与法定披露线差异', detail: '制度第六条（二）营业收入绝对金额为 100 万元，现行上市规则同类法定披露线为 1,000 万元；本判断按较严制度提示，最终以有效制度版本和证券部复核为准。', level: 'warning' });
    return {
      title, summary, badge, badgeClass, approvalLevel, rows, flags,
      contractApprovalUnconfirmed: false,
      legalDisclosure: investmentDisclosure || legalDisclosure,
      needsShareholder,
      primarySource: {
        url: decisionSources.investmentPolicy,
        label: '查看对外投资管理制度第 5—10 条'
      }
    };
  }

  function analyzeContractDecision(base, amount, related) {
    const contractCategory = document.querySelector('#contract-category').value;
    const categoryRules = {
      purchase: {
        article: '第 7.3.1 条第（一）项',
        name: '合同金额 / 最近一期审计总资产',
        note: '购买原材料、燃料、动力或者接受劳务',
        base: base.assets,
        basis: '最近一期经审计总资产'
      },
      sales: {
        article: '第 7.3.1 条第（二）项',
        name: '合同金额 / 最近一期审计主营业务收入',
        note: '销售产品或商品、工程承包或者提供劳务',
        base: base.mainRevenue,
        basis: '最近一期经审计主营业务收入'
      },
      other: {
        article: '第 7.3.1 条第（三）项',
        name: '其他日常经营合同',
        note: '公司或者深交所认为可能产生重大影响的其他合同',
        base: 0,
        basis: '财务状况或经营成果'
      }
    };
    const categoryRule = categoryRules[contractCategory] || categoryRules.sales;
    const categoryRatio = ratio(amount, categoryRule.base);
    const fixedThreshold = contractCategory !== 'other' && amount > 100000000 && categoryRatio >= 50;
    const newBusiness = document.querySelector('#new-business').checked;
    const materialImpactAssessment = assessContractMaterialImpact(amount, base, contractCategory, newBusiness);
    const materialImpact = materialImpactAssessment.likely;
    renderMaterialImpactAssessment(materialImpactAssessment);
    const legalDisclosure = fixedThreshold || materialImpact || related.board || related.shareholder;
    const needsShareholder = related.shareholder;
    const approvalLevel = needsShareholder ? 'shareholder' : related.board ? 'board' : 'manager';
    const rows = [
      {
        name: categoryRule.name,
        note: categoryRule.note,
        value: formatCurrency(amount),
        ratio: contractCategory === 'other' ? '定性判断' : formatRatio(categoryRatio),
        disclosureLine: contractCategory === 'other' ? '产生重大影响' : '≥50% 且 >¥100,000,000',
        shareholderLine: '本条未直接规定',
        disclosure: fixedThreshold || (contractCategory === 'other' && materialImpact),
        shareholder: false
      }
    ];
    if (related.kind !== 'none') {
      rows.push({
        name: related.kind === 'person' ? '关联自然人累计成交额' : '关联法人累计成交额', note: '日常经营合同仍叠加关联交易口径', value: formatCurrency(related.cumulativeAmount), ratio: formatRatio(related.netAssetsRatio),
        disclosureLine: related.kind === 'person' ? '>¥300,000' : '>¥3,000,000 且 ≥0.5%', shareholderLine: '>¥30,000,000 且 ≥5%', disclosure: related.board, shareholder: related.shareholder
      });
    }

    let title;
    let summary;
    let badge;
    let badgeClass;
    if (needsShareholder) {
      title = '关联合同达到股东会审议标准';
      summary = '合同叠加关联交易口径后达到股东会标准，应履行独立董事、董事会及股东会程序并及时披露。';
      badge = '需要披露';
      badgeClass = 'disclosure';
    } else if (fixedThreshold) {
      title = '达到日常经营重大合同披露标准';
      summary = `根据规范运作指引${categoryRule.article}，合同金额超过人民币 100,000,000 元，且占${categoryRule.basis} ${formatRatio(categoryRatio)}，应当及时披露。`;
      badge = '需要披露';
      badgeClass = 'disclosure';
    } else if (materialImpact || related.board) {
      title = '达到定性或关联交易披露条件';
      summary = materialImpact ? '根据规范运作指引第 7.3.1 条第（三）项，系统识别该合同可能对公司财务状况或经营成果产生重大影响，应当及时披露并由证券部复核。' : '合同本身未命中日常经营重大合同标准，但已触发关联交易披露标准。';
      badge = '需要披露';
      badgeClass = 'disclosure';
    } else {
      title = '未触发量化披露线 · 需重大性复核';
      summary = contractCategory === 'other'
        ? '系统暂未识别该合同可能对财务状况或经营成果产生重大影响；如存在特殊履约、亏损、减值或经营模式影响，仍须按照规范运作指引第 7.3.1 条第（三）项补充复核。'
        : `合同金额未同时满足“超过人民币 100,000,000 元且占${categoryRule.basis} 50%以上”，未触发规范运作指引第 7.3.1 条的量化披露线。`;
      badge = '需人工复核';
      badgeClass = 'review';
    }

    const flags = [
      { title: '确认合同分类与计算基准', detail: `${categoryRule.note}；本次适用${categoryRule.article}${contractCategory === 'other' ? '的定性标准' : `，计算基准为${categoryRule.basis}`}。` },
      { title: '完成重大影响判断', detail: materialImpactAssessment.text },
      { title: '核对内部签署权限', detail: '现有公开章程未给出日常经营合同的完整分级授权表；固定披露标准不等于董事会审批标准。', level: 'warning' },
      { title: '跟踪履约进展', detail: '重大合同生效、履行重大变化、出现重大不确定性、提前解除或终止时须继续披露。' }
    ];
    if (newBusiness) flags.push({ title: '新业务专项风险', detail: '首次重大合作或新业务应补充商业模式、履约能力、资金来源及不确定性说明。', level: 'warning' });
    if (related.kind !== 'none') flags.push({ title: '关联交易程序', detail: '核对连续十二个月累计、独立董事专门会议及关联董事/股东回避。', level: 'warning' });

    return {
      title, summary, badge, badgeClass, approvalLevel, rows, flags,
      contractApprovalUnconfirmed: !related.board && !needsShareholder && legalDisclosure,
      legalDisclosure, needsShareholder,
      primarySource: {
        url: decisionSources.standardOperationArticle731,
        label: `查看 PDF 第 98 页 · ${categoryRule.article}`
      }
    };
  }

  function analyzeDecision() {
    updateBaselineDisplay();
    const base = getDecisionBaseline();
    const amount = absolute(numberValue('#transaction-amount'));
    const related = getRelatedOverlay(amount, base);
    const result = decisionType === 'equity'
      ? analyzeEquityDecision(base, amount, related)
      : decisionType === 'investment'
        ? analyzeInvestmentDecision(base, amount, related)
        : analyzeContractDecision(base, amount, related);
    document.querySelector('#result-title').textContent = result.title;
    document.querySelector('#result-summary').textContent = result.summary;
    const sourceLink = document.querySelector('#result-source-link');
    sourceLink.hidden = !result.primarySource;
    if (result.primarySource) {
      sourceLink.href = result.primarySource.url;
      document.querySelector('#result-source-link-text').textContent = result.primarySource.label;
    }
    const badge = document.querySelector('#result-badge');
    badge.textContent = result.badge;
    badge.className = `decision-badge ${result.badgeClass}`;
    const statusIcon = document.querySelector('#result-status-icon');
    statusIcon.className = `result-status-icon ${result.badgeClass === 'review' ? 'review' : ''}`;
    statusIcon.innerHTML = `<i data-lucide="${result.badgeClass === 'review' ? 'scan-search' : result.needsShareholder ? 'landmark' : 'megaphone'}" aria-hidden="true"></i>`;
    document.querySelector('#approval-note').textContent = decisionType === 'equity'
      ? '公司章程第 49、115 条及对外投资管理制度第 5、6、9 条'
      : decisionType === 'investment'
        ? '对外投资管理制度第 5、6、7、9、10 条及关联交易管理口径'
        : result.needsShareholder ? '关联交易规则触发股东会程序' : '规范运作指引第 7.3.1 条仅规定披露标准，内部审批需另核授权';
    renderApprovalPath(result.approvalLevel, result.contractApprovalUnconfirmed);
    renderCalculationRows(result.rows);
    renderReviewFlags(result.flags);

    const evidence = decisionType === 'equity' ? [
      { article: '7.1.2 / 7.1.3', title: '创业板股票上市规则（2026 年修订）', detail: '规定重大交易的及时披露及股东会审议五项财务指标。', source: '深圳证券交易所 · 2026-04-24', url: decisionSources.listingRules },
      { article: '7.1.8 / 7.1.12', title: '股权变动与购买、出售资产特别口径', detail: '按权益变动比例计算；合并范围变化按全量指标；连续十二个月高值达到总资产 30% 时须经股东会三分之二以上通过。', source: '深圳证券交易所 · 现行有效', url: decisionSources.listingRules },
      { article: '第 49 / 115 条', title: '创业黑马公司章程', detail: '载明公司股东会、董事会重大交易审批标准，并采用连续十二个月累计原则。', source: '巨潮资讯 · 2025-08-26，2026-01 部分条款修订未涉及本项', url: decisionSources.articles },
      { article: '第 5 / 6 / 9 条', title: '创业黑马对外投资管理制度', detail: '分别规定股东会、董事会和总经理权限；第六条（二）与章程/上市规则存在口径冲突。', source: '巨潮资讯 · 2025-08-26', url: decisionSources.investmentPolicy },
      { article: '2025 年报', title: '创业黑马 2025 年年度报告', detail: '审计总资产 497,518,543.50 元、归母净资产 370,169,805.58 元、营业收入 141,062,775.50 元、归母净利润 -49,090,350.56 元。', source: '巨潮资讯 · 2026-04-08', url: decisionSources.annualReport }
    ] : decisionType === 'investment' ? [
      { article: '第五条', title: '创业黑马对外投资管理制度 · 股东会权限', detail: '交易涉及资产总额、标的营业收入、标的净利润、成交金额或交易产生利润达到制度第五条任一标准的，应经董事会审议通过后提交股东会审议。', source: '公司制度 · 2025 年版', location: 'PDF 第 2 页 · 第五条', url: decisionSources.investmentPolicy },
      { article: '第六条', title: '创业黑马对外投资管理制度 · 董事会权限及披露', detail: '对外投资达到资产总额 10%、标的收入/净利润 10%并满足绝对金额、成交金额占净资产 10%并超过 1,000 万元，或交易产生利润达到相应标准的，应经董事会审议并及时披露。', source: '公司制度 · 2025 年版', location: 'PDF 第 2—3 页 · 第六条', url: decisionSources.investmentPolicy },
      { article: '第七条', title: '购买/出售资产连续十二个月累计', detail: '购买、出售资产按资产总额与成交金额孰高计算；连续十二个月累计达到最近一期经审计总资产 30%时，应提交股东会并经出席股东所持表决权三分之二以上通过。', source: '公司制度 · 2025 年版', location: 'PDF 第 3 页 · 第七条', url: decisionSources.investmentPolicy },
      { article: '第九条 / 第十条', title: '总经理权限与关联交易衔接', detail: '未达到制度第五、六条标准的其他投资事项由总经理审批；涉及关联交易时，必须同时符合公司关联交易管理制度。', source: '公司制度 · 2025 年版', location: 'PDF 第 3 页 · 第九、十条', url: decisionSources.investmentPolicy },
      { article: '7.1.2 / 7.1.3', title: '创业板股票上市规则（2026 年修订）', detail: '重大交易达到法定指标时履行信息披露和股东会审议程序；本页面对制度口径与法定披露线分别计算并提示差异。', source: '深圳证券交易所 · 2026-04-24', url: decisionSources.listingRules },
      { article: '7.2.7 / 7.2.8', title: '关联交易披露与股东会标准', detail: '关联自然人、关联法人/组织按照交易金额、净资产比例和连续十二个月累计口径判断董事会披露及股东会标准。', source: '深圳证券交易所 · 现行有效', url: decisionSources.listingRules },
      { article: '关联交易管理制度', title: '公司关联交易管理制度', detail: '对关联方认定、关联交易审议、关联董事/股东回避和披露要求作进一步规定。', source: '公司制度 · 2025 年版', url: decisionSources.relatedPolicy }
    ] : [
      { article: '7.3.1', title: '日常经营重大合同披露标准', detail: '购买原材料、燃料、动力或接受劳务，按最近一期审计总资产计算；销售产品或商品、工程承包或提供劳务，按最近一期审计主营业务收入计算。两类均须达到 50%以上且绝对金额超过人民币 100,000,000 元。', source: '创业板上市公司规范运作（2026 年修订）', location: 'PDF 第 98 页 · 第 7.3.1 条', url: decisionSources.standardOperationArticle731, officialUrl: decisionSources.standardOperation },
      { article: '7.3.2', title: '重大合同公告内容要求', detail: '至少披露重大风险提示、合同各方情况、合同主要内容、合同履行对公司的影响及审议程序。', source: '创业板上市公司规范运作（2026 年修订）', location: 'PDF 第 98 页 · 第 7.3.2 条', url: decisionSources.standardOperationArticle731, officialUrl: decisionSources.standardOperation },
      { article: '7.3.4 / 7.3.5', title: '重大合同持续披露要求', detail: '及时披露合同生效、履行重大变化、重大不确定性、提前解除或终止，并在年度报告、半年度报告中持续披露履行情况。', source: '创业板上市公司规范运作（2026 年修订）', location: 'PDF 第 99 页 · 第 7.3.4 至 7.3.5 条', url: '/research/szse-chinext-standard-operation-2026.pdf#page=99', officialUrl: decisionSources.standardOperation },
      { article: '历史案例', title: '创业黑马全资子公司签订重大合同公告', detail: '2023-050 号公告披露约人民币 116,000,000 元销售合同；该案例用于观察公司披露实践，不替代现行规则判断。', source: '巨潮资讯 · 2023-09-08', url: decisionSources.contractExample },
      { article: '2025 年报', title: '创业黑马 2025 年年度报告', detail: '销售类合同的法定计算基准取自年报中已审计的主营业务收入 137,743,966.49 元；采购类合同基准为审计总资产 497,518,543.50 元。', source: '巨潮资讯 · 2026-04-08', url: decisionSources.annualReport }
    ];
    if (related.kind !== 'none') evidence.splice(2, 0, {
      article: '7.2.7 / 7.2.8', title: '关联交易披露与股东会标准', detail: '关联自然人超过人民币 300,000 元；关联法人超过人民币 3,000,000 元且占净资产 0.5%以上；超过人民币 30,000,000 元且占净资产 5%以上须提交股东会。', source: '创业板股票上市规则（2026 年修订）', url: decisionSources.listingRules
    });
    renderDecisionEvidence(evidence);
    refreshIcons();
  }

  function setDecisionType(type, resetExample = true) {
    decisionType = ['contract', 'investment'].includes(type) ? type : 'equity';
    document.querySelectorAll('[data-decision-type]').forEach((button) => {
      const selected = button.dataset.decisionType === decisionType;
      button.classList.toggle('is-active', selected);
      button.setAttribute('aria-selected', String(selected));
    });
    document.querySelector('.contract-fields').hidden = decisionType !== 'contract';
    document.querySelector('.equity-fields').hidden = decisionType !== 'equity';
    document.querySelector('.investment-fields').hidden = decisionType !== 'investment';
    if (resetExample) resetDecisionExample();
  }

  function resetDecisionExample() {
    document.querySelector('#related-kind').value = 'none';
    document.querySelector('#prior-related-amount').value = '0';
    if (decisionType === 'contract') {
      document.querySelector('#matter-name').value = '签订年度 AI 培训服务合同';
      document.querySelector('#transaction-amount').value = '120000000';
      document.querySelector('#contract-category').value = 'sales';
      document.querySelector('#new-business').checked = true;
    } else if (decisionType === 'investment') {
      document.querySelector('#matter-name').value = '设立全资子公司并出资';
      document.querySelector('#transaction-amount').value = '40000000';
      document.querySelector('#investment-kind').value = 'new_company';
      document.querySelector('#investment-target-assets').value = '';
      document.querySelector('#investment-target-revenue').value = '';
      document.querySelector('#investment-target-profit').value = '';
      document.querySelector('#investment-profit').value = '';
    } else {
      document.querySelector('#matter-name').value = '收购某科技公司 100% 股权';
      document.querySelector('#transaction-amount').value = '45000000';
      document.querySelector('#deal-direction').value = 'buy';
      document.querySelector('#equity-change').value = '100';
      document.querySelector('#scope-change').checked = true;
      document.querySelector('#target-assets').value = '50000000';
      document.querySelector('#target-revenue').value = '18000000';
      document.querySelector('#target-profit').value = '3000000';
      document.querySelector('#transaction-profit').value = '2000000';
      document.querySelector('#prior-asset-cumulative').value = '0';
    }
    analyzeDecision();
  }

  function setDecisionFontSize(size, persist = true) {
    const allowedSizes = new Set(['small', 'normal', 'large']);
    const selectedSize = allowedSizes.has(size) ? size : 'normal';
    const resultPanel = document.querySelector('.decision-result-panel');
    resultPanel.dataset.fontSize = selectedSize;
    document.querySelectorAll('[data-result-font]').forEach((button) => {
      const selected = button.dataset.resultFont === selectedSize;
      button.classList.toggle('is-active', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    if (persist) writeJson(storageKeys.decisionFontSize, selectedSize);
  }

  function initDecisionControls() {
    const form = document.querySelector('#decision-form');
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      analyzeDecision();
      document.querySelector('.decision-result-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    document.querySelectorAll('[data-decision-type]').forEach((button) => button.addEventListener('click', () => setDecisionType(button.dataset.decisionType)));
    document.querySelectorAll('[data-result-font]').forEach((button) => button.addEventListener('click', () => setDecisionFontSize(button.dataset.resultFont)));
    document.querySelector('#reset-decision').addEventListener('click', resetDecisionExample);
    document.querySelectorAll('.baseline-editor input').forEach((input) => input.addEventListener('input', updateBaselineDisplay));
    document.querySelectorAll('#transaction-amount, #contract-category, #new-business, #base-assets, #base-net-assets, #base-revenue, #related-kind, #prior-related-amount, #investment-kind, #investment-target-assets, #investment-target-revenue, #investment-target-profit, #investment-profit')
      .forEach((control) => control.addEventListener('input', analyzeDecision));
    document.querySelector('#contract-category')?.addEventListener('change', analyzeDecision);
    document.querySelector('#new-business')?.addEventListener('change', analyzeDecision);
    document.querySelectorAll('#related-kind, #investment-kind').forEach((control) => control.addEventListener('change', analyzeDecision));
    setDecisionFontSize(readJson(storageKeys.decisionFontSize, 'normal'), false);
    updateBaselineDisplay();
    analyzeDecision();
  }

  function parseTimestamp(value) {
    const raw = String(value || '').trim();
    if (!raw) return null;
    const bare = raw.match(/^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?$/);
    const normalized = bare
      ? `${bare[1]}T${bare[2] || '00'}:${bare[3] || '00'}:${bare[4] || '00'}${bare[5] ? `.${bare[5]}` : ''}+08:00`
      : raw;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatDataTimestamp(value) {
    if (!value) return '尚未同步';
    const date = parseTimestamp(value);
    if (!date) return '时间待确认';
    const parts = Object.fromEntries(new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai',
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    }).formatToParts(date).filter((item) => item.type !== 'literal').map((item) => [item.type, item.value]));
    return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
  }

  function formatBeijingDate(value) {
    const timestamp = formatDataTimestamp(value);
    return timestamp === '尚未同步' || timestamp === '时间待确认' ? timestamp : timestamp.slice(0, 10);
  }

  function isFreshData(value, maximumHours = 36) {
    const timestamp = new Date(value).getTime();
    return Number.isFinite(timestamp) && Date.now() - timestamp <= maximumHours * 60 * 60 * 1000;
  }

  function formatAnnouncementSize(sizeKB) {
    const size = Number(sizeKB || 0);
    if (!size) return 'PDF';
    return size >= 1024 ? `${(size / 1024).toFixed(1)} MB` : `${Math.round(size)} KB`;
  }

  function updateSourceHealth(element, isFresh) {
    element.classList.toggle('warning', !isFresh);
    element.innerHTML = `<i data-lucide="${isFresh ? 'check-circle-2' : 'triangle-alert'}" aria-hidden="true"></i>${isFresh ? '已同步' : '待更新'}`;
  }

  function renderDataOverview() {
    const announcements = companyData.announcements ?? [];
    const stats = companyData.stats ?? {};
    const latest = announcements[0];
    document.querySelector('#announcement-total').textContent = Number(stats.total || announcements.length).toLocaleString('zh-CN');
    document.querySelector('#periodic-total').textContent = Number(stats.periodicTotal || announcements.filter((item) => item.isPeriodic).length).toLocaleString('zh-CN');
    document.querySelector('#data-rule-total').textContent = data.records.length.toLocaleString('zh-CN');
    document.querySelector('#announcement-range').textContent = stats.earliestAt && stats.latestAt ? `${stats.earliestAt} 至 ${stats.latestAt}` : '等待同步历史公告';
    document.querySelector('#latest-announcement-date').textContent = stats.latestAt || '待同步';
    document.querySelector('#latest-announcement-name').textContent = latest?.title || '以巨潮资讯公开披露为准';
    document.querySelector('#company-sync-meta').textContent = `本地版本 ${formatDataTimestamp(companyData.generatedAt)} · ${announcements.length.toLocaleString('zh-CN')} 条`;
    document.querySelector('#rules-sync-meta').textContent = `本地版本 ${formatDataTimestamp(data.generatedAt)} · ${data.records.length.toLocaleString('zh-CN')} 条`;
    document.querySelector('#company-data-note').textContent = companyData.note || '公告正文、披露时间及效力以巨潮资讯网原始 PDF 为准。';
    updateSourceHealth(document.querySelector('#company-source-health'), isFreshData(companyData.generatedAt));
    updateSourceHealth(document.querySelector('#rules-source-health'), isFreshData(data.generatedAt));
  }

  function renderAnnouncementTaxonomy() {
    const categoriesRoot = document.querySelector('#announcement-categories');
    const categories = (companyData.categories ?? []).filter((category) => category.count > 0);
    document.querySelector('#category-count-all').textContent = Number(companyData.stats?.total || companyData.announcements.length).toLocaleString('zh-CN');
    categoriesRoot.innerHTML = categories.map((category) => `
      <button class="announcement-category ${announcementCategory === category.id ? 'is-active' : ''}" type="button" data-announcement-category="${escapeHtml(category.id)}">
        <span>${escapeHtml(category.name)}</span><small>${Number(category.count).toLocaleString('zh-CN')}</small>
      </button>`).join('');

    const allButton = document.querySelector('[data-announcement-category="all"]');
    allButton.classList.toggle('is-active', announcementCategory === 'all');
    allButton.onclick = () => {
      announcementCategory = 'all';
      announcementPage = 1;
      renderAnnouncementTaxonomy();
      renderAnnouncements();
    };
    categoriesRoot.querySelectorAll('[data-announcement-category]').forEach((button) => {
      button.addEventListener('click', () => {
        announcementCategory = button.dataset.announcementCategory;
        announcementPage = 1;
        renderAnnouncementTaxonomy();
        renderAnnouncements();
      });
    });

    const years = Object.entries(companyData.stats?.yearlyCounts ?? {}).sort((left, right) => Number(right[0]) - Number(left[0]));
    document.querySelector('#announcement-years').innerHTML = years.map(([year, count]) => `<button class="year-chip ${String(announcementYear) === String(year) ? 'is-active' : ''}" type="button" data-announcement-year="${year}">${year} <small>${count}</small></button>`).join('');
    const yearSelect = document.querySelector('#announcement-year-select');
    yearSelect.innerHTML = '<option value="all">全部年度</option>' + years.map(([year, count]) => `<option value="${year}">${year} 年（${count}）</option>`).join('');
    yearSelect.value = String(announcementYear);
    document.querySelectorAll('[data-announcement-year]').forEach((button) => button.addEventListener('click', () => {
      announcementYear = button.dataset.announcementYear;
      announcementPage = 1;
      renderAnnouncementTaxonomy();
      renderAnnouncements();
    }));
  }

  function getFilteredAnnouncements() {
    const keyword = document.querySelector('#announcement-search').value.trim().toLowerCase();
    const sort = document.querySelector('#announcement-sort').value;
    const filtered = (companyData.announcements ?? []).filter((announcement) => {
      const categoryMatch = announcementCategory === 'all' || announcement.categoryId === announcementCategory;
      const yearMatch = announcementYear === 'all' || String(announcement.year) === String(announcementYear);
      const scopeMatch = announcementScope === 'all' || announcement.isPeriodic;
      const keywordMatch = !keyword || `${announcement.title} ${announcement.categoryName} ${announcement.publishedAt}`.toLowerCase().includes(keyword);
      return categoryMatch && yearMatch && scopeMatch && keywordMatch;
    });
    filtered.sort((left, right) => sort === 'oldest'
      ? left.publishedAt.localeCompare(right.publishedAt) || left.id.localeCompare(right.id)
      : right.publishedAt.localeCompare(left.publishedAt) || right.id.localeCompare(left.id));
    return filtered;
  }

  function renderAnnouncements() {
    const announcements = getFilteredAnnouncements();
    const totalPages = Math.max(1, Math.ceil(announcements.length / announcementPageSize));
    announcementPage = Math.min(announcementPage, totalPages);
    const pageRecords = announcements.slice((announcementPage - 1) * announcementPageSize, announcementPage * announcementPageSize);
    const list = document.querySelector('#announcement-list');
    const empty = document.querySelector('#announcement-empty');
    const pagination = document.querySelector('#announcement-pagination');
    document.querySelector('#announcement-result-count').textContent = announcements.length.toLocaleString('zh-CN');
    document.querySelector('#announcement-page-current').textContent = announcementPage;
    document.querySelector('#announcement-page-total').textContent = totalPages;
    document.querySelector('#announcement-page-prev').disabled = announcementPage <= 1;
    document.querySelector('#announcement-page-next').disabled = announcementPage >= totalPages;
    empty.hidden = announcements.length !== 0;
    list.hidden = announcements.length === 0;
    pagination.hidden = announcements.length === 0;
    list.innerHTML = pageRecords.map((announcement) => {
      const [year, month, day] = announcement.publishedAt.split('-');
      const pdfUrl = safeOfficialUrl(announcement.pdfUrl);
      return `<article class="announcement-row">
        <time class="announcement-date" datetime="${escapeHtml(announcement.publishedAt)}"><strong>${month}-${day}</strong><span>${year}</span></time>
        <span class="announcement-type ${announcement.isPeriodic ? 'periodic' : ''}">${escapeHtml(announcement.categoryName)}</span>
        <div class="announcement-main"><a href="${pdfUrl}" target="_blank" rel="noreferrer">${escapeHtml(announcement.title)}</a><small>公告 ID ${escapeHtml(announcement.id)} · ${escapeHtml(announcement.source)}</small></div>
        <span class="announcement-size">${escapeHtml(formatAnnouncementSize(announcement.sizeKB))}</span>
        <a class="announcement-open" href="${pdfUrl}" target="_blank" rel="noreferrer" aria-label="打开${escapeHtml(announcement.title)}" data-tip="打开官方 PDF"><i data-lucide="external-link" aria-hidden="true"></i></a>
      </article>`;
    }).join('');
    refreshIcons();
  }

  function initDataCenter() {
    renderDataOverview();
    renderAnnouncementTaxonomy();
    renderAnnouncements();
    document.querySelector('#announcement-search').addEventListener('input', () => { announcementPage = 1; renderAnnouncements(); });
    document.querySelector('#announcement-year-select').addEventListener('change', (event) => {
      announcementYear = event.target.value;
      announcementPage = 1;
      renderAnnouncementTaxonomy();
      renderAnnouncements();
    });
    document.querySelector('#announcement-sort').addEventListener('change', () => { announcementPage = 1; renderAnnouncements(); });
    document.querySelectorAll('[data-announcement-scope]').forEach((button) => button.addEventListener('click', () => {
      announcementScope = button.dataset.announcementScope;
      announcementPage = 1;
      document.querySelectorAll('[data-announcement-scope]').forEach((item) => item.classList.toggle('is-active', item === button));
      renderAnnouncements();
    }));
    document.querySelector('#announcement-page-prev').addEventListener('click', () => { announcementPage = Math.max(1, announcementPage - 1); renderAnnouncements(); });
    document.querySelector('#announcement-page-next').addEventListener('click', () => { announcementPage += 1; renderAnnouncements(); });
    document.querySelector('#clear-announcement-filter').addEventListener('click', () => {
      announcementCategory = 'all';
      announcementYear = 'all';
      announcementScope = 'all';
      announcementPage = 1;
      document.querySelector('#announcement-search').value = '';
      document.querySelector('#announcement-sort').value = 'newest';
      document.querySelectorAll('[data-announcement-scope]').forEach((item) => item.classList.toggle('is-active', item.dataset.announcementScope === 'all'));
      renderAnnouncementTaxonomy();
      renderAnnouncements();
    });
    document.querySelector('#reload-data-page').addEventListener('click', () => location.reload());
  }

  function initRuleSourceMeta() {
    document.querySelector('#source-note').textContent = `${data.note || '规则正文以官方页面为准。'} 当前本地索引 ${data.records.length} 条。`;
    if (data.generatedAt) {
      document.querySelector('#rules-generated-at').textContent = `索引时间 ${formatDataTimestamp(data.generatedAt)}（北京时间）`;
    }
  }

  function renderTaxonomy() {
    const root = document.querySelector('#rule-taxonomy');
    const grouped = data.categories.reduce((map, category) => {
      if (!map.has(category.group)) map.set(category.group, []);
      map.get(category.group).push(category);
      return map;
    }, new Map());

    root.innerHTML = [...grouped.entries()].map(([group, categories]) => `
      <div class="taxonomy-group">
        <strong>${escapeHtml(group)}</strong>
        <div class="taxonomy-list">
          ${categories.map((category) => `
            <button type="button" class="taxonomy-item ${selectedCategory === category.id ? 'is-active' : ''}" data-category-id="${escapeHtml(category.id)}">
              <span>${escapeHtml(category.name)}</span><small>${category.count == null ? '—' : category.count}</small>
            </button>
          `).join('')}
        </div>
      </div>
    `).join('');

    root.querySelectorAll('[data-category-id]').forEach((button) => {
      button.addEventListener('click', () => {
        selectedCategory = button.dataset.categoryId;
        rulePage = 1;
        renderTaxonomy();
        renderRuleList();
      });
    });
  }

  function getFilteredRules() {
    const keyword = document.querySelector('#rule-search').value.trim().toLowerCase();
    const status = document.querySelector('#rule-status-filter').value;
    const sort = document.querySelector('#rule-sort').value;

    const filtered = data.records.filter((rule) => {
      const matchesCategory = selectedCategory === 'all' || rule.categories.some((category) => category.id === selectedCategory);
      const haystack = [rule.title, rule.summary, rule.navigation, ...rule.categories.map((category) => `${category.group} ${category.name}`)].join(' ').toLowerCase();
      const matchesKeyword = !keyword || haystack.includes(keyword);
      const matchesStatus = status === 'all' || (status === 'saved' ? savedRules.has(rule.id) : rule.sourceStatus === status);
      return matchesCategory && matchesKeyword && matchesStatus;
    });

    filtered.sort((left, right) => {
      if (sort === 'oldest') return left.publishedAt.localeCompare(right.publishedAt);
      if (sort === 'title') return left.title.localeCompare(right.title, 'zh-CN');
      return right.publishedAt.localeCompare(left.publishedAt);
    });
    return filtered;
  }

  function rulePresetLabel(preset) {
    if (preset === 'periodic-report') return '定期报告审查规则';
    if (preset === 'financial-accounting') return '财务会计审查规则';
    return '';
  }

  function renderRuleList() {
    const rules = getFilteredRules();
    const totalPages = Math.max(1, Math.ceil(rules.length / rulePageSize));
    rulePage = Math.min(rulePage, totalPages);
    const pageRules = rules.slice((rulePage - 1) * rulePageSize, rulePage * rulePageSize);
    const list = document.querySelector('#rule-list');
    const empty = document.querySelector('#rule-empty');
    const pagination = document.querySelector('#rule-pagination');
    document.querySelector('#rule-result-count').textContent = rules.length;
    document.querySelector('#rule-page-current').textContent = rulePage;
    document.querySelector('#rule-page-total').textContent = totalPages;
    document.querySelector('#rule-page-prev').disabled = rulePage <= 1;
    document.querySelector('#rule-page-next').disabled = rulePage >= totalPages;
    const category = data.categories.find((item) => item.id === selectedCategory);
    document.querySelector('#active-category-name').textContent = `· ${category?.name || '全部分类'}`;
    empty.hidden = rules.length !== 0;
    list.hidden = rules.length === 0;
    pagination.hidden = rules.length === 0;

    if (pageRules.length && !pageRules.some((rule) => rule.id === selectedRuleId)) selectedRuleId = pageRules[0].id;
    if (!rules.length) selectedRuleId = null;

    list.innerHTML = pageRules.map((rule) => {
      const repealed = rule.sourceStatus === 'repealed-list';
      const saved = savedRules.has(rule.id);
      const primaryCategory = rule.categories[0];
      return `
        <button type="button" class="rule-row ${selectedRuleId === rule.id ? 'is-active' : ''}" data-rule-id="${escapeHtml(rule.id)}">
          <i data-lucide="${repealed ? 'archive-x' : 'file-text'}" aria-hidden="true"></i>
          <span class="rule-row-main">
            <strong>${escapeHtml(rule.title)}</strong>
            <span class="rule-row-meta">
              <span>${escapeHtml(primaryCategory?.group || '')}</span><span>·</span><span>${escapeHtml(primaryCategory?.name || '')}</span>
              ${saved ? '<span>·</span><span><i data-lucide="bookmark-check" aria-hidden="true"></i>已加入规则包</span>' : ''}
            </span>
          </span>
          <span class="rule-row-side">
            <span class="status-chip ${repealed ? 'repealed' : 'official'}">${repealed ? '废止清单' : '官网收录'}</span>
            <time>${escapeHtml(rule.publishedAt)}</time>
          </span>
        </button>`;
    }).join('');

    list.querySelectorAll('[data-rule-id]').forEach((button) => {
      button.addEventListener('click', () => {
        selectedRuleId = button.dataset.ruleId;
        renderRuleList();
      });
    });
    renderRuleDetail();
    refreshIcons();
  }

  function renderRuleDetail() {
    const panel = document.querySelector('#rule-detail');
    const rule = data.records.find((item) => item.id === selectedRuleId);
    if (!rule) {
      panel.innerHTML = '<div class="detail-placeholder"><i data-lucide="mouse-pointer-click" aria-hidden="true"></i><strong>选择一条规则</strong><span>查看来源、分类和官方原文入口。</span></div>';
      return;
    }
    const repealed = rule.sourceStatus === 'repealed-list';
    const saved = savedRules.has(rule.id);
    panel.innerHTML = `
      <div class="rule-detail-content">
        <header class="rule-detail-head">
          <div class="detail-kickers">
            <span class="status-chip ${repealed ? 'repealed' : 'official'}">${repealed ? '废止清单收录' : '深交所官网收录'}</span>
            ${rule.categories.map((category) => `<span class="category-tag">${escapeHtml(category.name)}</span>`).join('')}
          </div>
          <h3>${escapeHtml(rule.title)}</h3>
        </header>
        <section class="rule-detail-section">
          <span class="detail-label">页面摘要</span>
          <p>${escapeHtml(rule.summary || '深交所列表页未提供可检索摘要，请打开官方原文查看完整内容。')}</p>
        </section>
        <section class="rule-detail-section">
          <span class="detail-label">来源信息</span>
          <div class="detail-meta-list">
            <div class="detail-meta-row"><span>发布机构</span><strong>${escapeHtml(rule.source)}</strong></div>
            <div class="detail-meta-row"><span>发布日期</span><strong>${escapeHtml(rule.publishedAt)}</strong></div>
            <div class="detail-meta-row"><span>页面路径</span><strong>${escapeHtml(rule.navigation || '法律规则')}</strong></div>
            <div class="detail-meta-row"><span>文件类型</span><strong>${escapeHtml(String(rule.doctype).toUpperCase())}</strong></div>
          </div>
        </section>
        <div class="detail-actions">
          <button class="button ${saved ? '' : 'button-primary'}" type="button" id="toggle-saved-rule">
            <i data-lucide="${saved ? 'bookmark-x' : 'bookmark-plus'}" aria-hidden="true"></i>${saved ? '移出规则包' : '加入审查规则包'}
          </button>
          <a class="button" href="${safeUrl(rule.url)}" target="_blank" rel="noreferrer"><i data-lucide="external-link" aria-hidden="true"></i>打开官方原文</a>
        </div>
      </div>`;
    panel.querySelector('#toggle-saved-rule').addEventListener('click', () => toggleSavedRule(rule.id));
    refreshIcons();
  }

  function toggleSavedRule(ruleId) {
    if (savedRules.has(ruleId)) {
      savedRules.delete(ruleId);
      showToast('已从审查规则包移除');
    } else {
      savedRules.add(ruleId);
      showToast('已加入审查规则包');
    }
    writeJson(userStorageKey(storageKeys.savedRules), [...savedRules]);
    updateRulePackCount();
    renderRuleList();
  }

  function updateRulePackCount() {
    const rulePackCount = document.querySelector('#rule-pack-count');
    if (rulePackCount) rulePackCount.textContent = savedRules.size;
  }

  function initRuleControls() {
    const search = document.querySelector('#rule-search');
    search.addEventListener('input', () => { rulePage = 1; renderRuleList(); });
    document.querySelector('#rule-status-filter').addEventListener('change', () => { rulePage = 1; renderRuleList(); });
    document.querySelector('#rule-sort').addEventListener('change', () => { rulePage = 1; renderRuleList(); });
    document.querySelector('#rule-page-prev').addEventListener('click', () => { rulePage = Math.max(1, rulePage - 1); renderRuleList(); });
    document.querySelector('#rule-page-next').addEventListener('click', () => { rulePage += 1; renderRuleList(); });
    document.querySelector('#clear-rule-filter').addEventListener('click', () => {
      selectedCategory = 'all';
      rulePage = 1;
      search.value = '';
      document.querySelector('#rule-status-filter').value = 'all';
      renderTaxonomy();
      renderRuleList();
    });
    document.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        showView('tasks');
        document.querySelector('#open-task-dialog')?.click();
      }
    });
  }

  function getTasks() {
    if (platformState.connected) return platformState.tasks;
    const customTasks = readJson(storageKeys.tasks, []);
    return [...customTasks, ...defaultTasks];
  }

  async function loadServerTasks() {
    if (!platformState.connected || !platformState.authenticated) return;
    const payload = await apiFetch('/api/tasks');
    platformState.tasks = payload.tasks || [];
    renderTasks();
    renderFinancialTaskOptions();
  }

  function renderTasks() {
    const tasks = getTasks();
    const visible = taskFilter === 'all' ? tasks : tasks.filter((task) => task.status === taskFilter);
    const taskIds = new Set(tasks.map((task) => String(task.id)));
    selectedTaskIds.forEach((taskId) => {
      if (!platformState.connected || !taskIds.has(String(taskId))) selectedTaskIds.delete(taskId);
    });
    const statusMeta = {
      processing: ['审查中', 'medium'],
      review: ['待复核', 'official'],
      completed: ['已完成', 'success']
    };
    document.querySelector('#task-table-body').innerHTML = visible.length ? visible.map((task) => {
      const [statusLabel, statusClass] = statusMeta[task.status] || ['待处理', 'neutral'];
      return `
        <tr>
          <td class="task-select-cell">${platformState.connected ? `<input class="task-select" type="checkbox" data-task-select="${escapeHtml(task.id)}" aria-label="选择 ${escapeHtml(task.name)}" ${selectedTaskIds.has(String(task.id)) ? 'checked' : ''}>` : ''}</td>
          <td><span class="task-name"><strong>${escapeHtml(task.name)}</strong><small>${escapeHtml(task.id)} · ${escapeHtml(task.file)}</small></span></td>
          <td>${escapeHtml(task.type)}</td>
          <td><span class="status-chip ${statusClass}">${statusLabel}</span></td>
          <td><strong class="risk-number ${task.risks > 4 ? 'high-text' : ''}">${task.risks}</strong> 项</td>
          <td>${escapeHtml(task.owner)}</td>
          <td class="table-muted">${escapeHtml(formatDataTimestamp(task.updatedAt))}</td>
          <td><div class="row-actions"><button class="row-action" type="button" data-open-review="${escapeHtml(task.id)}">${task.status === 'completed' ? '查看' : '继续审查'}</button>${platformState.connected ? `<button class="row-action danger icon-row-action" type="button" data-delete-task="${escapeHtml(task.id)}" aria-label="删除检查任务" data-tip="删除文档及任务记忆"><i data-lucide="trash-2" aria-hidden="true"></i></button>` : ''}</div></td>
        </tr>`;
    }).join('') : '<tr><td colspan="8"><div class="table-empty"><strong>暂无审查任务</strong><span>上传一份 PDF、DOCX、TXT 或 MD 开始审阅。</span></div></td></tr>';

    document.querySelector('#task-nav-count').textContent = tasks.length;
    document.querySelector('#task-count-all').textContent = tasks.length;
    ['processing', 'review', 'completed'].forEach((status) => {
      document.querySelector(`#task-count-${status}`).textContent = tasks.filter((task) => task.status === status).length;
    });
    document.querySelectorAll('[data-open-review]').forEach((button) => button.addEventListener('click', async () => {
      const task = tasks.find((item) => item.id === button.dataset.openReview);
      if (!task) return;
      await openTaskReview(task);
    }));
    document.querySelectorAll('[data-delete-task]').forEach((button) => button.addEventListener('click', async () => {
      const task = tasks.find((item) => item.id === button.dataset.deleteTask);
      if (task) await deleteTask(task);
    }));
    document.querySelectorAll('[data-task-select]').forEach((control) => control.addEventListener('change', () => {
      const taskId = String(control.dataset.taskSelect || '');
      if (!taskId) return;
      if (control.checked) selectedTaskIds.add(taskId);
      else selectedTaskIds.delete(taskId);
      updateTaskBulkControls(visible);
    }));
    const selectAll = document.querySelector('#select-all-tasks');
    if (selectAll) {
      const selectableVisible = platformState.connected ? visible : [];
      const selectedVisibleCount = selectableVisible.filter((task) => selectedTaskIds.has(String(task.id))).length;
      selectAll.disabled = selectableVisible.length === 0;
      selectAll.checked = selectableVisible.length > 0 && selectedVisibleCount === selectableVisible.length;
      selectAll.indeterminate = selectedVisibleCount > 0 && selectedVisibleCount < selectableVisible.length;
      selectAll.onchange = () => {
        selectableVisible.forEach((task) => {
          if (selectAll.checked) selectedTaskIds.add(String(task.id));
          else selectedTaskIds.delete(String(task.id));
        });
        renderTasks();
      };
    }
    updateTaskBulkControls(visible);
    if (platformState.connected) renderReports();
    refreshIcons();
  }

  function updateTaskBulkControls(visible = getTasks()) {
    const button = document.querySelector('#bulk-delete-tasks');
    const summary = document.querySelector('#task-selection-summary');
    const count = platformState.connected ? selectedTaskIds.size : 0;
    if (summary) {
      summary.textContent = `已选 ${count} 项`;
      summary.hidden = count === 0;
    }
    if (button) {
      button.disabled = count === 0;
      button.title = count ? `删除已选 ${count} 项文档审查` : '请先选择文档审查';
    }
    const selectAll = document.querySelector('#select-all-tasks');
    if (selectAll && platformState.connected) {
      const selectableVisible = visible.filter((task) => platformState.tasks.some((item) => String(item.id) === String(task.id)));
      const selectedVisibleCount = selectableVisible.filter((task) => selectedTaskIds.has(String(task.id))).length;
      selectAll.checked = selectableVisible.length > 0 && selectedVisibleCount === selectableVisible.length;
      selectAll.indeterminate = selectedVisibleCount > 0 && selectedVisibleCount < selectableVisible.length;
    }
  }

  function renderFinancialTaskOptions() {
    const select = document.querySelector('#financial-task-select');
    if (!select) return;
    const tasks = platformState.connected ? platformState.tasks : [];
    const previous = financialAuditTaskId || select.value;
    select.innerHTML = '<option value="">选择定期报告任务</option>' + tasks.map((task) => (
      `<option value="${escapeHtml(task.id)}">${escapeHtml(task.name)} · ${escapeHtml(task.file)}</option>`
    )).join('');
    if (tasks.some((task) => task.id === previous)) select.value = previous;
  }

  function financialStatusMeta(status) {
    return ({
      failed: ['明确错误', 'failed'],
      needs_review: ['待人工确认', 'needs_review'],
      source_issue: ['来源问题', 'source_issue'],
      passed: ['已核对无误', 'passed']
    })[status] || ['待分类', 'needs_review'];
  }

  function financialValue(value) {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'object') return Object.entries(value).map(([key, item]) => `${key}=${financialValue(item)}`).join('；');
    return String(value);
  }

  function filteredFinancialChecks() {
    const checks = financialAuditState?.checks || [];
    return checks.filter((check) => (
      (financialAuditStatus === 'all' || check.status === financialAuditStatus)
      && (financialAuditCategory === 'all' || check.category === financialAuditCategory)
    ));
  }

  function renderFinancialAudit() {
    const payload = financialAuditState;
    const summary = payload?.summary || {};
    document.querySelector('#financial-total').textContent = Number(summary.total || 0).toLocaleString('zh-CN');
    document.querySelector('#financial-passed').textContent = Number(summary.passed || 0).toLocaleString('zh-CN');
    document.querySelector('#financial-exceptions').textContent = Number(summary.exceptions || 0).toLocaleString('zh-CN');
    document.querySelector('#financial-severe').textContent = Number(summary.severe || 0).toLocaleString('zh-CN');
    document.querySelector('#financial-review').textContent = Number(summary.needs_review || 0).toLocaleString('zh-CN');
    const meta = document.querySelector('#financial-audit-meta');
    meta.textContent = payload
      ? `${payload.filename} · 引擎 ${payload.engineVersion} · ${Number(summary.tables_scanned || 0).toLocaleString('zh-CN')} 张表 · ${Number(summary.facts_extracted || 0).toLocaleString('zh-CN')} 个结构化事实 · 未调用外部 AI`
      : '选择一份已完成的定期报告审查任务。';

    const categories = [...new Set((payload?.checks || []).map((check) => check.category).filter(Boolean))].sort((left, right) => left.localeCompare(right, 'zh-CN'));
    const categorySelect = document.querySelector('#financial-category-filter');
    categorySelect.innerHTML = '<option value="all">全部类别</option>' + categories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`).join('');
    categorySelect.value = categories.includes(financialAuditCategory) ? financialAuditCategory : 'all';
    if (categorySelect.value === 'all') financialAuditCategory = 'all';

    const checks = filteredFinancialChecks();
    if (!checks.some((check) => check.check_id === selectedFinancialCheckId)) {
      selectedFinancialCheckId = checks.find((check) => check.status !== 'passed')?.check_id || checks[0]?.check_id || '';
    }
    const list = document.querySelector('#financial-check-list');
    list.innerHTML = checks.length ? checks.map((check) => {
      const [statusLabel, statusClass] = financialStatusMeta(check.status);
      const location = check.source_locations?.[0];
      const sourceText = [location?.table_name, location?.row_label, location?.column_label].filter(Boolean).join(' · ') || '位置待复核';
      return `<button class="financial-check-item ${check.check_id === selectedFinancialCheckId ? 'is-active' : ''}" type="button" data-financial-check="${escapeHtml(check.check_id)}"><span class="financial-check-item-top"><span class="financial-status ${statusClass}">${statusLabel}</span><small>${escapeHtml(check.category || '其他')}</small></span><strong>${escapeHtml(check.title || '')}</strong><small>${escapeHtml(sourceText)}</small></button>`;
    }).join('') : '<div class="review-empty-result"><i data-lucide="filter-x" aria-hidden="true"></i><strong>没有匹配检查项</strong><span>调整状态或类别筛选。</span></div>';
    list.querySelectorAll('[data-financial-check]').forEach((button) => button.addEventListener('click', () => {
      selectedFinancialCheckId = button.dataset.financialCheck;
      renderFinancialAudit();
    }));
    renderFinancialCheckDetail();
    refreshIcons();
  }

  function renderFinancialCheckDetail() {
    const detail = document.querySelector('#financial-check-detail');
    const check = (financialAuditState?.checks || []).find((item) => item.check_id === selectedFinancialCheckId);
    if (!check) {
      detail.innerHTML = '<div class="review-empty-result"><i data-lucide="mouse-pointer-click" aria-hidden="true"></i><strong>选择一项检查</strong><span>查看公式、取数、差异和原文位置。</span></div>';
      return;
    }
    const [statusLabel, statusClass] = financialStatusMeta(check.status);
    const inputs = Object.entries(check.inputs || {}).map(([key, value]) => `<span><b>${escapeHtml(key)}</b><code>${escapeHtml(financialValue(value))}</code></span>`).join('') || '<span><b>取数</b><code>—</code></span>';
    const caseReferences = Array.isArray(check.case_references) ? check.case_references : [];
    const caseMarkup = caseReferences.map((item) => `<div class="financial-case-reference"><strong>${escapeHtml(item.title || '已确认财务案例')}</strong><small>${escapeHtml(item.pattern || '案例校准')}</small><p>${escapeHtml(item.annotation || '')}</p><span>锚点：${escapeHtml(item.anchor_text || '原文位置')}</span></div>`).join('');
    const sources = (check.source_locations || []).map((location, index) => {
      const heading = [location.table_name, location.row_label, location.column_label].filter(Boolean).join(' · ');
      const page = location.page ? `第 ${location.page} 页` : '页码近似/待核';
      return `<button class="financial-source-location" type="button" data-financial-source="${index}"><strong>${escapeHtml(heading || '原文位置')}</strong><small>${escapeHtml(page)} · 第 ${Number(location.paragraph_index || 0) + 1} 个内容块</small><span>${escapeHtml(location.source_text || '')}</span></button>`;
    }).join('') || '<div class="financial-source-location"><strong>没有形成精确位置</strong><small>请人工定位原文。</small></div>';
    detail.innerHTML = `<header class="financial-detail-head"><div class="financial-detail-kickers"><span class="financial-status ${statusClass}">${statusLabel}</span><span class="financial-status">${escapeHtml(check.category || '其他')}</span><span class="financial-status">${escapeHtml(check.rule_id || '')}</span></div><h3>${escapeHtml(check.title || '')}</h3></header><dl class="financial-detail-grid"><dt>判断说明</dt><dd>${escapeHtml(check.explanation || '')}</dd><dt>计算公式</dt><dd><code>${escapeHtml(check.formula || '—')}</code></dd><dt>原始列示</dt><dd>${escapeHtml(financialValue(check.reported_value))}</dd><dt>本地复算</dt><dd>${escapeHtml(financialValue(check.calculated_value))}</dd><dt>差异</dt><dd>${escapeHtml(financialValue(check.difference))}</dd><dt>计算输入</dt><dd><div class="financial-input-list">${inputs}</div></dd><dt>原文位置</dt><dd><div class="financial-source-list">${sources}</div></dd>${caseMarkup ? `<dt>已确认案例参考</dt><dd><div class="financial-case-list">${caseMarkup}</div></dd>` : ''}<dt>处理建议</dt><dd>${escapeHtml(check.suggestion || '')}</dd></dl><div class="financial-detail-actions"><button class="button button-primary" type="button" id="financial-open-source"><i data-lucide="locate-fixed" aria-hidden="true"></i>在原文中定位</button></div>`;
    detail.querySelectorAll('[data-financial-source]').forEach((button) => button.addEventListener('click', () => openFinancialSource(Number(button.dataset.financialSource))));
    detail.querySelector('#financial-open-source')?.addEventListener('click', () => openFinancialSource(0));
  }

  async function loadFinancialAudit(taskId) {
    if (!platformState.connected || !taskId) return;
    financialAuditTaskId = taskId;
    document.querySelector('#financial-task-select').value = taskId;
    document.querySelector('#financial-audit-meta').textContent = '正在读取本地财务勾稽结果。';
    try {
      financialAuditState = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/financial-audit`);
      selectedFinancialCheckId = financialAuditState.checks?.find((check) => check.status !== 'passed')?.check_id || financialAuditState.checks?.[0]?.check_id || '';
      renderFinancialAudit();
    } catch (error) {
      financialAuditState = null;
      renderFinancialAudit();
      document.querySelector('#financial-audit-meta').textContent = error.message;
    }
  }

  function prepareFinancialAuditView() {
    renderFinancialTaskOptions();
    if (!platformState.connected || !platformState.tasks.length) {
      renderFinancialAudit();
      return;
    }
    if (financialAuditState && financialAuditTaskId) {
      renderFinancialAudit();
      return;
    }
    const task = platformState.tasks.find((item) => String(item.type || '').includes('定期报告')) || platformState.tasks[0];
    loadFinancialAudit(task.id);
  }

  async function openFinancialSource(index) {
    const check = (financialAuditState?.checks || []).find((item) => item.check_id === selectedFinancialCheckId);
    const location = check?.source_locations?.[index] || check?.source_locations?.[0];
    const task = platformState.tasks.find((item) => item.id === financialAuditTaskId);
    if (!check || !location || !task) {
      showToast('当前检查项没有可定位的原文位置');
      return;
    }
    await openTaskReview(task);
    setReviewReaderMode('original');
    locateOriginalRisk({
      page: location.page,
      paragraphIndex: Number(location.paragraph_index || 0),
      sourceText: location.source_text,
      originalLocations: [{
        label: [location.row_label, location.column_label].filter(Boolean).join(' · '),
        page: location.page,
        section: location.table_name,
        paragraphIndex: Number(location.paragraph_index || 0),
        text: location.source_text
      }]
    });
  }

  function downloadFinancialReport(format) {
    if (!platformState.connected || !financialAuditTaskId) {
      showToast('请先选择已完成财务勾稽的任务');
      return;
    }
    const url = `/api/tasks/${encodeURIComponent(financialAuditTaskId)}/financial-audit/report?format=${encodeURIComponent(format)}`;
    const link = document.createElement('a');
    link.href = url;
    if (format === 'docx') link.download = '';
    else link.target = '_blank';
    link.rel = 'noreferrer';
    link.click();
  }

  function initFinancialAuditControls() {
    document.querySelector('#financial-task-select').addEventListener('change', (event) => {
      if (event.target.value) loadFinancialAudit(event.target.value);
    });
    document.querySelector('#refresh-financial-audit').addEventListener('click', () => {
      if (financialAuditTaskId) loadFinancialAudit(financialAuditTaskId);
      else prepareFinancialAuditView();
    });
    document.querySelectorAll('[data-financial-status]').forEach((button) => button.addEventListener('click', () => {
      financialAuditStatus = button.dataset.financialStatus;
      document.querySelectorAll('[data-financial-status]').forEach((item) => item.classList.toggle('is-active', item === button));
      renderFinancialAudit();
    }));
    document.querySelector('#financial-category-filter').addEventListener('change', (event) => {
      financialAuditCategory = event.target.value;
      renderFinancialAudit();
    });
    document.querySelectorAll('[data-financial-report]').forEach((button) => button.addEventListener('click', () => downloadFinancialReport(button.dataset.financialReport)));
  }

  async function deleteTask(task) {
    if (!window.confirm(`确定删除“${task.name}”吗？\n\n原文件、风险结果、AI 对话、任务记忆和相关用量记录将一并永久删除。`)) return;
    try {
      await apiFetch(`/api/tasks/${encodeURIComponent(task.id)}`, { method: 'DELETE' });
      selectedTaskIds.delete(String(task.id));
      if (latestAnalysisState?.task?.id === task.id) latestAnalysisState = null;
      if (currentReviewTaskId === task.id) currentReviewTaskId = '';
      await loadServerTasks();
      showView('tasks');
      showToast('检查任务、文档和任务记忆已删除');
    } catch (error) {
      showToast(error.message);
    }
  }

  function renderReports() {
    const root = document.querySelector('#view-reports .report-list');
    const tasks = platformState.tasks;
    root.innerHTML = tasks.length ? tasks.map((task) => `<article class="report-row">
      <div class="report-icon"><i data-lucide="file-check-2" aria-hidden="true"></i></div>
      <div><strong>${escapeHtml(task.name)} · 审查报告</strong><span>${escapeHtml(task.file)} · ${Number(task.risks || 0)} 项风险 · ${escapeHtml(task.owner || '未指定')}</span></div>
      <time>${escapeHtml(formatBeijingDate(task.updatedAt))}</time>
      <button class="button" type="button" data-export-report="${escapeHtml(task.id)}"><i data-lucide="download" aria-hidden="true"></i>生成报告</button>
    </article>`).join('') : '<div class="review-empty-result"><i data-lucide="file-chart-column" aria-hidden="true"></i><strong>暂无可生成的审查报告</strong><span>完成一次文档审查后，任务会自动出现在这里。</span></div>';
    root.querySelectorAll('[data-export-report]').forEach((button) => button.addEventListener('click', () => exportReviewReport(button.dataset.exportReport)));
    refreshIcons();
  }

  async function exportReviewReport(taskId) {
    if (!platformState.connected || !taskId) {
      showToast('请使用 Windows 启动器打开完整系统');
      return;
    }
    try {
      const report = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/report`, { method: 'POST' });
      const reviewStatusLabel = (status) => ({
        confirmed: '已确认',
        false_positive: '误报',
        needs_material: '补充材料',
        resolved: '已完成',
        pending: '待复核'
      })[status || 'pending'] || '待复核';
      const sourceIdentity = (source) => [
        source.title || source.source || '',
        source.article || source.section || '',
        source.page || '',
        source.source_url || source.sourceUrl || ''
      ].join('|');
      const renderReportSource = (source, kind, kindClass = '') => {
        const sourceUrl = safeCitationUrl(source.source_url || source.sourceUrl || '');
        const title = source.title || source.source || '未命名来源';
        const article = source.article || source.section || '';
        const page = source.page ? `原文第 ${source.page} 页` : '';
        const row = source.csv_row || source.csvRow ? `CSV 第 ${source.csv_row || source.csvRow} 行` : '';
        const location = [article, source.version || '', page, row].filter(Boolean).join(' · ');
        const detail = source.detail || source.content || '当前来源未保存可展示的条款摘要，请打开原文核验。';
        const heading = sourceUrl === '#'
          ? `<strong>${escapeHtml(title)}</strong>`
          : `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">${escapeHtml(title)}</a>`;
        const openLink = sourceUrl === '#'
          ? ''
          : `<a class="source-open" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">打开来源原文</a>`;
        return `<article class="source-item"><span class="source-kind ${kindClass}">${escapeHtml(kind)}</span>${heading}${location ? `<small>${escapeHtml(location)}</small>` : '<small>具体条款位置待人工核验</small>'}<p>${escapeHtml(detail)}</p>${openLink}</article>`;
      };
      const riskIndex = report.risks.map((risk, index) => {
        const severity = getSeverityMeta(risk.severity);
        return `<a class="risk-index-item" href="#report-risk-${index + 1}"><span class="risk-index-top"><b>${String(index + 1).padStart(2, '0')}</b><i class="severity-dot ${escapeHtml(severity.chipClass)}">${escapeHtml(severity.label)}</i></span><strong>${escapeHtml(risk.title)}</strong><small>${escapeHtml(reviewStatusLabel(risk.status))} · ${escapeHtml(risk.type || '待分类')}</small></a>`;
      }).join('');
      const riskRows = report.risks.map((risk, index) => {
        const severity = getSeverityMeta(risk.severity);
        const confidence = Number.isFinite(Number(risk.confidence)) ? `${Math.round(Number(risk.confidence) * 100)}%` : '待确认';
        const allDirectBasis = risk.regulation_basis || risk.regulationBasis || [];
        const directBasis = risk.primaryRegulationBasis || risk.primary_regulation_basis || allDirectBasis.slice(0, 1);
        const additionalBasis = risk.additionalRegulationBasis || risk.additional_regulation_basis
          || allDirectBasis.slice(directBasis.length);
        const sourceDocuments = risk.sourceDocuments || risk.source_documents || [];
        const supplementarySources = [
          ...sourceDocuments.filter((source) => (
            (source.citation_kind || source.metadata?.citation_kind) !== 'deterministic_rule'
            && source.document_type !== 'user_documents'
            && hasSubstantiveRuleLocation(source)
          )),
          ...(risk.company_basis || risk.companyBasis || []),
          ...(risk.internal_rule_basis || risk.internalRuleBasis || []),
          ...(risk.historical_cases || risk.historicalCases || [])
        ];
        const directKeys = new Set([...directBasis, ...additionalBasis].map(sourceIdentity));
        const seen = new Set();
        const uniqueSupplementary = supplementarySources.filter((source) => {
          const key = sourceIdentity(source);
          if (directKeys.has(key) || seen.has(key)) return false;
          seen.add(key);
          return true;
        });
        const directMarkup = directBasis.map((source) => renderReportSource(source, '直接适用规则', 'direct')).join('');
        const additionalMarkup = additionalBasis.length
          ? `<details class="source-more"><summary>其他相关法规（${additionalBasis.length} 条）</summary><div class="source-more-list">${additionalBasis.map((source) => renderReportSource(source, '相关法规', 'rag')).join('')}</div></details>`
          : '';
        const supplementaryMarkup = uniqueSupplementary.map((source) => {
          const citationKind = source.citation_kind || source.metadata?.citation_kind || '';
          const label = citationKind === 'period_comparison'
            ? '历期官方报告对比'
            : citationKind === 'approved_case'
              ? '已确认正确案例'
              : source.document_type === 'regulations'
                ? '本地 RAG 条款命中'
                : '本地 RAG 补充资料';
          return renderReportSource(source, label, citationKind === 'period_comparison' ? 'comparison' : 'rag');
        }).join('');
        const evidenceMarkup = (directMarkup || additionalMarkup || supplementaryMarkup)
          ? `${directMarkup}${additionalMarkup}${supplementaryMarkup}`
          : '<p class="no-evidence">当前知识库未检索到直接依据，请人工进一步确认。</p>';
        const originalLocations = getRiskOriginalLocations(risk);
        const originalMarkup = originalLocations.map((location, locationIndex) => {
          const originalLocation = [
            location.page ? `第 ${location.page} 页` : '',
            location.section || '',
            Number.isInteger(location.paragraphIndex) ? `第 ${location.paragraphIndex + 1} 段` : ''
          ].filter(Boolean).join(' · ');
          return `<article class="original-excerpt"><strong>${escapeHtml(location.label || `相关原文 ${locationIndex + 1}`)}</strong><small class="original-location">${escapeHtml(originalLocation || '原文位置待确认')}</small><blockquote>${escapeHtml(location.text || '未提取到对应原文。')}</blockquote></article>`;
        }).join('');
        const calculationMarkup = renderFinancialChange(risk.financialChange || risk.calculation || {});
        return `<section class="risk-detail" id="report-risk-${index + 1}">
          <div class="risk-heading"><div><span class="risk-number">风险 ${String(index + 1).padStart(2, '0')}</span><h2>${escapeHtml(risk.title)}</h2></div><span class="severity-badge ${escapeHtml(severity.chipClass)}">${escapeHtml(severity.label)}</span></div>
          <dl class="risk-meta"><div><dt>风险类型</dt><dd>${escapeHtml(risk.type || '待分类')}</dd></div><div><dt>复核状态</dt><dd>${escapeHtml(reviewStatusLabel(risk.status))}</dd></div><div><dt>置信度</dt><dd>${escapeHtml(confidence)}</dd></div></dl>
          <div class="detail-block"><h3>问题说明</h3><p>${escapeHtml(risk.reason || risk.description || '暂无问题说明。')}</p></div>
          ${calculationMarkup ? `<div class="detail-block"><h3>财务变动判定</h3><div class="financial-change-box">${calculationMarkup}</div></div>` : ''}
          <div class="detail-block"><h3>原文位置（${originalLocations.length} 处）</h3><div class="original-list">${originalMarkup}</div></div>
          <div class="detail-block"><h3>规则与资料依据</h3><div class="source-list">${evidenceMarkup}</div></div>
          <div class="detail-block recommendation"><h3>修改建议</h3><p>${escapeHtml(risk.suggestion || risk.recommendation || '请结合适用规则和业务事实完成人工复核。').replaceAll('\n', '<br>')}</p></div>
          <a class="back-link" href="#risk-directory">返回风险目录</a>
        </section>`;
      }).join('');
      const reviewSummary = report.reviewSummary || {};
      const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(report.title)}审查报告</title><style>
        :root{color-scheme:light;--red:#a71924;--red-dark:#74111a;--black:#17191d;--ink:#292d33;--muted:#69717c;--line:#dfe3e8;--soft:#f5f6f7;--paper:#fff}
        *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#eef0f2;color:var(--ink);font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif;font-size:15px;line-height:1.7;letter-spacing:0}.report-shell{width:min(1480px,calc(100% - 40px));margin:24px auto;background:var(--paper);box-shadow:0 8px 30px rgba(22,25,29,.08)}
        .report-header{border-top:5px solid var(--red);padding:30px 34px 24px}.report-kicker{display:block;color:var(--red);font-size:13px;font-weight:700;margin-bottom:4px}.report-header h1{color:var(--black);font-size:26px;line-height:1.35;margin:0}.report-note{background:#fff5f5;border-left:3px solid var(--red);margin:20px 0 16px;padding:10px 14px}.report-meta{display:grid;grid-template-columns:minmax(0,2fr) repeat(2,minmax(160px,1fr));gap:10px 24px;margin:0}.report-meta div{min-width:0}.report-meta dt,.risk-meta dt{color:var(--muted);font-size:12px}.report-meta dd,.risk-meta dd{font-weight:600;margin:0;overflow-wrap:anywhere}.summary-bar{display:grid;grid-template-columns:repeat(5,minmax(100px,1fr));border-bottom:1px solid var(--line);border-top:1px solid var(--line)}.summary-item{padding:14px 18px}.summary-item+ .summary-item{border-left:1px solid var(--line)}.summary-item small{color:var(--muted);display:block;font-size:12px}.summary-item strong{color:var(--black);font-size:20px}
        .report-layout{display:grid;grid-template-columns:minmax(250px,30%) minmax(0,1fr);align-items:start}.risk-index{border-right:1px solid var(--line);max-height:calc(100vh - 40px);overflow:auto;padding:24px;position:sticky;top:20px}.risk-index h2{font-size:16px;margin:0 0 4px}.risk-index-intro{color:var(--muted);font-size:12px;margin:0 0 16px}.risk-index-item{border-top:1px solid var(--line);color:inherit;display:block;padding:14px 2px;text-decoration:none}.risk-index-item:last-child{border-bottom:1px solid var(--line)}.risk-index-item:hover,.risk-index-item:focus-visible{background:#faf4f4;outline:none}.risk-index-item>strong{display:block;font-size:14px;line-height:1.5;margin:5px 0}.risk-index-item>small{color:var(--muted)}.risk-index-top{align-items:center;display:flex;justify-content:space-between}.risk-index-top b{color:var(--red);font-size:13px}.severity-dot,.severity-badge{border:1px solid currentColor;font-style:normal;font-weight:700;line-height:1;padding:5px 7px}.severity-dot{font-size:11px}.severity-badge{font-size:12px;white-space:nowrap}.high{color:#9f1722}.medium{color:#9a5b00}.neutral{color:#56606c}
        .risk-details{min-width:0;padding:6px 34px 34px}.risk-detail{border-bottom:1px solid var(--line);padding:28px 0;scroll-margin-top:24px}.risk-detail:last-child{border-bottom:0}.risk-heading{align-items:flex-start;display:flex;gap:20px;justify-content:space-between}.risk-number{color:var(--red);font-size:12px;font-weight:700}.risk-heading h2{color:var(--black);font-size:20px;line-height:1.45;margin:2px 0 0}.risk-meta{background:var(--soft);display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:18px 0;padding:12px 16px}.detail-block{margin-top:22px}.detail-block h3{border-left:3px solid var(--red);color:var(--black);font-size:15px;margin:0 0 10px;padding-left:9px}.detail-block>p{margin:0;white-space:normal}.financial-change-box{background:var(--soft);border-left:3px solid var(--red);display:grid;gap:9px;padding:13px 16px}.financial-change-values{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0}.financial-change-values dt{color:var(--muted);font-size:11px}.financial-change-values dd{font-variant-numeric:tabular-nums;font-weight:700;margin:2px 0 0;overflow-wrap:anywhere}.original-list{display:grid;gap:12px}.original-excerpt{border-top:1px solid var(--line);padding-top:12px}.original-excerpt:first-child{border-top:0;padding-top:0}.original-excerpt>strong{display:block;margin-bottom:3px}.original-location{color:var(--muted);display:block;margin-bottom:7px}blockquote{background:var(--soft);border-left:3px solid #555d68;margin:0;padding:13px 16px;white-space:pre-wrap}.source-list{display:grid;gap:10px}.source-item{border-top:1px solid var(--line);padding:13px 0 3px}.source-kind{background:#eef0f2;color:#4e5864;display:inline-block;font-size:11px;font-weight:700;margin:0 8px 5px 0;padding:3px 6px}.source-kind.direct{background:#f8e9ea;color:var(--red-dark)}.source-kind.comparison{background:#edf2f6;color:#315a78}.source-item>strong,.source-item>a{color:var(--black);font-weight:700}.source-item>small{color:var(--muted);display:block;margin-top:4px}.source-item p{margin:7px 0;white-space:pre-wrap}.source-more{border:1px solid var(--line);margin-top:8px}.source-more summary{color:var(--red);cursor:pointer;font-size:12px;font-weight:700;padding:8px 10px}.source-more-list{padding:0 10px}.source-open,.back-link{color:var(--red);font-size:12px;font-weight:700;text-decoration:none}.source-open:hover,.back-link:hover{text-decoration:underline}.recommendation{background:#fffafa;border-left:3px solid var(--red);padding:14px 16px}.recommendation h3{border:0;padding:0}.recommendation p{white-space:normal}.no-evidence{background:var(--soft);color:var(--muted);margin:0;padding:12px}.back-link{display:inline-block;margin-top:18px}
        .empty-report{padding:28px 0}.report-footer{border-top:1px solid var(--line);color:var(--muted);font-size:12px;margin:0 34px;padding:18px 0 28px;overflow-wrap:anywhere}
        @media(max-width:840px){.report-shell{margin:0;width:100%}.report-header{padding:22px 18px 18px}.report-header h1{font-size:22px}.report-meta{grid-template-columns:1fr}.summary-bar{grid-template-columns:repeat(2,1fr)}.summary-item{border-bottom:1px solid var(--line)}.summary-item+ .summary-item{border-left:0}.summary-item:nth-child(even){border-left:1px solid var(--line)}.summary-item:last-child{grid-column:1/-1}.report-layout{display:block}.risk-index{border-bottom:1px solid var(--line);border-right:0;max-height:none;padding:20px 18px;position:static}.risk-details{padding:0 18px 24px}.risk-heading h2{font-size:18px}.risk-meta{grid-template-columns:1fr}.report-footer{margin:0 18px}.back-link{display:none}}
        @media print{body{background:#fff}.report-shell{box-shadow:none;margin:0;width:100%}.risk-index{display:none}.report-layout{display:block}.risk-details{padding:0 12mm}.risk-detail{break-inside:avoid;page-break-inside:avoid}.report-header{padding:8mm 12mm 5mm}.summary-bar{margin:0 12mm}.back-link{display:none}.report-footer{margin:0 12mm}}
      </style></head><body><div class="report-shell">
        <header class="report-header"><span class="report-kicker">AI 证券合规风险管理与智能审阅平台</span><h1>${escapeHtml(report.title)} · 审查报告</h1><p class="report-note">本文件是独立的合规审查报告，不替代、不改写原始文件；原始文件仍可在审阅工作台下载。</p><dl class="report-meta"><div><dt>审查文件</dt><dd>${escapeHtml(report.filename)}</dd></div><div><dt>生成时间</dt><dd>${escapeHtml(formatDataTimestamp(report.generatedAt))}（北京时间）</dd></div><div><dt>生成人</dt><dd>${escapeHtml(report.generatedBy)}</dd></div></dl></header>
        <section class="summary-bar" aria-label="审查汇总"><div class="summary-item"><small>风险总数</small><strong>${Number(report.summary.total || 0)}</strong></div><div class="summary-item"><small>高风险</small><strong>${Number(report.summary.high || 0)}</strong></div><div class="summary-item"><small>中风险</small><strong>${Number(report.summary.medium || 0)}</strong></div><div class="summary-item"><small>待复核</small><strong>${Number(reviewSummary.pending || 0)}</strong></div><div class="summary-item"><small>已确认 / 已完成</small><strong>${Number(reviewSummary.confirmed || 0) + Number(reviewSummary.resolved || 0)}</strong></div></section>
        <main class="report-layout"><aside class="risk-index" id="risk-directory"><h2>风险目录</h2><p class="risk-index-intro">点击风险，在右侧（手机端为下方）定位完整审查意见。</p>${riskIndex || '<p class="no-evidence">本次未生成风险项。</p>'}</aside><div class="risk-details">${riskRows || '<section class="empty-report"><h2>本次未生成风险项</h2><p>未命中自动检查规则不代表不存在合规风险，仍需结合适用规则完成人工复核。</p></section>'}</div></main>
        <footer class="report-footer">${escapeHtml(report.disclaimer)}<br>文件哈希：${escapeHtml(report.fileHash)}</footer>
      </div></body></html>`;
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `${String(report.title || '审查任务').replace(/[\\/:*?"<>|]/g, '_')}_审查报告.html`;
      link.click();
      URL.revokeObjectURL(url);
      showToast('审查报告已生成并记录审计日志');
      if (platformState.permissions.includes('audit')) loadAudit().catch(() => {});
    } catch (error) { showToast(error.message); }
  }

  const draftTypeLabels = {
    temporary_announcement: '临时公告',
    board_resolution: '董事会决议公告',
    shareholder_resolution: '股东会决议公告',
    meeting_notice: '会议通知',
    meeting_sign_in: '会议签到表',
    meeting_proposal: '会议议程/议案',
    meeting_agenda_summary: '主要议案概述',
    meeting_record: '会议记录',
    general_manager_meeting: '总经理会议',
    proxy_authorization: '授权委托书',
    legal_opinion: '法律意见书',
    committee_record: '专门委员会会议记录',
    committee_resolution: '专门委员会会议决议',
    independent_director_resolution: '独立董事专门会议决议',
    ballot: '会议表决票',
    related_transaction: '关联交易公告',
    investment_announcement: '对外投资公告',
    periodic_report_notice: '定期报告风险提示',
    szse_report_brief: '一页纸汇报资料'
  };
  let currentDraftId = '';

  function renderDraftSources(sources = []) {
    const root = document.querySelector('#draft-sources');
    document.querySelector('#draft-source-count').textContent = `${sources.length} 个来源`;
    const sourceHeading = document.querySelector('.draft-sources-head strong');
    const hasDirectReference = sources.some((source) => source.metadata?.direct_reference);
    if (sourceHeading) sourceHeading.textContent = hasDirectReference ? '本次导入文书' : '本地 RAG 依据';
    if (!sources.length) {
      root.innerHTML = '<div class="draft-empty"><i data-lucide="search-x" aria-hidden="true"></i><span>没有检索到直接依据，请人工进一步确认。</span></div>';
      refreshIcons();
      return;
    }
    root.innerHTML = sources.map((source, index) => {
      const url = safeCitationUrl(source.source_url || source.sourceUrl || '');
      const title = escapeHtml(source.title || source.source || '未命名资料');
      const heading = url === '#' ? `<strong>${title}</strong>` : `<a href="${url}" target="_blank" rel="noreferrer">${title}<i data-lucide="external-link" aria-hidden="true"></i></a>`;
      const location = escapeHtml(source.location || [source.page ? `第${source.page}页` : '', source.section || '', source.chunk_id || ''].filter(Boolean).join(' · ') || '位置待确认');
       const sourceLabel = source.metadata?.direct_reference
         ? '本次导入'
         : (source.style_reference || source.metadata?.style_reference ? '格式参考' : 'RAG依据');
       const caseRole = source.case_role_label ? ` · ${escapeHtml(source.case_role_label)}` : '';
       return `<article class="draft-source-item"><div class="draft-source-top"><b>${String(index + 1).padStart(2, '0')}</b><i class="draft-source-label">${sourceLabel}</i>${heading}</div><small>${location}${source.date ? ` · ${escapeHtml(source.date)}` : ''}${caseRole}</small><p>${escapeHtml(source.content || '')}</p></article>`;
    }).join('');
    refreshIcons();
  }

  function renderDraftResult(draft) {
    currentDraftId = draft?.id || '';
    const resultTitle = document.querySelector('#draft-result-title');
    const resultMeta = document.querySelector('#draft-result-meta');
    const content = document.querySelector('#draft-content');
    const save = document.querySelector('#draft-save');
    const download = document.querySelector('#draft-download');
    if (!draft) {
      resultTitle.textContent = '等待生成草稿';
      resultMeta.textContent = '生成结果会显示本地 RAG 来源和待确认项。';
      content.value = '';
      save.disabled = true;
      download.disabled = true;
      document.querySelector('#draft-warning-list').innerHTML = '';
      renderDraftSources([]);
      return;
    }
    resultTitle.textContent = draft.title || '未命名草稿';
    const directReference = (draft.source_documents || []).some((source) => source.metadata?.direct_reference);
    resultMeta.textContent = `${draftTypeLabels[draft.document_type] || draft.document_type} · ${formatDataTimestamp(draft.updated_at || draft.created_at)}（北京时间） · ${draft.source_documents?.length || 0} 个${directReference ? '原文' : '本地 RAG'}来源`;
    content.value = draft.content || '';
    save.disabled = false;
    download.disabled = false;
    const warnings = draft.warnings || [];
    document.querySelector('#draft-warning-list').innerHTML = warnings.map((warning) => `<div class="draft-warning"><i data-lucide="triangle-alert" aria-hidden="true"></i><span>${escapeHtml(warning)}</span></div>`).join('');
    renderDraftSources(draft.source_documents || []);
    refreshIcons();
  }

  function renderDraftHistory() {
    const root = document.querySelector('#draft-history-list');
    const drafts = platformState.drafts || [];
    document.querySelector('#draft-nav-count').textContent = drafts.length;
    if (!drafts.length) {
      root.innerHTML = '<div class="draft-empty"><i data-lucide="file-plus-2" aria-hidden="true"></i><span>还没有保存的草稿。</span></div>';
      refreshIcons();
      return;
    }
    root.innerHTML = drafts.map((draft) => `<article class="draft-history-row"><div class="draft-history-icon"><i data-lucide="file-text" aria-hidden="true"></i></div><div class="draft-history-main"><button type="button" data-open-draft="${escapeHtml(draft.id)}"><strong>${escapeHtml(draft.title)}</strong></button><small>${escapeHtml(draftTypeLabels[draft.document_type] || draft.document_type)} · ${formatDataTimestamp(draft.updated_at)} · ${draft.source_count || 0} 个来源</small></div><div class="draft-history-actions"><button class="row-action" type="button" data-download-draft="${escapeHtml(draft.id)}">下载 Word</button><button class="row-action danger" type="button" data-delete-draft="${escapeHtml(draft.id)}" aria-label="删除草稿">删除</button></div></article>`).join('');
    root.querySelectorAll('[data-open-draft]').forEach((button) => button.addEventListener('click', () => openDraft(button.dataset.openDraft)));
    root.querySelectorAll('[data-download-draft]').forEach((button) => button.addEventListener('click', () => downloadDraft(button.dataset.downloadDraft)));
    root.querySelectorAll('[data-delete-draft]').forEach((button) => button.addEventListener('click', () => deleteDraft(button.dataset.deleteDraft)));
    refreshIcons();
  }

  async function loadDrafts() {
    if (!platformState.connected || !platformState.authenticated || !platformState.permissions.includes('analyze')) return;
    const payload = await apiFetch('/api/drafts');
    platformState.drafts = payload.drafts || [];
    renderDraftHistory();
  }

  async function openDraft(draftId) {
    try {
      const draft = await apiFetch(`/api/drafts/${encodeURIComponent(draftId)}`);
      renderDraftResult(draft);
      showView('drafting');
      document.querySelector('#draft-content')?.focus();
    } catch (error) {
      showToast(error.message);
    }
  }

  async function deleteSelectedTasks() {
    if (!platformState.connected || !selectedTaskIds.size) return;
    const taskIds = [...selectedTaskIds];
    const tasks = platformState.tasks.filter((task) => taskIds.includes(String(task.id)));
    if (!tasks.length) {
      selectedTaskIds.clear();
      renderTasks();
      return;
    }
    const preview = tasks.length <= 3
      ? tasks.map((task) => `“${task.name}”`).join('、')
      : `${tasks.slice(0, 3).map((task) => `“${task.name}”`).join('、')} 等 ${tasks.length} 项`;
    if (!window.confirm(`确定批量删除 ${preview} 吗？\n\n原文件、风险结果、AI 对话、任务记忆、向量和审查报告将一并永久删除。此操作不可撤销。`)) return;
    const button = document.querySelector('#bulk-delete-tasks');
    const summary = document.querySelector('#task-selection-summary');
    if (button) {
      button.disabled = true;
      button.classList.add('is-busy');
      button.querySelector('span').textContent = `正在删除 ${taskIds.length} 项...`;
    }
    if (summary) {
      summary.hidden = false;
      summary.textContent = `正在删除 ${taskIds.length} 项，请稍候`;
    }
    // Let the browser paint the busy state before the server-side cascade.
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
    try {
      const result = await apiFetch('/api/tasks/batch-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_ids: taskIds })
      });
      taskIds.forEach((taskId) => selectedTaskIds.delete(String(taskId)));
      if (latestAnalysisState?.task?.id && taskIds.includes(String(latestAnalysisState.task.id))) latestAnalysisState = null;
      if (currentReviewTaskId && taskIds.includes(String(currentReviewTaskId))) currentReviewTaskId = '';
      if (financialAuditTaskId && taskIds.includes(String(financialAuditTaskId))) {
        financialAuditTaskId = '';
        financialAuditState = null;
      }
      await loadServerTasks();
      showView('tasks');
      showToast(`已批量删除 ${Number(result.taskCount || taskIds.length)} 项文档审查`);
    } catch (error) {
      showToast(error.message);
      renderTasks();
    } finally {
      if (button) {
        button.classList.remove('is-busy');
        button.querySelector('span').textContent = '批量删除';
      }
      updateTaskBulkControls();
    }
  }

  function downloadDraft(draftId = currentDraftId) {
    if (!draftId) {
      showToast('请先生成或选择一份草稿');
      return;
    }
    const link = document.createElement('a');
    link.href = `/api/drafts/${encodeURIComponent(draftId)}/document`;
    link.target = '_blank';
    link.rel = 'noreferrer';
    link.click();
  }

  async function deleteDraft(draftId) {
    if (!draftId || !window.confirm('删除这份草稿及其本地 Word 文件？')) return;
    try {
      await apiFetch(`/api/drafts/${encodeURIComponent(draftId)}`, { method: 'DELETE' });
      if (currentDraftId === draftId) renderDraftResult(null);
      await loadDrafts();
      showToast('草稿已删除');
    } catch (error) {
      showToast(error.message);
    }
  }

  function initDraftingControls() {
    const form = document.querySelector('#draft-form');
    if (!form) return;
    const status = document.querySelector('#draft-form-status');
    const submit = document.querySelector('#draft-submit');
    const documentType = document.querySelector('#draft-document-type');
    const title = document.querySelector('#draft-title');
    const subject = document.querySelector('#draft-subject');
    const facts = document.querySelector('#draft-facts');
    const requirements = document.querySelector('#draft-requirements');
    const referenceField = document.querySelector('#draft-reference-field');
    const referenceDocument = document.querySelector('#draft-reference-document');
    const updateDraftHints = () => {
      const isSzseBrief = documentType.value === 'szse_report_brief';
      const isMeetingDraft = documentType.value === 'auto' || ['meeting_notice', 'meeting_sign_in', 'meeting_proposal', 'meeting_agenda_summary', 'meeting_record', 'general_manager_meeting', 'proxy_authorization', 'legal_opinion', 'committee_record', 'committee_resolution', 'independent_director_resolution', 'ballot', 'board_resolution', 'shareholder_resolution'].includes(documentType.value);
      if (referenceField) referenceField.hidden = !isMeetingDraft;
      if (!isMeetingDraft && referenceDocument) referenceDocument.value = '';
      subject.placeholder = isSzseBrief
        ? '例如：汇报公司业务发展及重组进展'
        : isMeetingDraft
          ? '例如：关于与交易对方签署《业绩承诺与补偿协议之补充协议》的议案'
        : '例如：拟向某子公司增资 8,000 万元';
      title.placeholder = isSzseBrief
        ? '例如：关于公司业务发展及重组进展情况的汇报'
        : isMeetingDraft
          ? '例如：审计委员会2026年第X次会议记录'
        : '例如：关于对外投资暨关联交易的公告';
      facts.placeholder = isSzseBrief
        ? '填写成立/上市时间、主营业务演变、重要发展阶段、重组事项名称、当前阶段、已履行程序、监管沟通和下一步安排。未知内容不要猜测。'
        : isMeetingDraft
          ? '可留空。填写本次会议已确认的议案、会议日期、参会人员、表决结果或关联回避信息；系统会从本地会议案例提取议案说明和发言重点。'
        : '填写金额、日期、交易对方、关联关系、审批状态、资金来源等已确认事实。未知项目不要猜测。';
      requirements.placeholder = isSzseBrief
        ? '例如：控制在一页纸，突出重组当前进展、后续安排和需要监管机构指导的事项。'
        : isMeetingDraft
          ? '例如：会议记录要围绕议案说明交易背景、审议权限、风险和是否提交董事会；未知票数保留待补充。'
        : '例如：需要突出回避表决、补充风险提示，或沿用公司现行公告结构。';
    };
    documentType.addEventListener('change', updateDraftHints);
    updateDraftHints();
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      if (!subject.value.trim() && !facts.value.trim() && !requirements.value.trim()) {
        if (referenceDocument?.files?.length) {
          // A supplied meeting proposal/notice is sufficient input; its facts
          // are extracted locally by the server.
        } else {
        status.textContent = '请至少填写事项主题、已确认事实或起草要求。';
        status.classList.add('is-error');
        return;
        }
      }
      submit.disabled = true;
      const hasReference = Boolean(referenceDocument?.files?.length);
      submit.querySelector('span').textContent = hasReference ? '正在解析会议参考文书...' : '正在检索本地资料...';
      status.classList.remove('is-error');
      status.textContent = hasReference
        ? '正在读取本次会议文书，生成只引用该文件的签到表草稿。'
        : '正在读取公司资料、监管规则和历史案例。';
      try {
        const fields = new FormData(form);
        const endpoint = hasReference ? '/api/drafts/from-reference' : '/api/drafts';
        const options = hasReference
          ? { method: 'POST', body: fields }
          : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(fields.entries())) };
        const draft = await apiFetch(endpoint, options);
        renderDraftResult(draft);
        await loadDrafts();
        status.textContent = hasReference
          ? `已根据 ${referenceDocument.files[0].name} 生成会议签到表，引用 ${draft.source_documents?.length || 0} 个原文片段。`
          : `已生成草稿，引用 ${draft.source_documents?.length || 0} 个本地 RAG 来源。`;
        showToast(hasReference ? '会议签到表草稿已生成' : '本地 RAG 草稿已生成');
      } catch (error) {
        status.textContent = error.message;
        status.classList.add('is-error');
      } finally {
        submit.disabled = false;
        submit.querySelector('span').textContent = '检索资料并生成草稿';
      }
    });
    document.querySelector('#draft-save').addEventListener('click', async () => {
      if (!currentDraftId) return;
      const button = document.querySelector('#draft-save');
      button.disabled = true;
      try {
        const draft = await apiFetch(`/api/drafts/${encodeURIComponent(currentDraftId)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: document.querySelector('#draft-result-title').textContent, content: document.querySelector('#draft-content').value })
        });
        renderDraftResult(draft);
        await loadDrafts();
        showToast('草稿修改已保存');
      } catch (error) {
        showToast(error.message);
      } finally {
        button.disabled = false;
      }
    });
    document.querySelector('#draft-download').addEventListener('click', () => downloadDraft());
    document.querySelector('#draft-refresh').addEventListener('click', () => loadDrafts().catch((error) => showToast(error.message)));
    renderDraftHistory();
  }

  function initTaskControls() {
    document.querySelector('#bulk-delete-tasks')?.addEventListener('click', deleteSelectedTasks);
    document.querySelectorAll('[data-task-filter]').forEach((button) => {
      button.addEventListener('click', () => {
        taskFilter = button.dataset.taskFilter;
        document.querySelectorAll('[data-task-filter]').forEach((item) => item.classList.toggle('is-active', item === button));
        renderTasks();
      });
    });

    const dialog = document.querySelector('#task-dialog');
    const form = document.querySelector('#new-task-form');
    const fileInput = form.elements.document;
    const comparisonFileInput = form.elements.comparison_document;
    const comparisonFileStatus = document.querySelector('#comparison-file-status');
    const uploadTitle = dialog.querySelector('.upload-field strong');
    const uploadStatus = document.querySelector('#upload-file-status');
    const submitButton = document.querySelector('#submit-task');
    const submitLabel = submitButton.querySelector('span');
    const progressPanel = document.querySelector('#analysis-progress');
    const progressStage = document.querySelector('#analysis-progress-stage');
    const progressPercent = document.querySelector('#analysis-progress-percent');
    const progressTrack = progressPanel.querySelector('[role="progressbar"]');
    const progressBar = document.querySelector('#analysis-progress-bar');
    const progressMessage = document.querySelector('#analysis-progress-message');
    const progressCount = document.querySelector('#analysis-progress-count');
    const taskTypeSelect = form.elements.taskType;
    const rulePackSelect = form.elements.rulePack;
    const classificationPreview = document.querySelector('#auto-classification-preview span');
    const filenameClassification = (filename) => {
      const name = String(filename || '').replace(/\s/g, '');
      if (/(年度报告|半年度报告|季度报告|定期报告)/.test(name)) return ['定期报告一致性审查', '创业板定期报告规则包'];
      if (/(关联交易|关联方|关联关系)/.test(name)) return ['关联交易专项审查', '关联交易专项规则包'];
      if (/(股权转让|股权交易|对外投资|增资|担保|合同|资产重组|购买资产|出售资产|回购股份|股份回购|重大事项)/.test(name)) return ['重大事项披露审查', '创业板持续监管规则包'];
      return null;
    };
    const renderClassificationPreview = () => {
      const filename = fileInput.files[0]?.name || '';
      const initial = filenameClassification(filename);
      const taskManual = taskTypeSelect.value !== 'auto';
      const packManual = rulePackSelect.value !== 'auto';
      if (taskManual && packManual) {
        classificationPreview.textContent = `将使用手动选择的“${taskTypeSelect.value}”和“${rulePackSelect.value}”。`;
      } else if (taskManual) {
        classificationPreview.textContent = `审查类型已手动选择为“${taskTypeSelect.value}”，规则包将自动匹配。`;
      } else if (packManual) {
        classificationPreview.textContent = `系统将自动识别审查类型，并使用手动选择的“${rulePackSelect.value}”。`;
      } else if (initial) {
        classificationPreview.textContent = `文件名初步识别：${initial[0]}，拟匹配“${initial[1]}”；正文解析后确认。`;
      } else if (filename) {
        classificationPreview.textContent = '文件名无法确定专项类型；系统将读取正文识别，不明确时采用通用规则包并提示人工确认。';
      } else {
        classificationPreview.textContent = '上传后根据文件名和正文自动识别，识别不明确时采用通用规则包并提示人工确认。';
      }
    };
    const stageLabels = {
      queued: '等待处理', parsing: '解析文档', classification: '识别审查类型', chunking: '切分内容', embedding: '本地 Embedding',
      vector_persist: '保存向量', fast_review: '快速审查', rules: '规则检查', comparison: '跨期对比', rag: '批量检索依据', ai_analysis: 'AI 分析',
      summary_compare: '摘要与原文对比', saving: '保存结果', completed: '审查完成', failed: '处理失败'
    };
    const updateProgress = (job) => {
      const percent = Math.max(0, Math.min(Number(job.progress) || 0, 100));
      progressPanel.hidden = false;
      progressPanel.classList.toggle('is-failed', job.status === 'failed');
      progressStage.textContent = stageLabels[job.stage] || '正在处理';
      progressPercent.textContent = `${percent}%`;
      progressBar.style.width = `${percent}%`;
      progressTrack.setAttribute('aria-valuenow', String(percent));
      progressMessage.textContent = job.message || '正在本机处理文档。';
      const unit = job.stage === 'parsing' ? '内容块' : (job.stage === 'rag' ? '风险' : '片段');
      progressCount.textContent = job.totalItems > 0 ? `已处理 ${job.completedItems.toLocaleString('zh-CN')} / ${job.totalItems.toLocaleString('zh-CN')} 个${unit}` : '';
    };
    const waitForAnalysis = async (jobId) => {
      while (true) {
        const job = await apiFetch(`/api/analysis-jobs/${encodeURIComponent(jobId)}`);
        updateProgress(job);
        if (job.status === 'completed') return apiFetch(`/api/tasks/${encodeURIComponent(job.taskId)}`);
        if (job.status === 'failed') throw new Error(job.error || job.message || '本地分析未完成。');
        await new Promise((resolve) => window.setTimeout(resolve, 900));
      }
    };
    document.querySelector('#open-task-dialog').addEventListener('click', () => dialog.showModal());
    document.querySelector('#close-task-dialog').addEventListener('click', () => dialog.close());
    document.querySelector('#cancel-task-dialog').addEventListener('click', () => dialog.close());
    fileInput.addEventListener('change', () => {
      uploadTitle.textContent = fileInput.files[0]?.name || '选择 Word、PDF、Excel、CSV、TXT 或 MD';
      uploadStatus.textContent = fileInput.files[0] ? `${(fileInput.files[0].size / 1024 / 1024).toFixed(2)} MB · 准备在本机解析` : '最大 20MB，扫描 PDF 自动使用 Windows 本地 OCR';
      uploadStatus.classList.remove('is-error');
      renderClassificationPreview();
    });
    comparisonFileInput?.addEventListener('change', () => {
      const files = [...(comparisonFileInput.files || [])];
      if (comparisonFileStatus) {
        comparisonFileStatus.textContent = files.length
          ? `已选择 ${files.length} 份对比文件：${files.map((file) => file.name).join('、')}`
          : '可同时选择最多 8 份对比文件；系统会分别读取每份文档，XLS/XLSX/CSV 全部参与财务勾稽，其他文档逐份进行摘要/全文和事实对比。';
        comparisonFileStatus.classList.toggle('is-error', files.length > 8);
      }
    });
    taskTypeSelect.addEventListener('change', renderClassificationPreview);
    rulePackSelect.addEventListener('change', renderClassificationPreview);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      const formData = new FormData(form);
      const comparisonFiles = [...(comparisonFileInput?.files || [])];
      if (comparisonFiles.length > 8) {
        if (comparisonFileStatus) {
          comparisonFileStatus.textContent = '最多可添加 8 份对比文件。';
          comparisonFileStatus.classList.add('is-error');
        }
        return;
      }
      // Rebuild the repeated multipart field explicitly.  FormData(form)
      // already contains the selected files in most browsers; deleting first
      // avoids sending every comparison file twice.
      formData.delete('comparison_document');
      for (const file of comparisonFiles) {
        formData.append('comparison_document', file, file.name);
      }
      submitButton.disabled = true;
      submitLabel.textContent = '正在处理...';
      uploadStatus.textContent = '文件正在本机处理，可以查看下方实时进度';
      uploadStatus.classList.remove('is-error');
      updateProgress({ stage: 'queued', status: 'processing', progress: 1, message: '正在上传文件。', completedItems: 0, totalItems: 0 });

      try {
        let result;
        if (platformState.connected) {
          const job = await apiFetch('/api/tasks', { method: 'POST', body: formData });
          updateProgress(job);
          result = await waitForAnalysis(job.jobId);
        } else {
          let response;
          try {
            response = await fetch('/api/analyze', { method: 'POST', body: formData });
          } catch (error) {
            if (error instanceof TypeError) throw new Error('无法连接本地审查服务，请重新运行 Windows 启动器后刷新页面。');
            throw error;
          }
          const job = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(job.error || '本地解析服务未返回有效结果。');
          updateProgress(job);
          result = await waitForAnalysis(job.jobId);
        }

        const task = {
          id: result.taskId || `XS-${Date.now()}`,
          name: formData.get('taskName') || (fileInput.files[0]?.name || '审查任务').replace(/\.[^.]+$/, ''),
          file: result.filename || fileInput.files[0]?.name || '待审文档',
          type: result.taskType || formData.get('taskType'),
          status: 'review',
          risks: result.summary?.total || 0,
          owner: platformState.user?.display_name || '本机用户',
          updatedAt: new Date().toISOString()
        };
        if (platformState.connected) {
          platformState.tasks = [task, ...platformState.tasks.filter((item) => item.id !== task.id)];
        } else {
          const customTasks = readJson(storageKeys.tasks, []);
          customTasks.unshift(task);
          writeJson(storageKeys.tasks, customTasks);
        }
        latestAnalysisState = { task, result };
        writeSessionJson(storageKeys.latestAnalysis, latestAnalysisState);

        form.reset();
        renderClassificationPreview();
        if (comparisonFileStatus) {
          comparisonFileStatus.textContent = '可同时选择最多 8 份对比文件；系统会分别读取每份文档，XLS/XLSX/CSV 全部参与财务勾稽，其他文档逐份进行摘要/全文和事实对比。';
          comparisonFileStatus.classList.remove('is-error');
        }
        uploadTitle.textContent = '选择 Word、PDF、Excel、CSV、TXT 或 MD';
        uploadStatus.textContent = '最大 20MB，扫描 PDF 自动使用 Windows 本地 OCR';
        progressPanel.hidden = true;
        dialog.close();
        taskFilter = 'all';
        document.querySelectorAll('[data-task-filter]').forEach((item) => item.classList.toggle('is-active', item.dataset.taskFilter === 'all'));
        renderTasks();
        renderUploadedReview(result, task);
        showView('review');
        const ocrNote = result.ocrUsed ? `，本地 OCR ${result.ocrPages.length} 页` : '';
        const classificationNote = result.classification?.method === 'automatic'
          ? `，已自动采用${result.taskType}`
          : '';
        showToast(`审查完成：发现 ${result.summary.total} 项待复核内容${ocrNote}${classificationNote}`);
      } catch (error) {
        uploadStatus.textContent = error.message;
        uploadStatus.classList.add('is-error');
        progressPanel.classList.add('is-failed');
        progressStage.textContent = '处理失败';
        progressMessage.textContent = error.message;
      } finally {
        submitButton.disabled = false;
        submitLabel.textContent = '创建并开始审查';
      }
    });
  }

  function getSeverityMeta(severity) {
    if (severity === 'high') return { label: '高风险', chipClass: 'high', inlineClass: 'high' };
    if (severity === 'medium') return { label: '中风险', chipClass: 'medium', inlineClass: 'medium' };
    return { label: '待确认', chipClass: 'neutral', inlineClass: 'medium' };
  }

  function renderEmptyReview() {
    clearOriginalDocumentPreview();
    resetSummaryComparisonPanel();
    reviewReaderMode = 'annotated';
    currentReviewTaskId = null;
    currentReviewDocument = null;
    selectedRiskId = null;
    risks = {};
    resolvedRisks.clear();
    document.querySelector('#review-task-label').textContent = '审查工作台';
    document.querySelector('#review-file-name').textContent = '尚未选择审查任务';
    document.querySelector('#review-classification-meta').textContent = '审查类型与规则包将在打开任务后显示';
    document.querySelector('#review-status').innerHTML = '<i data-lucide="circle-dashed" aria-hidden="true"></i>等待任务';
    document.querySelector('#review-page-count').textContent = '0 页';
    document.querySelector('#review-reader-meta').textContent = '从审查任务中心打开文档';
    document.querySelector('#review-outline').innerHTML = '<button type="button" class="is-active"><i data-lucide="file-text" aria-hidden="true"></i>等待文档</button>';
    document.querySelector('#review-document-paper').innerHTML = '<div class="review-empty-result"><i data-lucide="file-search-2" aria-hidden="true"></i><strong>请选择一项审查任务</strong><span>上传新材料或从“审查任务”中打开历史任务后，可在此定位原文和处理风险。</span></div>';
    setReviewReaderMode('annotated');
    document.querySelector('#risk-list').innerHTML = '<div class="review-empty-result"><i data-lucide="shield-check" aria-hidden="true"></i><strong>暂无审阅结果</strong></div>';
    document.querySelector('#pending-risk-count').textContent = '0';
    document.querySelector('#risk-high-count').textContent = '高 0';
    document.querySelector('#risk-medium-count').textContent = '中 0';
    document.querySelector('#risk-review-count').textContent = '待确认 0';
    document.querySelector('#risk-reason').textContent = '打开任务后显示风险说明。';
    document.querySelector('#risk-financial-change-group').hidden = true;
    document.querySelector('#risk-financial-change').innerHTML = '';
    document.querySelector('#risk-evidence').innerHTML = '<strong>暂无检索来源</strong><small>每项风险必须关联可核验来源。</small>';
    document.querySelector('#risk-suggestion').textContent = '人工复核操作将在选择风险后启用。';
    document.querySelectorAll('#confirm-risk, #ignore-risk, #note-risk, #undo-risk').forEach((button) => { button.disabled = true; });
    document.querySelector('#undo-risk').hidden = true;
    renderAssistantMessages([]);
    refreshIcons();
  }

  function getRiskStatusMeta(status, severity) {
    const reviewed = {
      confirmed: ['已确认', 'success'],
      false_positive: ['误报', 'neutral'],
      needs_material: ['补充材料', 'medium'],
      resolved: ['已完成', 'success']
    }[status];
    if (reviewed) return { label: reviewed[0], chipClass: reviewed[1] };
    return getSeverityMeta(severity);
  }

  function updateRiskCounters() {
    const values = Object.values(risks);
    const pending = values.filter((risk) => !risk.status || risk.status === 'pending');
    document.querySelector('#pending-risk-count').textContent = pending.length;
    document.querySelector('#risk-review-count').textContent = `待确认 ${pending.filter((risk) => risk.severity === 'needs_review').length}`;
  }

  function updateRiskActions() {
    const risk = selectedRiskId ? risks[selectedRiskId] : null;
    const pending = Boolean(risk) && (!risk.status || risk.status === 'pending');
    document.querySelector('#confirm-risk').disabled = !pending;
    document.querySelector('#ignore-risk').disabled = !pending;
    document.querySelector('#note-risk').disabled = !risk;
    const undoButton = document.querySelector('#undo-risk');
    undoButton.hidden = !risk || pending;
    undoButton.disabled = !risk || pending;
    if (!risk || pending) return;
    const labels = {
      confirmed: '撤销确认',
      false_positive: '撤销误报',
      needs_material: '撤销补充材料',
      resolved: '撤销完成'
    };
    undoButton.innerHTML = `<i data-lucide="rotate-ccw" aria-hidden="true"></i>${labels[risk.status] || '撤销处理'}`;
  }

  function renderParagraphWithRisks(text, paragraphRisks) {
    const intervals = paragraphRisks.map((risk) => {
      const needle = String(risk.sourceText || '').replace(/^\.\.\.|\.\.\.$/g, '');
      const start = needle ? text.indexOf(needle) : -1;
      return { risk, start, end: start >= 0 ? start + needle.length : -1 };
    }).filter((item) => item.start >= 0).sort((left, right) => left.start - right.start);

    if (!intervals.length) return restoreLegacyDocxCheckboxes(escapeHtml(text));
    let cursor = 0;
    let html = '';
    for (const interval of intervals) {
      if (interval.start < cursor) continue;
      const severity = getSeverityMeta(interval.risk.severity);
      html += escapeHtml(text.slice(cursor, interval.start));
      html += `<button type="button" class="inline-risk ${severity.inlineClass}" data-risk-id="${escapeHtml(interval.risk.id)}">${escapeHtml(text.slice(interval.start, interval.end))}</button>`;
      cursor = interval.end;
    }
    return restoreLegacyDocxCheckboxes(html + escapeHtml(text.slice(cursor)));
  }

  function restoreLegacyDocxCheckboxes(html) {
    const value = String(html || '');
    const plainValue = value.replace(/<[^>]*>/g, '');
    const hasExplicitEmptyPair = /□\s*(?:适用|是)\s*□\s*(?:不适用|否)/.test(plainValue);
    if (value.includes('☑') || hasExplicitEmptyPair) return value;
    return value
      .replaceAll('□适用 不适用', '□适用 <span class="document-checkbox checked" aria-label="已选择">☑</span>不适用')
      .replaceAll('适用 □不适用', '<span class="document-checkbox checked" aria-label="已选择">☑</span>适用 □不适用')
      .replaceAll('□是 否', '□是 <span class="document-checkbox checked" aria-label="已选择">☑</span>否')
      .replaceAll('是 □否', '<span class="document-checkbox checked" aria-label="已选择">☑</span>是 □否');
  }

  function renderDocumentTable(text, paragraphRisks) {
    const rows = String(text || '')
      .split(/\r?\n/)
      .map((row) => row.split('|').map((cell) => cell.trim()))
      .filter((row) => row.some(Boolean));
    if (!rows.length) return '<p class="document-table-empty">表格中没有可显示的文字。</p>';
    const columnCount = Math.max(...rows.map((row) => row.length));
    const normalizeRow = (row) => [...row, ...Array(Math.max(0, columnCount - row.length)).fill('')];
    const renderCells = (row, tag) => normalizeRow(row).map((cell) => {
      const content = renderParagraphWithRisks(cell, paragraphRisks);
      const isNegativeNumber = /^[\-−－]\s*\d[\d,]*(?:\.\d+)?(?:%|元|万元)?$/.test(cell);
      const visibleContent = content || '<span aria-hidden="true">&nbsp;</span>';
      return `<${tag}>${isNegativeNumber ? `<span class="document-negative-number" title="负数">${visibleContent}</span>` : visibleContent}</${tag}>`;
    }).join('');
    const [header, ...body] = rows;
    return `<div class="document-table-wrap" role="region" aria-label="文档表格" tabindex="0">
      <table class="document-content-table" style="--document-table-columns:${columnCount}">
        <thead><tr>${renderCells(header, 'th')}</tr></thead>
        ${body.length ? `<tbody>${body.map((row) => `<tr>${renderCells(row, 'td')}</tr>`).join('')}</tbody>` : ''}
      </table>
    </div>`;
  }

  function clearOriginalDocumentPreview() {
    if (originalDocumentUrl) URL.revokeObjectURL(originalDocumentUrl);
    originalDocumentUrl = '';
    originalDocumentFilename = '';
    originalDocumentPage = null;
    originalDocumentPreview = null;
    const frame = document.querySelector('#review-original-frame');
    const structure = document.querySelector('#review-original-structure');
    const placeholder = document.querySelector('#review-original-placeholder');
    if (frame) {
      frame.removeAttribute('src');
      frame.hidden = true;
    }
    if (structure) {
      structure.hidden = true;
      structure.replaceChildren();
    }
    if (placeholder) {
      placeholder.hidden = false;
      placeholder.innerHTML = '<i data-lucide="file-check-2" aria-hidden="true"></i><strong>原始文件尚未打开</strong><span>切换到“原始文件”后，系统将直接读取上传的原件。原件是最终审批依据，解析标注仅用于定位问题。</span>';
    }
  }

  function originalDocumentSuffix() {
    return String(originalDocumentFilename || '').toLowerCase().split('.').pop() || '';
  }

  function renderOriginalDocumentPlaceholder(message, linkLabel = '') {
    const placeholder = document.querySelector('#review-original-placeholder');
    const frame = document.querySelector('#review-original-frame');
    const structure = document.querySelector('#review-original-structure');
    if (!placeholder || !frame || !structure) return;
    frame.hidden = true;
    frame.removeAttribute('src');
    structure.hidden = true;
    structure.replaceChildren();
    placeholder.hidden = false;
    const link = originalDocumentUrl && linkLabel
      ? `<a href="${escapeHtml(originalDocumentUrl)}" target="_blank" rel="noreferrer" download="${escapeHtml(originalDocumentFilename)}"><i data-lucide="external-link" aria-hidden="true"></i>${escapeHtml(linkLabel)}</a>`
      : '';
    placeholder.innerHTML = `<i data-lucide="file-check-2" aria-hidden="true"></i><strong>原始文件已保留</strong><span>${escapeHtml(message)}</span>${link}`;
    refreshIcons();
  }

  function renderOriginalStructuredPreview(preview) {
    const placeholder = document.querySelector('#review-original-placeholder');
    const frame = document.querySelector('#review-original-frame');
    const structure = document.querySelector('#review-original-structure');
    if (!placeholder || !frame || !structure) return;
    const blocks = Array.isArray(preview.blocks) ? preview.blocks : [];
    const tableCount = Number(preview.tableCount || blocks.filter((block) => String(block.blockType || '').toLowerCase() === 'table').length);
    const content = blocks.map((block, index) => {
      const text = String(block.text || '');
      const paragraphIndex = Number.isInteger(Number(block.paragraphIndex)) ? Number(block.paragraphIndex) : index;
      const location = `data-page="${escapeHtml(block.page || '')}" data-section="${escapeHtml(block.section || '')}" data-paragraph-index="${paragraphIndex}"`;
      if (String(block.blockType || '').toLowerCase() === 'table') {
        return `<div class="document-table-block" id="original-preview-block-${index}" ${location}>${renderDocumentTable(text, [])}</div>`;
      }
      if (String(block.blockType || '').toLowerCase() === 'heading' || index === 0) {
        return `<h4 id="original-preview-block-${index}" ${location}>${escapeHtml(text)}</h4>`;
      }
      return `<p id="original-preview-block-${index}" ${location}>${escapeHtml(text)}</p>`;
    }).join('');
    const sourceLink = originalDocumentUrl
      ? `<a class="original-source-link" href="${escapeHtml(originalDocumentUrl)}" target="_blank" rel="noreferrer" download="${escapeHtml(originalDocumentFilename)}"><i data-lucide="external-link" aria-hidden="true"></i>打开 / 下载原文件</a>`
      : '';
    const sourceLabel = String(preview.fileType || '').toUpperCase() === 'XLS' || String(preview.fileType || '').toUpperCase() === 'XLSX' ? '工作表和数据直接从本机 Excel 原件重新读取' : '表格和正文直接从本机原件重新读取';
    structure.innerHTML = `<div class="original-preview-banner"><span><strong>原件内容审批视图 · 已读取 ${blocks.length.toLocaleString('zh-CN')} 个内容块 / ${tableCount.toLocaleString('zh-CN')} 张表格</strong>${sourceLabel}；精确分页、合并单元格和最终版式以原件为准。</span>${sourceLink}</div>
      <article class="original-preview-paper"><h3>${escapeHtml(preview.title || originalDocumentFilename)}</h3>${content || '<p>未从原件提取到可显示内容。</p>'}</article>`;
    originalDocumentPreview = preview;
    document.querySelector('#review-reader-meta').textContent = `Word 原件 · ${blocks.length.toLocaleString('zh-CN')} 个内容块 · ${tableCount.toLocaleString('zh-CN')} 张表格`;
    frame.hidden = true;
    frame.removeAttribute('src');
    placeholder.hidden = true;
    structure.hidden = false;
    refreshIcons();
  }

  function renderKnowledgePreview(preview) {
    const body = document.querySelector('#knowledge-preview-body');
    if (!body) return;
    const blocks = Array.isArray(preview.blocks) ? preview.blocks : [];
    const tableCount = Number(preview.tableCount || blocks.filter((block) => String(block.blockType || '').toLowerCase() === 'table').length);
    const content = blocks.map((block, index) => {
      const text = String(block.text || '');
      const location = [
        block.page ? `第 ${escapeHtml(block.page)} 页` : '',
        block.sheetName ? `工作表：${escapeHtml(block.sheetName)}` : '',
        Array.isArray(block.sourceRowNumbers) && block.sourceRowNumbers.length
          ? `Excel 行 ${escapeHtml(block.sourceRowNumbers.join('、'))}` : '',
      ].filter(Boolean).join(' · ');
      const locationMarkup = location ? `<small class="knowledge-preview-location">${location}</small>` : '';
      if (String(block.blockType || '').toLowerCase() === 'table') {
        return `<div class="document-table-block knowledge-preview-block">${locationMarkup}${renderDocumentTable(text, [])}</div>`;
      }
      if (String(block.blockType || '').toLowerCase() === 'heading' || index === 0) {
        return `<h4 class="knowledge-preview-block">${escapeHtml(text)}${locationMarkup}</h4>`;
      }
      return `<p class="knowledge-preview-block">${escapeHtml(text)}${locationMarkup}</p>`;
    }).join('');
    body.innerHTML = `<div class="knowledge-preview-summary"><strong>已读取原文件内容</strong><span>${escapeHtml(preview.filename || '')} · ${blocks.length.toLocaleString('zh-CN')} 个内容块 · ${tableCount.toLocaleString('zh-CN')} 张表格${preview.ocrUsed ? ' · 已使用本地 OCR' : ''}</span></div><article class="original-preview-paper knowledge-preview-paper"><h3>${escapeHtml(preview.title || preview.filename || '资料原文')}</h3>${content || '<p>未从原文件提取到可显示内容。</p>'}</article>`;
    body.scrollTop = 0;
    refreshIcons();
  }

  async function openKnowledgePreview(documentId) {
    const dialog = document.querySelector('#knowledge-preview-dialog');
    const body = document.querySelector('#knowledge-preview-body');
    const title = document.querySelector('#knowledge-preview-title');
    const meta = document.querySelector('#knowledge-preview-meta');
    const download = document.querySelector('#knowledge-preview-download');
    if (!dialog || !body) return;
    title.textContent = '资料原文预览';
    meta.textContent = '正在从本机读取原文件内容';
    body.innerHTML = '<div class="review-empty-result"><i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在读取原文件</strong></div>';
    dialog.showModal();
    refreshIcons();
    try {
      const preview = await apiFetch(`/api/knowledge/${encodeURIComponent(documentId)}/preview`);
      title.textContent = preview.title || preview.filename || '资料原文预览';
      meta.textContent = `${preview.fileType || '文档'} · 更新时间 ${formatDataTimestamp(preview.updatedAt)}`;
      download.href = `/api/knowledge/${encodeURIComponent(documentId)}/document`;
      renderKnowledgePreview(preview);
    } catch (error) {
      body.innerHTML = `<div class="review-empty-result"><i data-lucide="file-warning" aria-hidden="true"></i><strong>原文件读取失败</strong><span>${escapeHtml(error.message || '请稍后重试，或下载原文件后查看。')}</span></div>`;
      refreshIcons();
    }
  }

  async function ensureOriginalDocumentLoaded() {
    if (originalDocumentUrl) return;
    if (!platformState.connected || !currentReviewTaskId) {
      renderOriginalDocumentPlaceholder('请先打开一项真实审查任务。');
      return;
    }
    try {
      const response = await fetch(`/api/tasks/${encodeURIComponent(currentReviewTaskId)}/document`, { credentials: 'same-origin' });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || '原始文件读取失败。');
      }
      const task = platformState.tasks.find((item) => item.id === currentReviewTaskId);
      originalDocumentFilename = task?.file || document.querySelector('#review-file-name')?.textContent || '审查原文';
      originalDocumentUrl = URL.createObjectURL(await response.blob());
      const suffix = originalDocumentSuffix();
      if (suffix === 'pdf' || ['txt', 'csv', 'md', 'json', 'html', 'htm'].includes(suffix)) {
        const frame = document.querySelector('#review-original-frame');
        const placeholder = document.querySelector('#review-original-placeholder');
        frame.hidden = false;
        placeholder.hidden = true;
        frame.src = originalDocumentUrl + (suffix === 'pdf' && originalDocumentPage ? `#page=${originalDocumentPage}` : '');
      } else if (['docx', 'doc', 'xlsx', 'xls'].includes(suffix)) {
        const preview = await apiFetch(`/api/tasks/${encodeURIComponent(currentReviewTaskId)}/document-preview`);
        renderOriginalStructuredPreview(preview);
      } else {
        renderOriginalDocumentPlaceholder(
          '原文件已保留。当前浏览器无法直接还原该格式的版式，请下载原文件进行最终审批；解析视图仅用于定位风险。',
          '打开 / 下载原文件',
        );
      }
      showToast('已加载原始文件，原件未被改写');
    } catch (error) {
      renderOriginalDocumentPlaceholder(error.message || '原始文件读取失败，请下载原件后审批。');
      showToast(error.message || '原始文件读取失败。');
    }
  }

  function locateOriginalPage(page) {
    const numericPage = Number(page);
    if (!Number.isInteger(numericPage) || numericPage < 1) return;
    originalDocumentPage = numericPage;
    if (!originalDocumentUrl) {
      ensureOriginalDocumentLoaded().then(() => locateOriginalPage(numericPage)).catch(() => {});
      return;
    }
    const suffix = originalDocumentSuffix();
    const frame = document.querySelector('#review-original-frame');
    if (frame && suffix === 'pdf') frame.src = `${originalDocumentUrl}#page=${numericPage}`;
    document.querySelector('#review-reader-meta').textContent = `原始文件 · 第 ${numericPage} 页`;
  }

  function locateOriginalRisk(risk, requestedLocation = null) {
    const location = requestedLocation || getRiskOriginalLocations(risk)[0] || {};
    const suffix = originalDocumentSuffix();
    if (suffix === 'pdf') {
      const page = Number(location.page || risk.page);
      if (Number.isInteger(page) && page > 0) locateOriginalPage(page);
      return;
    }
    if (!originalDocumentPreview) {
      ensureOriginalDocumentLoaded().then(() => locateOriginalRisk(risk, location)).catch(() => {});
      return;
    }
    const sourceText = String(location.text || risk.sourceText || risk.original || risk.evidence || '').trim();
    const needle = sourceText.split(/\r?\n/).find((line) => line.trim())?.trim().slice(0, 80) || '';
    let paragraphIndex = Number.isInteger(location.paragraphIndex) ? location.paragraphIndex : -1;
    if (paragraphIndex < 0 && needle) {
      const matchedBlock = (originalDocumentPreview.blocks || []).find((block) => String(block.text || '').includes(needle));
      if (matchedBlock && Number.isInteger(Number(matchedBlock.paragraphIndex))) {
        paragraphIndex = Number(matchedBlock.paragraphIndex);
      }
    }
    if (paragraphIndex < 0 && Number.isInteger(risk.paragraphIndex)) paragraphIndex = risk.paragraphIndex;
    let target = document.querySelector(`#review-original-structure [data-paragraph-index="${paragraphIndex}"]`);
    if (!target && needle) {
      const blockIndex = (originalDocumentPreview.blocks || []).findIndex((block) => String(block.text || '').includes(needle));
      if (blockIndex >= 0) target = document.querySelector(`#original-preview-block-${blockIndex}`);
    }
    const scroller = document.querySelector('#review-original-structure');
    if (!target || !scroller) return;
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    document.querySelectorAll('#review-original-structure .document-location-target').forEach((element) => element.classList.remove('document-location-target'));
    target.classList.add('document-location-target');
    window.setTimeout(() => target.classList.remove('document-location-target'), 1800);
    const page = target.dataset.page ? `第 ${target.dataset.page} 页` : '';
    document.querySelector('#review-reader-meta').textContent = [
      'Word 原件内容', location.label || '', page, target.dataset.section || '', `第 ${paragraphIndex + 1} 个内容块`
    ].filter(Boolean).join(' · ');
  }

  function setReviewReaderMode(mode) {
    reviewReaderMode = mode === 'original' ? 'original' : 'annotated';
    document.querySelectorAll('[data-reader-mode]').forEach((button) => {
      const active = button.dataset.readerMode === reviewReaderMode;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', String(active));
    });
    const paperWrap = document.querySelector('.paper-wrap');
    const originalWrap = document.querySelector('#review-original-file');
    if (paperWrap) paperWrap.hidden = reviewReaderMode === 'original';
    if (originalWrap) originalWrap.hidden = reviewReaderMode !== 'original';
    if (reviewReaderMode === 'original') ensureOriginalDocumentLoaded();
    else if (currentReviewDocument) {
      const meta = document.querySelector('#review-reader-meta');
      if (meta) meta.textContent = `${currentReviewDocument.paragraphs.length} 段 · 原始文件未被修改`;
    }
    refreshIcons();
  }

  let summaryComparisonRenderToken = 0;

  function comparisonDocumentBlocks(source) {
    const blocks = Array.isArray(source?.blocks) ? source.blocks : [];
    if (blocks.length) return blocks;
    return (Array.isArray(source?.paragraphs) ? source.paragraphs : []).map((text, paragraphIndex) => ({
      text,
      paragraphIndex,
      blockType: 'paragraph',
      page: null,
      section: '',
      sheetName: '',
      sourceRowNumbers: [],
    }));
  }

  function comparisonSideForDocument(documentId, summaryComparison) {
    const id = String(documentId || '');
    if (id && id === String(summaryComparison.summaryDocumentId || '')) return 'summary';
    if (id && id === String(summaryComparison.originalDocumentId || '')) return 'original';
    return '';
  }

  function comparisonLocationItems(risk, summaryComparison) {
    const supplied = getRiskOriginalLocations(risk);
    return supplied.map((location, index) => ({
      ...location,
      side: comparisonSideForDocument(location.documentId, summaryComparison) || (index === 0 ? 'summary' : 'original'),
    }));
  }

  function renderComparisonDocumentBody(source, side, summaryComparison, highlightedParagraphs = new Set()) {
    const blocks = comparisonDocumentBlocks(source);
    const title = source.title || source.filename || (side === 'summary' ? '摘要' : '完整报告原文');
    const content = blocks.map((block, index) => {
      const text = String(block.text || '');
      if (index === 0 && text.trim() && text.trim() === String(title).trim()) return '';
      const paragraphIndex = Number.isInteger(Number(block.paragraphIndex)) ? Number(block.paragraphIndex) : index;
      const blockId = `summary-comparison-${side}-block-${paragraphIndex}`;
      const location = [
        block.page ? `第 ${block.page} 页` : '',
        block.section || '',
        block.sheetName ? `工作表 ${block.sheetName}` : '',
        Array.isArray(block.sourceRowNumbers) && block.sourceRowNumbers.length ? `第 ${block.sourceRowNumbers.join('、')} 行` : '',
      ].filter(Boolean).join(' · ');
      const classes = ['summary-comparison-block'];
      if (highlightedParagraphs.has(paragraphIndex)) classes.push('is-comparison-target');
      const attrs = `id="${blockId}" data-comparison-paragraph="${paragraphIndex}" data-comparison-side="${side}"`;
      const locationMarkup = location ? `<small class="summary-comparison-location">${escapeHtml(location)}</small>` : '';
      const blockType = String(block.blockType || block.block_type || '').toLowerCase();
      if (blockType === 'table') {
        return `<div class="document-table-block ${classes.join(' ')}" ${attrs}>${renderDocumentTable(text, [])}${locationMarkup}</div>`;
      }
      const rendered = restoreLegacyDocxCheckboxes(escapeHtml(text));
      const tag = blockType === 'heading' || index === 0 ? 'h4' : 'p';
      return `<${tag} class="${classes.join(' ')}" ${attrs}>${rendered}${locationMarkup}</${tag}>`;
    }).join('');
    return `<article class="summary-comparison-paper"><h4 class="summary-comparison-document-title">${escapeHtml(title)}</h4>${content || '<p class="summary-comparison-empty">未从该文件提取到可显示内容。</p>'}</article>`;
  }

  function comparisonFindingMarkup(risk, summaryComparison) {
    const locations = comparisonLocationItems(risk, summaryComparison);
    const severity = getSeverityMeta(risk.severity || risk.level);
    const calculation = risk.calculation || {};
    const values = calculation.status === 'metric_mismatch'
      ? `<div class="summary-comparison-values"><span>摘要：${escapeHtml((calculation.summaryValues || []).join('、'))}</span><span>原文：${escapeHtml((calculation.originalValues || []).join('、'))}</span></div>`
      : calculation.status === 'fact_mismatch'
        ? `<div class="summary-comparison-values"><span>摘要：${escapeHtml(calculation.summaryValue || '')}</span><span>原文：${escapeHtml(calculation.originalValue || '')}</span></div>`
        : '';
    const jumps = locations.map((location, index) => {
      if (!Number.isInteger(location.paragraphIndex)) return '';
      const label = location.side === 'summary' ? '定位摘要' : '定位完整报告';
      return `<button type="button" class="summary-comparison-jump" data-comparison-side="${location.side}" data-comparison-paragraph="${location.paragraphIndex}"><i data-lucide="locate-fixed" aria-hidden="true"></i>${label}${location.page ? ` · 第 ${escapeHtml(location.page)} 页` : ''}</button>`;
    }).join('');
    return `<article class="summary-comparison-finding"><div class="summary-comparison-finding-head"><span class="status-chip ${severity.chipClass}">${escapeHtml(severity.label)}</span><strong>${escapeHtml(risk.title)}</strong></div><p>${escapeHtml(risk.description || risk.reason || '')}</p>${values}<div class="summary-comparison-finding-actions">${jumps}</div></article>`;
  }

  function resetSummaryComparisonPanel(message = '') {
    const panel = document.querySelector('#summary-comparison-panel');
    if (!panel) return;
    panel.hidden = true;
    const status = document.querySelector('#summary-comparison-status');
    const meta = document.querySelector('#summary-comparison-meta');
    if (status) {
      status.className = 'status-chip neutral';
      status.textContent = '未加载';
    }
    if (meta) meta.textContent = message || '等待加载对比结果';
    ['summary-comparison-findings', 'summary-comparison-multi-documents', 'summary-comparison-summary-body', 'summary-comparison-original-body'].forEach((id) => {
      const node = document.querySelector(`#${id}`);
      if (node) node.innerHTML = '';
    });
    const multiDocuments = document.querySelector('#summary-comparison-multi-documents');
    if (multiDocuments) multiDocuments.hidden = true;
    const legacyColumns = document.querySelector('.summary-comparison-columns');
    if (legacyColumns) legacyColumns.hidden = false;
  }

  function comparisonDocumentKey(index) {
    return `doc-${index}`;
  }

  function comparisonDocumentMeta(document) {
    const fileType = String(document.fileType || '文档').toUpperCase();
    const blocks = comparisonDocumentBlocks(document).length;
    const pageCount = Number(document.pageCount || 0);
    return `${fileType} · ${pageCount} 页 · ${blocks.toLocaleString('zh-CN')} 个内容块`;
  }

  function renderMultiComparisonFinding(risk, documentById, keyById) {
    const severity = getSeverityMeta(risk.severity || risk.level);
    const calculation = risk.calculation || {};
    const values = calculation.status === 'metric_mismatch'
      ? `<div class="summary-comparison-values"><span>摘要：${escapeHtml((calculation.summaryValues || []).join('、'))}</span><span>原文：${escapeHtml((calculation.originalValues || []).join('、'))}</span></div>`
      : calculation.status === 'fact_mismatch'
        ? `<div class="summary-comparison-values"><span>摘要：${escapeHtml(calculation.summaryValue || '')}</span><span>原文：${escapeHtml(calculation.originalValue || '')}</span></div>`
        : '';
    const jumps = getRiskOriginalLocations(risk).map((location, index) => {
      const documentId = String(location.documentId || '');
      const key = keyById.get(documentId) || (index === 0 ? keyById.get('__main__') : '');
      if (!key || !Number.isInteger(location.paragraphIndex)) return '';
      const document = documentById.get(documentId) || (key === keyById.get('__main__') ? documentById.get('__main__') : null);
      const label = document?.filename || (index === 0 ? '主文档' : '对比文档');
      return `<button type="button" class="summary-comparison-jump" data-comparison-key="${escapeHtml(key)}" data-comparison-paragraph="${location.paragraphIndex}"><i data-lucide="locate-fixed" aria-hidden="true"></i>${escapeHtml(label)}${location.page ? ` · 第 ${escapeHtml(location.page)} 页` : ''}</button>`;
    }).join('');
    return `<article class="summary-comparison-finding"><div class="summary-comparison-finding-head"><span class="status-chip ${severity.chipClass}">${escapeHtml(severity.label)}</span><strong>${escapeHtml(risk.title)}</strong></div><p>${escapeHtml(risk.description || risk.reason || '')}</p>${values}<div class="summary-comparison-finding-actions">${jumps || '<span class="summary-comparison-no-location">未保存可定位段落</span>'}</div></article>`;
  }

  async function renderSummaryComparison(result, task) {
    const panel = document.querySelector('#summary-comparison-panel');
    if (!panel) return;
    const summaryComparison = result.summaryComparison || {};
    const comparisonDocuments = Array.isArray(result.comparisonDocuments) ? result.comparisonDocuments : [];
    const token = ++summaryComparisonRenderToken;
    resetSummaryComparisonPanel();
    if (!comparisonDocuments.length) return;
    panel.hidden = false;
    const status = document.querySelector('#summary-comparison-status');
    const meta = document.querySelector('#summary-comparison-meta');
    const findingsNode = document.querySelector('#summary-comparison-findings');
    const summaryBody = document.querySelector('#summary-comparison-summary-body');
    const originalBody = document.querySelector('#summary-comparison-original-body');
    const summaryName = document.querySelector('#summary-comparison-summary-name');
    const originalName = document.querySelector('#summary-comparison-original-name');
    const summaryMeta = document.querySelector('#summary-comparison-summary-meta');
    const originalMeta = document.querySelector('#summary-comparison-original-meta');
    status.className = 'status-chip neutral';
    status.textContent = '读取中';
    meta.textContent = '正在分别读取摘要和完整报告原文；两栏可独立滚动。';
    summaryBody.innerHTML = '<div class="review-empty-result"><i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在读取摘要</strong></div>';
    originalBody.innerHTML = '<div class="review-empty-result"><i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在读取完整报告</strong></div>';
    refreshIcons();

    const mainDocument = {
      documentId: result.documentId,
      filename: result.filename,
      fileType: result.fileType,
      title: result.title,
      pageCount: result.pageCount,
      paragraphCount: result.paragraphCount,
      blocks: result.blocks,
      paragraphs: result.paragraphs,
    };
    const related = comparisonDocuments.find((item) => item.documentId);
    if (!related?.documentId) {
      status.className = 'status-chip high';
      status.textContent = '对比文件不可用';
      meta.textContent = '对比文件已记录但没有可读取的文件标识。';
      summaryBody.innerHTML = '<div class="review-empty-result"><strong>对比文件未保存</strong></div>';
      originalBody.innerHTML = '<div class="review-empty-result"><strong>对比文件未保存</strong></div>';
      return;
    }
    const loadedComparisonDocuments = await Promise.all(comparisonDocuments.map(async (item) => {
      if (!item.documentId) return { ...item, _previewError: '文件标识缺失。' };
      try {
        return await apiFetch(`/api/tasks/${encodeURIComponent(task.id)}/documents/${encodeURIComponent(item.documentId)}/preview`);
      } catch (error) {
        return { ...item, _previewError: error.message || '对比文件读取失败。' };
      }
    }));
    if (token !== summaryComparisonRenderToken) return;
    const allDocuments = [mainDocument, ...loadedComparisonDocuments];
    const isMultiDocument = allDocuments.length > 2 || summaryComparison.multi || !summaryComparison.status;
    if (isMultiDocument) {
      const multiDocuments = document.querySelector('#summary-comparison-multi-documents');
      const legacyColumns = document.querySelector('.summary-comparison-columns');
      if (!multiDocuments) return;
      if (legacyColumns) legacyColumns.hidden = true;
      multiDocuments.hidden = false;
      const documentById = new Map([['__main__', mainDocument], ...allDocuments.filter((item) => item.documentId).map((item) => [String(item.documentId), item])]);
      const keyById = new Map([['__main__', comparisonDocumentKey(0)], ...allDocuments.map((item, index) => [String(item.documentId || `__index_${index}`), comparisonDocumentKey(index)])]);
      const findingRisks = (result.risks || []).filter((risk) => String(risk.type || risk.category || '').includes('摘要') || String(risk.title || '').startsWith('摘要与原文'));
      const highlighted = new Map(allDocuments.map((item, index) => [comparisonDocumentKey(index), new Set()]));
      findingRisks.forEach((risk) => getRiskOriginalLocations(risk).forEach((location, locationIndex) => {
        const key = keyById.get(String(location.documentId || '')) || (locationIndex === 0 ? comparisonDocumentKey(0) : '');
        if (key && Number.isInteger(location.paragraphIndex)) highlighted.get(key)?.add(location.paragraphIndex);
      }));
      multiDocuments.innerHTML = allDocuments.map((document, index) => {
        const key = comparisonDocumentKey(index);
        const title = document.filename || document.title || (index === 0 ? '主审查文档' : `对比文档 ${index}`);
        const icon = /\.(?:xls|xlsx|csv)$/i.test(title) ? 'file-spreadsheet' : 'file-text';
        const error = document._previewError ? `<div class="review-empty-result"><strong>无法读取原文</strong><span>${escapeHtml(document._previewError)}</span></div>` : renderComparisonDocumentBody(document, key, summaryComparison, highlighted.get(key) || new Set());
        return `<article class="summary-comparison-document"><header><i data-lucide="${icon}" aria-hidden="true"></i><div><strong title="${escapeHtml(title)}">${escapeHtml(title)}</strong><small>${escapeHtml(comparisonDocumentMeta(document))}</small></div></header><div class="summary-comparison-scroll" id="summary-comparison-${key}-body">${error}</div></article>`;
      }).join('');
      const comparisonCompleted = summaryComparison.status === 'completed';
      const mismatchCount = Number(summaryComparison.mismatches || findingRisks.length || 0);
      status.className = `status-chip ${comparisonCompleted && mismatchCount ? 'high' : comparisonCompleted ? 'success' : 'neutral'}`;
      status.textContent = comparisonCompleted ? (mismatchCount ? `${mismatchCount} 项差异` : '核对一致') : '已读取对比文件';
      meta.textContent = comparisonCompleted
        ? `主文档与 ${loadedComparisonDocuments.length} 份对比文件已分别展示；点击差异按钮可定位到对应文件原文。`
        : `已读取主文档及 ${loadedComparisonDocuments.length} 份对比文件。XLS/XLSX/CSV 的财务勾稽结果请查看下方财务审计结果。`;
      if (findingRisks.length) {
        findingsNode.innerHTML = `<div class="summary-comparison-findings-head"><strong>差异清单</strong><span>${findingRisks.length} 项，需要人工确认</span></div>${findingRisks.map((risk) => renderMultiComparisonFinding(risk, documentById, keyById)).join('')}`;
      } else {
        findingsNode.innerHTML = '<div class="summary-comparison-no-findings"><i data-lucide="circle-check-big" aria-hidden="true"></i><strong>未发现摘要—原文差异</strong><span>各对比文件已单独展示；表格勾稽结果请查看财务审计区。</span></div>';
      }
      refreshIcons();
      return;
    }
    let relatedDocument = loadedComparisonDocuments[0];
    if (relatedDocument?._previewError) {
      if (token !== summaryComparisonRenderToken) return;
      status.className = 'status-chip high';
      status.textContent = '读取失败';
      meta.textContent = relatedDocument._previewError;
      summaryBody.innerHTML = '<div class="review-empty-result"><strong>无法读取摘要或完整报告</strong></div>';
      originalBody.innerHTML = '<div class="review-empty-result"><strong>无法读取摘要或完整报告</strong></div>';
      return;
    }
    if (token !== summaryComparisonRenderToken) return;
    const legacyDocuments = [mainDocument, relatedDocument];
    const documentBySide = { summary: null, original: null };
    legacyDocuments.forEach((document) => {
      const side = comparisonSideForDocument(document.documentId, summaryComparison)
        || (is_summary_filename(document.filename) ? 'summary' : 'original');
      if (!documentBySide[side]) documentBySide[side] = document;
    });
    // Older tasks may not have persisted document IDs in the comparison result.
    if (!documentBySide.summary || !documentBySide.original) {
      const fallback = legacyDocuments.filter((document) => !Object.values(documentBySide).includes(document));
      if (!documentBySide.summary) documentBySide.summary = fallback.shift() || legacyDocuments[0];
      if (!documentBySide.original) documentBySide.original = fallback.shift() || legacyDocuments[1] || legacyDocuments[0];
    }
    const findingRisks = (result.risks || []).filter((risk) => String(risk.type || risk.category || '').includes('摘要') || String(risk.title || '').startsWith('摘要与原文'));
    const highlighted = { summary: new Set(), original: new Set() };
    findingRisks.forEach((risk) => comparisonLocationItems(risk, summaryComparison).forEach((location) => {
      if (location.side && Number.isInteger(location.paragraphIndex)) highlighted[location.side].add(location.paragraphIndex);
    }));
    summaryBody.innerHTML = renderComparisonDocumentBody(documentBySide.summary, 'summary', summaryComparison, highlighted.summary);
    originalBody.innerHTML = renderComparisonDocumentBody(documentBySide.original, 'original', summaryComparison, highlighted.original);
    summaryName.textContent = documentBySide.summary.filename || summaryComparison.summaryDocument || '摘要';
    originalName.textContent = documentBySide.original.filename || summaryComparison.originalDocument || '完整报告原文';
    summaryMeta.textContent = `${documentBySide.summary.fileType || '文档'} · ${documentBySide.summary.pageCount || 0} 页 · ${comparisonDocumentBlocks(documentBySide.summary).length.toLocaleString('zh-CN')} 个内容块`;
    originalMeta.textContent = `${documentBySide.original.fileType || '文档'} · ${documentBySide.original.pageCount || 0} 页 · ${comparisonDocumentBlocks(documentBySide.original).length.toLocaleString('zh-CN')} 个内容块`;
    const comparisonCompleted = summaryComparison.status === 'completed';
    const mismatchCount = Number(summaryComparison.mismatches || findingRisks.length || 0);
    if (comparisonCompleted) {
      status.className = `status-chip ${mismatchCount ? 'high' : 'success'}`;
      status.textContent = mismatchCount ? `${mismatchCount} 项差异` : '核对一致';
      meta.textContent = `已核对 ${summaryComparison.checkedItems || 0} 项：${summaryComparison.summaryDocument || documentBySide.summary.filename || '摘要'} 与 ${summaryComparison.originalDocument || documentBySide.original.filename || '完整报告'}。点击差异下方按钮可分别定位两份原文。`;
      findingsNode.innerHTML = findingRisks.length
        ? `<div class="summary-comparison-findings-head"><strong>差异清单</strong><span>${findingRisks.length} 项，需要人工确认</span></div>${findingRisks.map((risk) => comparisonFindingMarkup(risk, summaryComparison)).join('')}`
        : '<div class="summary-comparison-no-findings"><i data-lucide="circle-check-big" aria-hidden="true"></i><strong>关键财务指标和基本信息未发现差异</strong><span>摘要主动省略的章节不会被当作错误。</span></div>';
    } else {
      status.className = 'status-chip medium';
      status.textContent = '未完成核对';
      meta.textContent = summaryComparison.message || '已展示两份文档，但未能唯一识别摘要与完整报告，未生成差异结论。';
      findingsNode.innerHTML = '<div class="summary-comparison-no-findings"><i data-lucide="triangle-alert" aria-hidden="true"></i><strong>未生成摘要—原文差异结论</strong><span>请确认上传文件分别为“报告摘要”和“完整报告”。</span></div>';
    }
    refreshIcons();
  }

  function is_summary_filename(filename) {
    return /摘要/.test(String(filename || ''));
  }

  function locateOutlineParagraph(paragraphIndex) {
    const index = Number(paragraphIndex);
    if (!Number.isInteger(index) || index < 0) return;
    if (reviewReaderMode !== 'original') {
      locateDocumentParagraph(index, 'start');
      return;
    }
    const block = (currentReviewDocument?.blocks || []).find((item) => Number(item.paragraphIndex) === index) || {};
    const location = { paragraphIndex: index, page: block.page, section: block.section, text: block.text || '' };
    if (originalDocumentSuffix() === 'pdf' && block.page) {
      locateOriginalPage(block.page);
      return;
    }
    locateOriginalRisk({ paragraphIndex: index, page: block.page, sourceText: block.text || '' }, location);
  }

  function renderUploadedReview(result, task) {
    clearOriginalDocumentPreview();
    reviewReaderMode = /\.(?:pdf|docx?)$/i.test(String(result.filename || task.file || '')) ? 'original' : 'annotated';
    currentReviewTaskId = task.id;
    currentReviewDocument = {
      id: result.documentId || null,
      paragraphs: result.paragraphs || [],
      blocks: result.blocks || [],
      headings: result.headings || []
    };
    risks = Object.fromEntries(result.risks.map((risk) => [risk.id, risk]));
    resolvedRisks.clear();
    result.risks.filter((risk) => risk.status && risk.status !== 'pending').forEach((risk) => resolvedRisks.add(risk.id));
    selectedRiskId = result.risks.find((risk) => risk.status === 'pending')?.id || result.risks[0]?.id || null;
    platformState.activeConversationId = null;

    document.querySelector('#review-task-label').textContent = `审查任务 · ${task.id}`;
    document.querySelector('#review-file-name').textContent = result.filename;
    const classification = result.classification || {};
    const classificationMethod = classification.method === 'automatic'
      ? '自动识别'
      : (classification.method === 'mixed' ? '自动与人工组合' : '人工选择');
    const confidenceText = Number.isFinite(Number(classification.confidence))
      ? ` · 识别置信度 ${Math.round(Number(classification.confidence) * 100)}%`
      : '';
    const reviewText = classification.needsReview ? ' · 建议人工确认适用范围' : '';
    const reasonText = Array.isArray(classification.reasons) && classification.reasons[0]
      ? ` · 依据：${classification.reasons[0]}`
      : '';
    const classificationMeta = document.querySelector('#review-classification-meta');
    classificationMeta.textContent = `${classificationMethod} · ${result.taskType} · ${result.rulePack}${confidenceText}${reviewText}${reasonText}`;
    classificationMeta.title = Array.isArray(classification.reasons) ? classification.reasons.join('；') : '';
    const modeLabel = result.analysisMode === 'cloud'
      ? (result.aiUsed ? 'AI 增强审阅完成' : '本地规则完成，AI 未调用')
      : (result.analysisMode === 'local_llm'
        ? (result.aiUsed ? '完全本地 AI 审阅完成' : '本地规则完成，本地 LLM 未调用')
        : '本地 RAG 与规则检查完成');
    document.querySelector('#review-status').innerHTML = `<i data-lucide="check-circle-2" aria-hidden="true"></i>${escapeHtml(modeLabel)}`;
    const coverage = result.ragCoverage || {};
    const periodComparison = result.periodComparison || {};
    const summaryComparison = result.summaryComparison || {};
    const castingReview = result.castingReview || {};
    const comparisonBaselines = Array.isArray(periodComparison.baselines) ? periodComparison.baselines : [];
    const coverageNode = document.querySelector('#review-rag-coverage');
    const narrativeText = Number(periodComparison.narrativeSectionsChecked) > 0
      ? `；文字章节 ${periodComparison.narrativeSectionsFound || 0}/${periodComparison.narrativeSectionsChecked} 类，内部文字冲突 ${periodComparison.narrativeInternalConflicts || 0} 项，历史重大变化待核验 ${periodComparison.narrativeHistoricalChanges || 0} 项`
      : '';
    const castingText = Number(castingReview.tablesScanned) > 0
      ? `；本地 Casting 扫描 ${castingReview.tablesScanned} 张表、复算 ${castingReview.checksPerformed || 0} 项、差异 ${castingReview.mismatches || 0} 项`
      : '';
    const summaryComparisonText = summaryComparison.status === 'completed'
      ? `；摘要—原文核对 ${summaryComparison.checkedItems || 0} 项，差异 ${summaryComparison.mismatches || 0} 项`
      : (summaryComparison.status === 'not_summary_pair' ? '；已提供对比文档，但未识别为摘要—原文文件对' : '');
    const comparisonText = comparisonBaselines.length
      ? `；历史报告核对 ${periodComparison.checkedItems || 0} 项，跨期差异 ${periodComparison.historicalMismatches ?? periodComparison.mismatches ?? 0} 项，本报告内部差异 ${periodComparison.internalMismatches ?? 0} 项${narrativeText}${summaryComparisonText}；对比原件：`
      : (periodComparison.status === 'missing_baseline' ? '；跨期对比：未找到可用官方基线正文' : '') + summaryComparisonText;
    if (Number(coverage.ruleChunksScanned) > 0) {
      const retrievalLabel = ({ keyword: '关键词', semantic: '语义向量', hybrid: '混合' })[coverage.retrievalMode] || coverage.retrievalMode || '本地';
      coverageNode.textContent = `本地 RAG：全部 ${new Intl.NumberFormat('zh-CN').format(coverage.ruleDocumentsScanned || 0)} 份有效法规 / ${new Intl.NumberFormat('zh-CN').format(coverage.ruleChunksScanned || 0)} 个已向量化 Chunk 参与${retrievalLabel}匹配；命中 ${coverage.matchedRuleDocuments || 0} 份，每项最多展示 Top ${coverage.topKPerRisk || 12}${castingText}${comparisonText}`;
    } else {
      coverageNode.textContent = Object.keys(coverage).length
        ? `本地 RAG：当前没有可参与匹配的已向量化法规 Chunk，请先由管理员完成法规正文入库和索引${castingText}${comparisonText}${comparisonBaselines.length ? '' : '。'}`
        : '历史任务未记录规则覆盖统计；重新上传审查后可查看全库匹配范围。';
    }
    comparisonBaselines.forEach((item, index) => {
      if (index > 0) coverageNode.append(document.createTextNode('、'));
      const url = safeOfficialUrl(item.sourceUrl || item.source_url || '');
      if (url === '#') {
        coverageNode.append(document.createTextNode(item.title || '上期报告'));
        return;
      }
      const link = document.createElement('a');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noreferrer';
      link.textContent = item.title || '上期报告';
      coverageNode.append(link);
    });
    document.querySelector('#review-page-count').textContent = `${result.pageCount} 页`;
    const ocrMeta = result.ocrUsed ? ` · 本地 OCR ${result.ocrPages.length} 页` : '';
    document.querySelector('#review-reader-meta').textContent = `${result.paragraphCount} 段 · ${new Intl.NumberFormat('zh-CN').format(result.characterCount)} 字${ocrMeta}`;

    const headingIndexes = new Set(result.headings.map((heading) => heading.paragraphIndex));
    const risksByParagraph = new Map();
    result.risks.forEach((risk) => {
      const paragraphIndexes = getRiskOriginalLocations(risk)
        .map((location) => location.paragraphIndex)
        .filter((paragraphIndex) => Number.isInteger(paragraphIndex));
      if (!paragraphIndexes.length && Number.isInteger(risk.paragraphIndex)) paragraphIndexes.push(risk.paragraphIndex);
      [...new Set(paragraphIndexes)].forEach((paragraphIndex) => {
        const values = risksByParagraph.get(paragraphIndex) || [];
        if (!values.some((item) => item.id === risk.id)) values.push(risk);
        risksByParagraph.set(paragraphIndex, values);
      });
    });

    const blocksByParagraph = new Map((result.blocks || []).map((block) => [Number(block.paragraphIndex), block]));
    const comparisonDocuments = Array.isArray(result.comparisonDocuments) ? result.comparisonDocuments : [];
    const comparisonMarkup = comparisonDocuments.length
      ? `<section class="comparison-document-note"><strong>已纳入勾稽对比</strong>${comparisonDocuments.map((item) => {
        const label = item.filename || '对比文件';
        const icon = /\.(?:xls|xlsx|csv)$/i.test(label) ? 'file-spreadsheet' : 'file-text';
        const url = item.documentId
          ? `/api/tasks/${encodeURIComponent(task.id)}/documents/${encodeURIComponent(item.documentId)}`
          : '';
        return url
          ? `<a href="${url}" target="_blank" rel="noreferrer" download="${escapeHtml(label)}"><i data-lucide="${icon}" aria-hidden="true"></i>${escapeHtml(label)}</a>`
          : `<span>${escapeHtml(label)}</span>`;
      }).join('')}</section>`
      : '';
    const documentHtml = result.paragraphs.map((paragraph, index) => {
      if (index === 0 && paragraph === result.title) return '';
      const block = blocksByParagraph.get(index) || {};
      const location = `data-page="${escapeHtml(block.page || '')}" data-section="${escapeHtml(block.section || '')}"`;
      const paragraphRisks = risksByParagraph.get(index) || [];
      const blockType = String(block.blockType || block.block_type || '').toLowerCase();
      if (blockType === 'table') {
        return `<div class="document-table-block" id="uploaded-paragraph-${index}" ${location}>${renderDocumentTable(paragraph, paragraphRisks)}</div>`;
      }
      const content = renderParagraphWithRisks(paragraph, paragraphRisks);
      return headingIndexes.has(index) || blockType === 'heading'
        ? `<h4 id="uploaded-paragraph-${index}" ${location}>${content}</h4>`
        : `<p id="uploaded-paragraph-${index}" ${location}>${content}</p>`;
    }).join('');
    const titleAnchorId = result.paragraphs[0] === result.title ? 'uploaded-paragraph-0' : 'uploaded-document-title';
    const titleBlock = blocksByParagraph.get(0) || {};
    document.querySelector('#review-document-paper').innerHTML = `
      <h3 id="${titleAnchorId}" data-page="${escapeHtml(titleBlock.page || '')}" data-section="${escapeHtml(titleBlock.section || '')}">${escapeHtml(result.title)}</h3>
      <p class="document-meta">${escapeHtml(result.fileType)} · ${new Intl.NumberFormat('zh-CN').format(result.paragraphCount)} 段 · ${escapeHtml(modeLabel)}</p>
      ${comparisonMarkup}
      ${documentHtml || '<p>未提取到其他正文段落。</p>'}
      <p class="paper-page-number">解析审阅视图 · 原始文件未被修改</p>`;
    setReviewReaderMode(reviewReaderMode);

    const outline = result.headings.length ? result.headings : [{ text: result.title, paragraphIndex: 0 }];
    document.querySelector('#review-outline').innerHTML = outline.map((heading, index) => `
      <button type="button" class="${index === 0 ? 'is-active' : ''}" data-scroll-paragraph="${heading.paragraphIndex}">
        <i data-lucide="${index === 0 ? 'file-text' : 'chevron-right'}" aria-hidden="true"></i>${escapeHtml(heading.text)}
      </button>`).join('');

    document.querySelector('#risk-list').innerHTML = result.risks.length ? result.risks.map((risk, index) => {
      const status = getRiskStatusMeta(risk.status, risk.severity);
      const active = risk.id === selectedRiskId ? 'is-active' : '';
      const resolved = risk.status && risk.status !== 'pending' ? 'is-resolved' : '';
      return `<button type="button" class="risk-list-item ${active} ${resolved}" data-risk-id="${escapeHtml(risk.id)}"><span><strong>${escapeHtml(risk.title)}</strong><small>${escapeHtml(risk.location)} · 置信度 ${Math.round(risk.confidence * 100)}%</small></span><span class="status-chip ${status.chipClass}">${status.label}</span></button>`;
    }).join('') : '<div class="review-empty-result"><i data-lucide="circle-check-big" aria-hidden="true"></i><strong>未命中自动检查规则</strong><span>仍需证券部按适用规则完成人工复核。</span></div>';

    document.querySelector('#risk-high-count').textContent = `高 ${result.summary.high || 0}`;
    document.querySelector('#risk-medium-count').textContent = `中 ${result.summary.medium || 0}`;
    updateRiskCounters();

    if (selectedRiskId) {
      selectRisk(selectedRiskId, false);
    } else {
      document.querySelector('#risk-reason').textContent = '本次本地规则检查未发现明确命中项。';
      document.querySelector('#risk-financial-change-group').hidden = true;
      document.querySelector('#risk-financial-change').innerHTML = '';
      document.querySelector('#risk-original').innerHTML = '<small>没有可定位的自动检查问题。</small>';
      document.querySelector('#risk-evidence').innerHTML = '<strong>仍需人工复核</strong><small>未命中不代表文档不存在合规风险。</small>';
      document.querySelector('#risk-suggestion').textContent = '请结合最新有效监管规则、公司制度和交易事实完成人工审查。';
      updateRiskActions();
    }
    renderAssistantMessages([]);
    if (platformState.connected) loadTaskConversations(task.id).catch((error) => showToast(error.message));
    if (result.aiMessage) showToast(result.aiMessage);
    renderSummaryComparison(result, task).catch((error) => showToast(error.message || '摘要—原文对比加载失败。'));
    refreshIcons();
  }

  function setReviewSideTab(name) {
    const activeName = name === 'assistant' ? name : 'risks';
    document.querySelectorAll('[data-review-tab]').forEach((item) => {
      const active = item.dataset.reviewTab === activeName;
      item.classList.toggle('is-active', active);
      item.setAttribute('aria-selected', String(active));
    });
    document.querySelector('#review-risk-tab').hidden = activeName !== 'risks';
    document.querySelector('#review-assistant-tab').hidden = activeName !== 'assistant';
  }

  function renderDemoReview() {
    document.querySelector('#view-review').innerHTML = demoReviewMarkup;
    risks = structuredClone(defaultRisks);
    resolvedRisks.clear();
    selectedRiskId = 'risk-amount';
    currentReviewTaskId = 'XS-2026-008';
    currentReviewDocument = null;
    resetSummaryComparisonPanel();
    initReviewControls();
    refreshIcons();
  }

  async function openTaskReview(task) {
    if (platformState.connected) {
      try {
        const result = await apiFetch(`/api/tasks/${encodeURIComponent(task.id)}`);
        latestAnalysisState = { task, result };
        renderUploadedReview(result, task);
        showView('review');
      } catch (error) {
        showToast(error.message);
      }
      return;
    }
    if (latestAnalysisState?.task?.id === task.id) {
      renderUploadedReview(latestAnalysisState.result, latestAnalysisState.task);
      showView('review');
      return;
    }
    if (defaultTasks.some((item) => item.id === task.id)) {
      if (currentReviewTaskId !== 'XS-2026-008') renderDemoReview();
      showView('review');
      return;
    }
    showToast('该文档正文未保留，请重新上传后继续审查');
  }

  function renderDirectBasis(item, label = '直接适用规则') {
    const sourceUrl = safeOfficialUrl(item.source_url || item.sourceUrl || '');
    const title = escapeHtml(item.title || item.source || '未命名规则');
    const article = item.article || item.section || '';
    const location = [article || '具体条款待人工核验', item.version || ''].filter(Boolean).join(' · ');
    const pageLocation = item.page ? `官方原文第 ${item.page} 页` : '';
    const heading = sourceUrl === '#'
      ? `<strong>${title}</strong>`
      : `<a href="${sourceUrl}" target="_blank" rel="noreferrer">${title}</a>`;
    const openLink = sourceUrl === '#' ? '' : `<a class="citation-open" href="${sourceUrl}" target="_blank" rel="noreferrer">打开官方原文</a>`;
    return `<article class="citation-item"><i class="citation-kind direct">${escapeHtml(label)}</i>${heading}<strong class="citation-article">${escapeHtml(location)}</strong><p>${escapeHtml(item.detail || item.content || '当前未保存条文要求，请打开官方原文核验。')}</p>${pageLocation ? `<small>${escapeHtml(pageLocation)}</small>` : ''}${openLink}</article>`;
  }

  function renderRagSource(source) {
    const sourceUrl = safeCitationUrl(source.source_url || source.sourceUrl || '');
    const title = escapeHtml(source.title || source.source || '未命名来源');
    const section = source.section || '';
    const article = source.article || (/第[一二三四五六七八九十百零〇0-9]+条|\d+\.\d+(?:\.\d+)?条?/.exec(section)?.[0] || '');
    const location = [article, !article ? section : '', source.version || '', source.page ? `原文第 ${source.page} 页` : ''].filter(Boolean).join(' · ');
    const documentParagraph = findCitationParagraph(source);
    if (documentParagraph !== null) {
      return `<button type="button" class="citation-item citation-jump" data-document-paragraph="${documentParagraph}"><i class="citation-kind">待审原文定位（非规则依据）</i><span class="citation-title"><strong>${title}</strong><i data-lucide="locate-fixed" aria-hidden="true"></i></span><small>${escapeHtml(location || `第 ${documentParagraph + 1} 段`)}</small><p>${escapeHtml(source.content || '')}</p><span class="citation-jump-label">定位到原文</span></button>`;
    }
    const heading = sourceUrl === '#'
      ? `<strong>${title}</strong>`
      : `<a href="${sourceUrl}" target="_blank" rel="noreferrer">${title}</a>`;
    const citationKind = source.citation_kind || source.metadata?.citation_kind || '';
    const typeLabel = citationKind === 'period_comparison'
      ? '历期官方报告对比来源'
      : citationKind === 'approved_case'
        ? '已确认正确案例'
        : source.document_type === 'regulations'
          ? '本地 RAG 条款命中'
          : '本地 RAG 补充资料';
    const openLink = sourceUrl === '#' ? '' : `<a class="citation-open" href="${sourceUrl}" target="_blank" rel="noreferrer">打开来源原文</a>`;
    return `<article class="citation-item"><i class="citation-kind rag">${typeLabel}</i>${heading}<small>${escapeHtml(location || '位置待人工核验')}</small><p>${escapeHtml(source.content || '')}</p>${openLink}</article>`;
  }

  function hasSubstantiveRuleLocation(source) {
    if (source.document_type !== 'regulations') return true;
    const locationText = `${source.article || ''} ${source.section || ''}`;
    return /第[一二三四五六七八九十百零〇0-9]+条|\d+\.\d+(?:\.\d+)?条?/.test(locationText);
  }

  function getRiskOriginalLocations(risk) {
    const supplied = risk.originalLocations || risk.original_locations || [];
    const locations = Array.isArray(supplied) && supplied.length ? supplied : [{
      label: risk.title || '问题原文',
      page: risk.page,
      section: risk.section,
      paragraphIndex: risk.paragraphIndex,
      text: risk.sourceText || risk.evidence || ''
    }];
    const seen = new Set();
    return locations.map((location, index) => {
      const rawParagraph = location.paragraphIndex ?? location.paragraph_index;
      const paragraphIndex = rawParagraph !== null && rawParagraph !== '' && Number.isInteger(Number(rawParagraph))
        ? Number(rawParagraph)
        : null;
      return {
        label: location.label || `相关原文 ${index + 1}`,
        page: location.page || risk.page || null,
        section: location.section || risk.section || '',
        paragraphIndex,
        text: location.text || location.content || (index === 0 ? risk.sourceText || risk.evidence || '' : ''),
        spreadsheetRow: location.spreadsheetRow ?? location.spreadsheet_row ?? null,
        sheetName: location.sheetName || location.sheet_name || '',
        documentId: location.documentId || location.document_id || ''
      };
    }).filter((location) => {
      const key = `${location.documentId}|${location.sheetName}|${location.spreadsheetRow}|${location.paragraphIndex}|${location.section}|${location.text}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function renderRiskOriginalLocations(risk) {
    return getRiskOriginalLocations(risk).map((location, index) => {
      const locationText = [
        location.page ? `第 ${location.page} 页` : '',
        location.sheetName ? `工作表 ${location.sheetName}` : '',
        location.spreadsheetRow ? `第 ${location.spreadsheetRow} 行` : '',
        location.section,
        Number.isInteger(location.paragraphIndex) ? `第 ${location.paragraphIndex + 1} 段` : ''
      ].filter(Boolean).join(' · ');
      const numericPage = Number(location.page);
      const canLocate = (!location.documentId || location.documentId === currentReviewDocument?.id)
        && (Number.isInteger(location.paragraphIndex)
        || (location.page !== null && location.page !== '' && Number.isInteger(numericPage) && numericPage > 0));
      const sourceFileLink = location.documentId && currentReviewTaskId && location.documentId !== currentReviewDocument?.id
        ? `<a class="risk-source-file" href="/api/tasks/${encodeURIComponent(currentReviewTaskId)}/documents/${encodeURIComponent(location.documentId)}" target="_blank" rel="noreferrer" download><i data-lucide="external-link" aria-hidden="true"></i>打开对比原文件</a>`
        : '';
      return `<article class="risk-original-item">
        <strong>${escapeHtml(location.label)}</strong>
        <small>${escapeHtml(locationText || '原文位置待确认')}</small>
        <p>${escapeHtml(location.text || '未提取到对应原文。')}</p>
        ${sourceFileLink}
        ${canLocate ? `<button class="button" type="button" data-risk-original-index="${index}"><i data-lucide="locate-fixed" aria-hidden="true"></i>定位此处原文</button>` : ''}
      </article>`;
    }).join('');
  }

  function formatStoredFinancialAmount(value) {
    const normalized = String(value ?? '').trim();
    const match = normalized.match(/^([+-]?)(\d+)(?:\.(\d+))?$/);
    if (!match) return normalized || '待确认';
    const integer = match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    const decimals = (match[3] || '').padEnd(2, '0');
    return `${match[1]}${integer}.${decimals}`;
  }

  function renderFinancialChange(calculation) {
    if (!calculation || !calculation.display_change_text) return '';
    const displayRate = calculation.display_yoy_rate;
    const rateRow = displayRate === null || displayRate === undefined || displayRate === ''
      ? ''
      : `<div><dt>可展示同比</dt><dd>${Number(displayRate) > 0 ? '+' : ''}${escapeHtml(displayRate)}%</dd></div>`;
    return `<strong>${escapeHtml(calculation.display_change_text)}</strong><dl class="financial-change-values">
      <div><dt>上年同期</dt><dd>${escapeHtml(formatStoredFinancialAmount(calculation.previous))} 元</dd></div>
      <div><dt>本报告期</dt><dd>${escapeHtml(formatStoredFinancialAmount(calculation.current))} 元</dd></div>
      <div><dt>金额变动</dt><dd>${escapeHtml(formatStoredFinancialAmount(calculation.absolute_change))} 元</dd></div>
      ${rateRow}
    </dl>`;
  }

  function selectRisk(riskId, scrollToSource = true) {
    const risk = risks[riskId];
    if (!risk) return;
    selectedRiskId = riskId;
    document.querySelectorAll('[data-risk-id]').forEach((control) => {
      control.classList.toggle('is-active', control.dataset.riskId === riskId);
    });
    document.querySelector('#risk-reason').textContent = risk.reason;
    const calculation = risk.financialChange || risk.calculation || {};
    const calculationMarkup = renderFinancialChange(calculation);
    document.querySelector('#risk-financial-change-group').hidden = !calculationMarkup;
    document.querySelector('#risk-financial-change').innerHTML = calculationMarkup;
    document.querySelector('#risk-original').innerHTML = renderRiskOriginalLocations(risk);
    const sources = risk.sourceDocuments || risk.source_documents || [];
    const allBasis = risk.regulation_basis || risk.regulationBasis || [];
    const basis = risk.primaryRegulationBasis || risk.primary_regulation_basis || allBasis.slice(0, 1);
    const additionalBasis = risk.additionalRegulationBasis || risk.additional_regulation_basis
      || allBasis.slice(basis.length);
    const ragSources = sources.filter((source) => (
      (source.citation_kind || source.metadata?.citation_kind) !== 'deterministic_rule'
      && hasSubstantiveRuleLocation(source)
    ));
    const directMarkup = basis.map((item) => renderDirectBasis(item)).join('');
    const additionalMarkup = additionalBasis.length
      ? `<details class="citation-more"><summary>其他相关法规（${additionalBasis.length} 条）</summary><div>${additionalBasis.map((item) => renderDirectBasis(item, '相关法规')).join('')}</div></details>`
      : '';
    const evidenceMarkup = directMarkup + additionalMarkup + ragSources.map(renderRagSource).join('');
    if (evidenceMarkup) {
      document.querySelector('#risk-evidence').innerHTML = evidenceMarkup;
    } else {
      const evidenceUrl = safeOfficialUrl(risk.evidenceUrl);
      document.querySelector('#risk-evidence').innerHTML = evidenceUrl === '#'
        ? `<strong>${escapeHtml(risk.evidenceTitle || '当前知识库未检索到直接依据')}</strong><small>${escapeHtml(risk.evidenceNote || '请人工进一步确认。')}</small>`
        : `<a href="${evidenceUrl}" target="_blank" rel="noreferrer">${escapeHtml(risk.evidenceTitle)}</a><small>${escapeHtml(risk.evidenceNote)}</small>`;
    }
    document.querySelector('#risk-suggestion').textContent = risk.suggestion;
    updateRiskActions();
    if (scrollToSource && reviewReaderMode === 'original') {
      locateOriginalRisk(risk);
    } else if (scrollToSource && Number.isInteger(risk.paragraphIndex)) {
      locateDocumentParagraph(risk.paragraphIndex);
    }
    refreshIcons();
  }

  function findCitationParagraph(source) {
    if (!currentReviewDocument || String(source.document_id || '') !== String(currentReviewDocument.id || '')) return null;
    const explicitParagraph = Number(source.paragraph ?? source.paragraph_index);
    if (Number.isInteger(explicitParagraph) && explicitParagraph >= 0) return explicitParagraph;
    const excerpt = String(source.content || '').trim();
    if (excerpt) {
      const excerptStart = excerpt.split(/\r?\n/).find((line) => line.trim())?.trim().slice(0, 80) || '';
      const matchIndex = currentReviewDocument.paragraphs.findIndex((paragraph) => {
        const text = String(paragraph || '').trim();
        return excerptStart && (text.includes(excerptStart) || excerpt.includes(text.slice(0, 80)));
      });
      if (matchIndex >= 0) return matchIndex;
    }
    const section = String(source.section || '').trim();
    const heading = currentReviewDocument.headings.find((item) => section && (String(item.section || '') === section || String(item.text || '').includes(section)));
    if (heading && Number.isInteger(Number(heading.paragraphIndex))) return Number(heading.paragraphIndex);
    const page = Number(source.page);
    const block = currentReviewDocument.blocks.find((item) => Number.isInteger(page) && Number(item.page) === page);
    return block && Number.isInteger(Number(block.paragraphIndex)) ? Number(block.paragraphIndex) : null;
  }

  function locateDocumentParagraph(paragraphIndex, block = 'center') {
    const target = document.querySelector(`#uploaded-paragraph-${paragraphIndex}`);
    const scroller = document.querySelector('.paper-wrap');
    if (!target || !scroller) return;
    const scrollerRect = scroller.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const alignmentOffset = block === 'start' ? 18 : Math.max(18, (scroller.clientHeight - targetRect.height) / 2);
    const nextTop = scroller.scrollTop + targetRect.top - scrollerRect.top - alignmentOffset;
    scroller.scrollTo({ top: Math.max(0, nextTop), behavior: 'smooth' });
    document.querySelectorAll('#review-document-paper .document-location-target').forEach((element) => element.classList.remove('document-location-target'));
    target.classList.add('document-location-target');
    window.setTimeout(() => target.classList.remove('document-location-target'), 1800);
    const closestHeading = [...document.querySelectorAll('#review-outline [data-scroll-paragraph]')]
      .filter((button) => Number(button.dataset.scrollParagraph) <= Number(paragraphIndex)).pop();
    if (closestHeading) document.querySelectorAll('#review-outline button').forEach((button) => button.classList.toggle('is-active', button === closestHeading));
    const page = target.dataset.page ? `第 ${target.dataset.page} 页` : '';
    const section = target.dataset.section || '';
    document.querySelector('#review-reader-meta').textContent = [page, section, `第 ${Number(paragraphIndex) + 1} 段`].filter(Boolean).join(' · ');
  }

  async function resolveRisk(action, comment = '') {
    if (!selectedRiskId) return;
    if (resolvedRisks.has(selectedRiskId) && !['supplement', 'reopen'].includes(action)) {
      showToast('该风险已经处理');
      return;
    }
    let reviewResult = null;
    if (platformState.connected) {
      try {
        reviewResult = await apiFetch(`/api/risks/${encodeURIComponent(selectedRiskId)}/review`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action, comment })
        });
      } catch (error) {
        showToast(error.message);
        return;
      }
    }
    risks[selectedRiskId].status = reviewResult?.status || ({ confirm: 'confirmed', ignore: 'false_positive', supplement: 'needs_material', reopen: 'pending' })[action] || 'resolved';
    const reopened = risks[selectedRiskId].status === 'pending';
    if (reopened) resolvedRisks.delete(selectedRiskId);
    else resolvedRisks.add(selectedRiskId);
    document.querySelectorAll(`[data-risk-id="${selectedRiskId}"]`).forEach((control) => control.classList.toggle('is-resolved', !reopened));
    const listItem = document.querySelector(`.risk-list-item[data-risk-id="${selectedRiskId}"] .status-chip`);
    if (listItem) {
      const status = getRiskStatusMeta(risks[selectedRiskId].status, risks[selectedRiskId].severity);
      listItem.className = `status-chip ${status.chipClass}`;
      listItem.textContent = status.label;
    }
    updateRiskCounters();
    updateRiskActions();
    refreshIcons();
    showToast(action === 'confirm'
      ? '风险已确认并写入审计记录'
      : action === 'ignore'
        ? '已标记误报并保留审计记录'
        : action === 'reopen'
          ? '已撤销处理，风险恢复为待处理'
          : '补充材料要求已记录');
  }

  function initReviewControls() {
    document.querySelector('#risk-list').addEventListener('click', (event) => {
      const control = event.target.closest('[data-risk-id]');
      if (control) selectRisk(control.dataset.riskId);
    });
    document.querySelector('#review-document-paper').addEventListener('click', (event) => {
      const control = event.target.closest('[data-risk-id]');
      if (control) selectRisk(control.dataset.riskId, false);
    });
    document.querySelector('#review-outline').addEventListener('click', (event) => {
      const control = event.target.closest('[data-scroll-paragraph]');
      if (!control) return;
      document.querySelectorAll('#review-outline button').forEach((button) => button.classList.toggle('is-active', button === control));
      locateOutlineParagraph(Number(control.dataset.scrollParagraph));
    });
    document.querySelector('#summary-comparison-findings')?.addEventListener('click', (event) => {
      const control = event.target.closest('[data-comparison-key][data-comparison-paragraph], [data-comparison-side][data-comparison-paragraph]');
      if (!control) return;
      const side = control.dataset.comparisonKey || control.dataset.comparisonSide;
      const paragraph = Number(control.dataset.comparisonParagraph);
      const scroller = document.getElementById(`summary-comparison-${side}-body`);
      const target = scroller?.querySelector(`[data-comparison-paragraph="${paragraph}"]`);
      if (!target || !scroller) return;
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      document.querySelectorAll('.summary-comparison-block.is-comparison-target').forEach((element) => element.classList.remove('is-comparison-target'));
      target.classList.add('is-comparison-target');
      window.setTimeout(() => target.classList.remove('is-comparison-target'), 1800);
    });
    document.querySelector('#risk-evidence').addEventListener('click', (event) => {
      const control = event.target.closest('[data-document-paragraph]');
      if (control) locateDocumentParagraph(Number(control.dataset.documentParagraph));
    });
    document.querySelector('#risk-original').addEventListener('click', (event) => {
      const control = event.target.closest('[data-risk-original-index]');
      if (!control || !selectedRiskId || !risks[selectedRiskId]) return;
      const location = getRiskOriginalLocations(risks[selectedRiskId])[Number(control.dataset.riskOriginalIndex)];
      if (!location) return;
      if (reviewReaderMode === 'original' && selectedRiskId) {
        locateOriginalRisk(risks[selectedRiskId], location);
      } else {
        locateDocumentParagraph(location.paragraphIndex);
      }
    });
    document.querySelector('#confirm-risk').addEventListener('click', () => resolveRisk('confirm'));
    document.querySelector('#ignore-risk').addEventListener('click', () => resolveRisk('ignore'));
    document.querySelector('#undo-risk').addEventListener('click', () => resolveRisk('reopen'));
    document.querySelector('#note-risk').addEventListener('click', () => {
      if (!selectedRiskId || !risks[selectedRiskId]) return;
      const note = window.prompt('请输入需要补充的材料或复核备注：', risks[selectedRiskId].note || '');
      if (note === null) return;
      risks[selectedRiskId].note = note.trim();
      resolveRisk('supplement', note.trim());
    });
    document.querySelector('#generate-report').addEventListener('click', () => {
      if (!currentReviewTaskId) {
        showToast('请先打开一项审查任务');
        return;
      }
      exportReviewReport(currentReviewTaskId);
    });
    document.querySelector('#download-annotated-document').addEventListener('click', downloadAnnotatedDocument);
    document.querySelector('#review-zoom-out').addEventListener('click', () => setDocumentZoom(documentZoom - 0.1));
    document.querySelector('#review-zoom-in').addEventListener('click', () => setDocumentZoom(documentZoom + 0.1));
    document.querySelector('#download-review-document').addEventListener('click', downloadCurrentDocument);
    document.querySelectorAll('[data-reader-mode]').forEach((button) => button.addEventListener('click', () => {
      setReviewReaderMode(button.dataset.readerMode);
    }));
    document.querySelectorAll('[data-review-tab]').forEach((button) => button.addEventListener('click', () => {
      setReviewSideTab(button.dataset.reviewTab);
      if (button.dataset.reviewTab === 'assistant') document.querySelector('#assistant-question').focus();
    }));
    document.querySelector('#new-conversation').addEventListener('click', () => {
      platformState.activeConversationId = null;
      renderAssistantMessages([]);
      document.querySelector('#assistant-question').focus();
    });
    document.querySelector('#assistant-form').addEventListener('submit', sendAssistantQuestion);
    if (selectedRiskId) selectRisk(selectedRiskId, false);
  }

  function setDocumentZoom(value) {
    documentZoom = Math.max(0.8, Math.min(1.3, Math.round(value * 10) / 10));
    document.querySelector('#review-document-paper').style.fontSize = `${documentZoom * 100}%`;
    const originalPaper = document.querySelector('.original-preview-paper');
    if (originalPaper) originalPaper.style.fontSize = `${documentZoom * 100}%`;
    showToast(`原文缩放 ${Math.round(documentZoom * 100)}%`);
  }

  async function downloadCurrentDocument() {
    if (!platformState.connected || !currentReviewTaskId) {
      showToast('请先打开一项真实审查任务');
      return;
    }
    try {
      const response = await fetch(`/api/tasks/${encodeURIComponent(currentReviewTaskId)}/document`, { credentials: 'same-origin' });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || '原始文件下载失败。');
      }
      const task = platformState.tasks.find((item) => item.id === currentReviewTaskId);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = task?.file || '审查原文';
      link.click();
      URL.revokeObjectURL(url);
      showToast('原始文件已下载并记录审计日志');
      if (platformState.permissions.includes('audit')) loadAudit().catch(() => {});
    } catch (error) { showToast(error.message); }
  }

  function responseDownloadFilename(response, fallback) {
    const disposition = response.headers.get('Content-Disposition') || '';
    const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
    if (!encoded) return fallback;
    try { return decodeURIComponent(encoded); }
    catch (_error) { return fallback; }
  }

  async function downloadAnnotatedDocument() {
    if (!platformState.connected || !currentReviewTaskId) {
      showToast('请先打开一项真实审查任务');
      return;
    }
    const button = document.querySelector('#download-annotated-document');
    button.disabled = true;
    try {
       showToast('正在基于 Word 原件生成修订批注版…');
      const response = await fetch(
        `/api/tasks/${encodeURIComponent(currentReviewTaskId)}/annotated-document`,
        { credentials: 'same-origin' },
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || '修订批注版生成失败。');
      }
      const task = platformState.tasks.find((item) => item.id === currentReviewTaskId);
       const fallback = `${String(task?.file || '审查原文').replace(/\.docx$/i, '')}_AI合规审阅修订批注版.docx`;
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = responseDownloadFilename(response, fallback);
      link.click();
      URL.revokeObjectURL(url);
       showToast('修订批注版已生成，上传原件未被修改');
      if (platformState.permissions.includes('audit')) loadAudit().catch(() => {});
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
    }
  }

  function citationMarkup(sources = []) {
    if (!sources.length) return '<p class="assistant-no-source">当前知识库未检索到直接依据，请人工进一步确认。</p>';
    return `<details class="assistant-sources"><summary>${sources.length} 个检索来源</summary>${sources.map((source) => {
      const url = safeCitationUrl(source.source_url || source.sourceUrl || '');
      const title = escapeHtml(source.title || source.source || '未命名来源');
      const label = [source.page ? `第 ${source.page} 页` : '', source.section || '', source.chunk_id || ''].filter(Boolean).join(' · ');
      const heading = url === '#' ? `<strong>${title}</strong>` : `<a href="${url}" target="_blank" rel="noreferrer">${title}</a>`;
      return `<div>${heading}<small>${escapeHtml(label || '位置待确认')}</small><p>${escapeHtml(source.content || '')}</p></div>`;
    }).join('')}</details>`;
  }

  function renderAssistantMessages(messages) {
    const container = document.querySelector('#assistant-messages');
    if (!messages.length) {
      container.innerHTML = '<div class="assistant-empty"><i data-lucide="messages-square" aria-hidden="true"></i><strong>围绕当前任务继续提问</strong><span>例如：为什么判定为风险？引用了哪些公司制度？</span></div>';
      refreshIcons();
      return;
    }
    container.innerHTML = messages.map((message) => {
      const role = message.role === 'assistant' ? 'assistant' : 'user';
      return `<article class="assistant-message ${role}"><span>${role === 'assistant' ? '合规助手' : '我'}</span><p>${escapeHtml(message.content).replaceAll('\n', '<br>')}</p>${role === 'assistant' ? citationMarkup(message.citations || message.source_documents || []) : ''}</article>`;
    }).join('');
    container.scrollTop = container.scrollHeight;
  }

  async function loadTaskConversations(taskId) {
    if (!platformState.connected || !taskId) return;
    const payload = await apiFetch(`/api/conversations?task_id=${encodeURIComponent(taskId)}`);
    platformState.conversations = payload.conversations || [];
    const conversation = platformState.conversations[0];
    platformState.activeConversationId = conversation?.id || null;
    if (!conversation) {
      renderAssistantMessages([]);
      return;
    }
    const messagePayload = await apiFetch(`/api/conversations/${encodeURIComponent(conversation.id)}/messages`);
    renderAssistantMessages(messagePayload.messages || []);
  }

  async function sendAssistantQuestion(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = document.querySelector('#assistant-question');
    const question = input.value.trim();
    if (!question || !currentReviewTaskId) return;
    if (!platformState.connected) {
      showToast('AI 助手需要通过 Windows 启动器打开');
      return;
    }
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    const existing = [...document.querySelectorAll('#assistant-messages .assistant-message')].map((element) => ({
      role: element.classList.contains('assistant') ? 'assistant' : 'user',
      content: element.querySelector('p')?.innerText || '',
      citations: []
    }));
    renderAssistantMessages([...existing, { role: 'user', content: question }, { role: 'assistant', content: '正在检索当前任务、公司知识库和法规库...', citations: [] }]);
    try {
      const result = await apiFetch(`/api/tasks/${encodeURIComponent(currentReviewTaskId)}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, conversation_id: platformState.activeConversationId })
      });
      platformState.activeConversationId = result.conversation_id;
      input.value = '';
      await loadTaskConversations(currentReviewTaskId);
      if (platformState.permissions.includes('audit')) loadUsage().catch(() => {});
    } catch (error) {
      renderAssistantMessages([...existing, { role: 'user', content: question }, { role: 'assistant', content: error.message, citations: [] }]);
    } finally {
      button.disabled = false;
    }
  }

  function renderWorkspaceConversations() {
    const list = document.querySelector('#workspace-conversation-list');
    if (!list) return;
    const conversations = platformState.workspaceConversations || [];
    list.innerHTML = conversations.length
      ? conversations.map((conversation) => `<button type="button" class="workspace-conversation-item ${conversation.id === platformState.workspaceConversationId ? 'is-active' : ''}" data-workspace-conversation="${escapeHtml(conversation.id)}"><strong>${escapeHtml(conversation.title || '未命名对话')}</strong><small>${escapeHtml(formatDataTimestamp(conversation.updated_at))}</small></button>`).join('')
      : '<div class="chat-empty">还没有独立对话。</div>';
    list.querySelectorAll('[data-workspace-conversation]').forEach((button) => button.addEventListener('click', () => loadWorkspaceConversation(button.dataset.workspaceConversation)));
  }

  async function loadWorkspaceConversation(conversationId) {
    if (!conversationId) {
      platformState.workspaceConversationId = null;
      renderWorkspaceMessages([]);
      renderWorkspaceConversations();
      return;
    }
    const payload = await apiFetch(`/api/chat/${encodeURIComponent(conversationId)}/messages`);
    platformState.workspaceConversationId = conversationId;
    renderWorkspaceMessages(payload.messages || []);
    renderWorkspaceConversations();
  }

  function renderWorkspaceMessages(messages) {
    const container = document.querySelector('#workspace-chat-messages');
    if (!container) return;
    if (!messages.length) {
      container.innerHTML = '<div class="assistant-empty"><i data-lucide="messages-square" aria-hidden="true"></i><strong>输入问题开始检索</strong><span>例如：公司关联交易制度有哪些审批要求？</span></div>';
      refreshIcons();
      return;
    }
    container.innerHTML = messages.map((message) => {
      const role = message.role === 'assistant' ? 'assistant' : 'user';
      return `<article class="assistant-message ${role}"><span>${role === 'assistant' ? '本地资料助手' : '我'}</span><p>${escapeHtml(message.content).replaceAll('\n', '<br>')}</p>${role === 'assistant' ? citationMarkup(message.citations || []) : ''}</article>`;
    }).join('');
    container.scrollTop = container.scrollHeight;
    refreshIcons();
  }

  async function loadWorkspaceConversations() {
    if (!platformState.connected || !platformState.authenticated || !platformState.permissions.includes('analyze')) return;
    const payload = await apiFetch('/api/chat/conversations');
    platformState.workspaceConversations = payload.conversations || [];
    if (platformState.workspaceConversationId && !platformState.workspaceConversations.some((item) => item.id === platformState.workspaceConversationId)) {
      platformState.workspaceConversationId = null;
    }
    renderWorkspaceConversations();
    if (platformState.workspaceConversationId) await loadWorkspaceConversation(platformState.workspaceConversationId);
  }

  async function sendWorkspaceQuestion(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = document.querySelector('#workspace-chat-question');
    const question = input?.value.trim();
    if (!question) return;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    const existing = [...document.querySelectorAll('#workspace-chat-messages .assistant-message')].map((element) => ({
      role: element.classList.contains('assistant') ? 'assistant' : 'user',
      content: element.querySelector('p')?.innerText || '',
      citations: []
    }));
    renderWorkspaceMessages([...existing, { role: 'user', content: question }, { role: 'assistant', content: '正在检索本地资料库和规则库...', citations: [] }]);
    try {
      const result = await apiFetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, conversation_id: platformState.workspaceConversationId })
      });
      platformState.workspaceConversationId = result.conversation_id;
      input.value = '';
      await loadWorkspaceConversations();
      await loadWorkspaceConversation(platformState.workspaceConversationId);
    } catch (error) {
      renderWorkspaceMessages([...existing, { role: 'user', content: question }, { role: 'assistant', content: error.message, citations: [] }]);
    } finally {
      button.disabled = false;
    }
  }

  function initWorkspaceChatControls() {
    document.querySelector('#workspace-chat-form')?.addEventListener('submit', sendWorkspaceQuestion);
    document.querySelector('#refresh-workspace-conversations')?.addEventListener('click', () => loadWorkspaceConversations().catch((error) => showToast(error.message)));
    document.querySelector('#new-workspace-conversation')?.addEventListener('click', () => loadWorkspaceConversation(null));
  }

  const knowledgeTypeLabels = {
    company_profile: '公司画像', internal_rules: '内部制度', regulations: '法规规则',
    announcements: '历史公告', cases: '历史案例', drafting_materials: '起草文书资料',
    user_documents: '其他资料'
  };

  function renderKnowledgeCategoryControls() {
    const categories = platformState.knowledgeCategories || [];
    const root = document.querySelector('#knowledge-custom-filters');
    const select = document.querySelector('#knowledge-category-select');
    if (root) {
      root.innerHTML = categories.map((category) => `<button class="segment ${platformState.knowledgeCategoryId === category.id ? 'is-active' : ''}" type="button" data-knowledge-category="${escapeHtml(category.id)}">${escapeHtml(category.name)}</button>`).join('');
      root.querySelectorAll('[data-knowledge-category]').forEach((button) => button.addEventListener('click', async () => {
        platformState.knowledgeType = 'all';
        platformState.knowledgeCategoryId = button.dataset.knowledgeCategory;
        document.querySelectorAll('[data-knowledge-type]').forEach((item) => item.classList.toggle('is-active', item.dataset.knowledgeType === 'all'));
        document.querySelectorAll('[data-knowledge-category]').forEach((item) => item.classList.toggle('is-active', item === button));
        renderKnowledgeCategoryControls();
        await loadKnowledge();
      }));
    }
    if (select) {
      select.innerHTML = '<option value="">不设置自定义资料栏</option>' + categories.map((category) => `<option value="${escapeHtml(category.id)}">${escapeHtml(category.name)}</option>`).join('');
      select.value = platformState.knowledgeCategoryId || '';
    }
  }

  async function loadKnowledgeCategories() {
    if (!platformState.connected || !platformState.authenticated) return;
    const payload = await apiFetch('/api/knowledge/categories');
    platformState.knowledgeCategories = payload.categories || [];
    renderKnowledgeCategoryControls();
  }

  function renderKnowledgeCategoryList() {
    const root = document.querySelector('#knowledge-category-list');
    if (!root) return;
    const categories = platformState.knowledgeCategories || [];
    root.innerHTML = categories.length ? categories.map((category) => `<div class="knowledge-category-row"><span><strong>${escapeHtml(category.name)}</strong><small>${escapeHtml(category.description || '无说明')}</small></span><button type="button" class="row-action danger" data-delete-knowledge-category="${escapeHtml(category.id)}">停用</button></div>`).join('') : '<div class="chat-empty">还没有自定义资料栏。</div>';
    root.querySelectorAll('[data-delete-knowledge-category]').forEach((button) => button.addEventListener('click', async () => {
      if (!window.confirm('停用后不能再将新资料放入此栏，已入库资料仍保留。是否继续？')) return;
      button.disabled = true;
      try {
        await apiFetch(`/api/knowledge/categories/${encodeURIComponent(button.dataset.deleteKnowledgeCategory)}`, { method: 'DELETE' });
        await loadKnowledgeCategories();
        renderKnowledgeCategoryList();
        await loadKnowledge();
      } catch (error) { showToast(error.message); button.disabled = false; }
    }));
  }

  function initKnowledgeCategoryControls() {
    const dialog = document.querySelector('#knowledge-category-dialog');
    const form = document.querySelector('#knowledge-category-form');
    if (!dialog || !form) return;
    document.querySelector('#open-knowledge-category-dialog')?.addEventListener('click', async () => {
      await loadKnowledgeCategories();
      renderKnowledgeCategoryList();
      dialog.showModal();
    });
    document.querySelector('#close-knowledge-category-dialog')?.addEventListener('click', () => dialog.close());
    document.querySelector('#cancel-knowledge-category-dialog')?.addEventListener('click', () => dialog.close());
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const fields = new FormData(form);
      const status = document.querySelector('#knowledge-category-status');
      const submit = form.querySelector('button[type="submit"]');
      submit.disabled = true;
      try {
        await apiFetch('/api/knowledge/categories', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: fields.get('name'), description: fields.get('description') }) });
        form.reset();
        await loadKnowledgeCategories();
        renderKnowledgeCategoryList();
        await loadKnowledge();
        if (status) status.textContent = '资料栏已新增。';
      } catch (error) {
        if (status) { status.textContent = error.message; status.classList.add('is-error'); }
      } finally { submit.disabled = false; }
    });
  }

  function showLibraryPanel(requestedPanel, load = true) {
    const canManageKnowledge = platformState.permissions.includes('knowledge');
    libraryPanel = requestedPanel === 'knowledge' && canManageKnowledge ? 'knowledge' : 'rules';
    document.querySelectorAll('[data-library-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.libraryPanel !== libraryPanel;
    });
    document.querySelectorAll('[data-library-tab]').forEach((button) => {
      const active = button.dataset.libraryTab === libraryPanel;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', String(active));
    });
    if (libraryPanel === 'knowledge' && load) loadKnowledge().catch((error) => showToast(error.message));
    refreshIcons();
  }

  function initLibraryControls() {
    document.querySelectorAll('[data-library-tab]').forEach((button) => {
      button.addEventListener('click', () => showLibraryPanel(button.dataset.libraryTab));
    });
    document.querySelector('#knowledge-search').addEventListener('input', (event) => {
      knowledgeSearch = event.target.value;
      renderKnowledge();
    });
    showLibraryPanel('rules', false);
  }

  function renderKnowledge() {
    const documents = platformState.knowledge;
    const keyword = knowledgeSearch.trim().toLocaleLowerCase();
    const filteredDocuments = documents.filter((documentItem) => {
      if (!keyword) return true;
      const haystack = [
        documentItem.title,
        documentItem.source,
        documentItem.version,
        documentItem.company,
      documentItem.announcement_id,
        documentItem.publication_date,
        documentItem.effective_date,
        knowledgeTypeLabels[documentItem.document_type],
        documentItem.category_name,
      ].filter(Boolean).join(' ').toLocaleLowerCase();
      return haystack.includes(keyword);
    });
    const activeTotal = documents.filter((item) => item.status === 'active').length;
    const activeFiltered = filteredDocuments.filter((item) => item.status === 'active').length;
    document.querySelector('#knowledge-total').textContent = keyword
      ? `${activeFiltered} / ${activeTotal} 份有效文档`
      : `${activeTotal} 份有效文档`;
    const body = document.querySelector('#knowledge-table-body');
    body.innerHTML = filteredDocuments.map((documentItem) => {
      const canOpen = documentItem.status === 'active' || documentItem.can_manage;
      const title = canOpen
        ? `<button class="knowledge-title-link" type="button" data-preview-knowledge="${escapeHtml(documentItem.id)}"><strong>${escapeHtml(documentItem.title)}</strong><i data-lucide="eye" aria-hidden="true"></i></button>`
        : `<strong>${escapeHtml(documentItem.title)}</strong>`;
      const viewAction = canOpen
        ? `<button class="row-action icon-row-action" type="button" data-preview-knowledge="${escapeHtml(documentItem.id)}" aria-label="查看原文件" data-tip="查看原文件"><i data-lucide="eye" aria-hidden="true"></i></button>`
        : '';
      const manageActions = documentItem.can_manage && documentItem.status === 'active'
        ? `<button class="row-action" type="button" data-rebuild-knowledge="${escapeHtml(documentItem.id)}" data-tip="重新解析原文件并更新 RAG 索引">重新索引</button><button class="row-action danger" type="button" data-disable-knowledge="${escapeHtml(documentItem.id)}">停用</button>`
        : '';
      const relativePath = documentItem.source_name && documentItem.source_name !== documentItem.source
        ? `相对路径：${documentItem.source_name}`
        : '';
      const sourceMeta = [relativePath, documentItem.version || '版本未标注'].filter(Boolean).join(' · ');
      return `<tr>
      <td><span class="task-name">${title}<small>${documentItem.scope === 'shared' ? '公共底库' : '仅本人可见'}</small></span></td>
      <td><span>${escapeHtml(knowledgeTypeLabels[documentItem.document_type] || documentItem.document_type)}</span>${documentItem.category_name ? `<small class="table-subline">${escapeHtml(documentItem.category_name)}</small>` : ''}</td>
      <td><span class="task-name"><strong>${escapeHtml(documentItem.source)}</strong><small>${escapeHtml(sourceMeta)}</small></span></td>
      <td>${Number(documentItem.page_count || 0)}</td><td>${Number(documentItem.chunk_count || 0)}</td>
      <td><span class="status-chip ${documentItem.status === 'active' ? 'success' : 'neutral'}">${documentItem.status === 'active' ? '有效' : '已停用'}</span></td>
      <td><div class="row-actions">${viewAction}${manageActions}</div></td>
    </tr>`;
    }).join('');
    const empty = document.querySelector('#knowledge-empty');
    empty.hidden = filteredDocuments.length > 0;
    const emptyTitle = empty.querySelector('strong');
    const emptyMessage = empty.querySelector('span');
    if (keyword) {
      emptyTitle.textContent = '没有匹配的资料';
      emptyMessage.textContent = '请调整搜索关键词或切换资料分类。';
    } else {
      emptyTitle.textContent = '当前分类暂无资料';
      emptyMessage.textContent = '通过“导入资料”上传 PDF、Word、XLS/XLSX、CSV、TXT、MD 或 JSON。';
    }
    body.querySelectorAll('[data-rebuild-knowledge]').forEach((button) => button.addEventListener('click', () => rebuildKnowledge(button.dataset.rebuildKnowledge)));
    body.querySelectorAll('[data-disable-knowledge]').forEach((button) => button.addEventListener('click', () => disableKnowledge(button.dataset.disableKnowledge)));
    body.querySelectorAll('[data-preview-knowledge]').forEach((button) => button.addEventListener('click', () => openKnowledgePreview(button.dataset.previewKnowledge)));
    refreshIcons();
  }

  async function loadKnowledge() {
    if (!platformState.connected || !platformState.authenticated) return;
    const params = new URLSearchParams();
    if (platformState.knowledgeType !== 'all') params.set('document_type', platformState.knowledgeType);
    if (platformState.knowledgeCategoryId) params.set('category_id', platformState.knowledgeCategoryId);
    const query = params.toString() ? `?${params.toString()}` : '';
    const payload = await apiFetch(`/api/knowledge${query}`);
    platformState.knowledge = payload.documents || [];
    await loadKnowledgeCategories();
    renderKnowledge();
  }

  function renderUsers() {
    const users = platformState.users;
    const activeUsers = users.filter((user) => Number(user.active) === 1);
    document.querySelector('#account-total').textContent = users.length.toLocaleString('zh-CN');
    document.querySelector('#account-active-total').textContent = activeUsers.length.toLocaleString('zh-CN');
    document.querySelector('#account-admin-total').textContent = users.filter((user) => user.role === 'admin').length.toLocaleString('zh-CN');
    document.querySelector('#account-nav-count').textContent = users.length.toLocaleString('zh-CN');
    document.querySelector('#account-table-body').innerHTML = users.length ? users.map((user) => {
      const active = Number(user.active) === 1;
      const current = user.id === platformState.user?.id ? '<small>当前登录账号</small>' : '';
      const action = user.id === platformState.user?.id
        ? '<span class="table-muted">当前账号</span>'
        : `<button class="row-action danger" type="button" data-delete-user="${escapeHtml(user.id)}" data-user-label="${escapeHtml(user.username)}"><i data-lucide="trash-2" aria-hidden="true"></i>注销</button>`;
      return `<tr>
        <td><span class="task-name"><strong class="account-username">${escapeHtml(user.username)}</strong>${current}</span></td>
        <td>${escapeHtml(user.display_name || '未设置')}</td>
        <td><span class="status-chip ${user.role === 'admin' ? 'high' : 'neutral'}">${escapeHtml(roleLabel(user.role))}</span></td>
        <td><span class="status-chip ${active ? 'success' : 'neutral'}">${active ? '已启用' : '已停用'}</span></td>
        <td class="table-muted">${escapeHtml(formatDataTimestamp(user.created_at))}</td>
        <td class="table-muted">${escapeHtml(formatDataTimestamp(user.updated_at))}</td>
        <td>${action}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="7"><div class="table-empty"><strong>暂无注册账号</strong></div></td></tr>';
    document.querySelectorAll('[data-delete-user]').forEach((button) => button.addEventListener('click', () => deleteManagedUser(button)));
    refreshIcons();
  }

  async function deleteManagedUser(button) {
    const label = button.dataset.userLabel || '该账号';
    if (!window.confirm(`确认注销账号“${label}”？该账号的私有文档、任务、向量和记忆将被永久删除。`)) return;
    button.disabled = true;
    try {
      await apiFetch(`/api/users/${encodeURIComponent(button.dataset.deleteUser)}`, { method: 'DELETE' });
      showToast(`账号“${label}”已注销`);
      await loadUsers();
    } catch (error) {
      showToast(error.message);
      button.disabled = false;
    }
  }

  async function loadUsers() {
    if (!platformState.connected || !platformState.authenticated || !platformState.permissions.includes('users')) return;
    const payload = await apiFetch('/api/users');
    platformState.users = payload.users || [];
    renderUsers();
  }

  function initUserControls() {
    document.querySelector('#refresh-accounts').addEventListener('click', async () => {
      try {
        await loadUsers();
        showToast('账号列表已刷新');
      } catch (error) { showToast(error.message); }
    });
  }

  async function rebuildKnowledge(documentId) {
    try {
      const result = await apiFetch(`/api/knowledge/${encodeURIComponent(documentId)}/rebuild`, { method: 'POST' });
      showToast(`已重新索引 ${result.chunks} 个 Chunk`);
      await loadKnowledge();
    } catch (error) { showToast(error.message); }
  }

  async function disableKnowledge(documentId) {
    if (!window.confirm('停用后该文档不再参与 RAG 检索，是否继续？')) return;
    try {
      await apiFetch(`/api/knowledge/${encodeURIComponent(documentId)}`, { method: 'DELETE' });
      showToast('知识文档已停用并移出向量索引');
      await loadKnowledge();
    } catch (error) { showToast(error.message); }
  }

  function initKnowledgeControls() {
    document.querySelectorAll('[data-knowledge-type]').forEach((button) => button.addEventListener('click', async () => {
      platformState.knowledgeType = button.dataset.knowledgeType;
      platformState.knowledgeCategoryId = null;
      document.querySelectorAll('[data-knowledge-type]').forEach((item) => item.classList.toggle('is-active', item === button));
      renderKnowledgeCategoryControls();
      await loadKnowledge();
    }));
    const dialog = document.querySelector('#knowledge-dialog');
    const form = document.querySelector('#knowledge-form');
    const typeSelect = form?.elements?.document_type;
    const dialogTitle = document.querySelector('#knowledge-dialog-title');
    const defaultImportStatus = '系统将逐份解析、Chunk、Embedding，并按文件哈希跳过重复内容。';
    const directDraftingStatus = '直接导入起草文书：无需填写公司、来源、版本等信息，系统会自动按文件名归档并建立本地检索索引。';
    const knowledgeImportStatus = document.querySelector('#knowledge-import-status');
    const knowledgeFileSelection = document.querySelector('#knowledge-file-selection');
    const fileInput = form?.elements?.documents;
    const folderInput = form?.elements?.folder_documents;

    const getKnowledgeFiles = () => {
      const candidates = [
        ...(fileInput?.files ? [...fileInput.files] : []),
        ...(folderInput?.files ? [...folderInput.files] : []),
      ].filter((file) => /\.(pdf|doc|docx|xls|xlsx|csv|txt|md|json)$/i.test(file.name));
      const seen = new Set();
      return candidates
        .map((file) => ({
          file,
          relativePath: String(file.webkitRelativePath || file.name).replaceAll('\\', '/'),
        }))
        .filter(({ file, relativePath }) => {
          // Keep same-named files from different folders, but avoid adding the
          // same browser File twice when both pickers contain it.
          const key = `${relativePath}\u0000${file.size}\u0000${file.lastModified}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        })
        .sort((left, right) => left.relativePath.localeCompare(right.relativePath, 'zh-CN'));
    };

    const renderKnowledgeFileSelection = () => {
      const files = getKnowledgeFiles();
      const folderCount = folderInput?.files?.length || 0;
      const allCount = (fileInput?.files?.length || 0) + folderCount;
      if (!files.length) {
        if (knowledgeFileSelection) knowledgeFileSelection.textContent = '尚未选择文件。选择文件夹后，系统会列出并逐份导入其中的支持文件。';
        return;
      }
      const ignored = Math.max(0, allCount - files.length);
      const prefix = folderCount ? `已选择文件夹：${folderCount} 个文件` : `已选择 ${files.length} 个文件`;
      if (knowledgeFileSelection) {
        knowledgeFileSelection.textContent = `${prefix}${ignored ? `，已忽略 ${ignored} 个不支持的文件` : ''}；导入时会保留文件夹相对路径。`;
      }
    };

    // 起草文书由专用入口导入，文件名即为标题和来源，不要求用户重复填写元数据。
    const syncKnowledgeImportMode = () => {
      const drafting = typeSelect?.value === 'drafting_materials';
      const typeField = form?.querySelector('[data-knowledge-type-field]');
      const metadataFields = form ? [...form.querySelectorAll('[data-knowledge-metadata]')] : [];
      if (typeField) typeField.hidden = drafting;
      metadataFields.forEach((field) => {
        field.hidden = drafting;
        field.querySelectorAll('input, select, textarea').forEach((input) => {
          if (!input.dataset.knowledgeRequired) input.dataset.knowledgeRequired = String(input.required);
          input.disabled = drafting;
          input.required = drafting ? false : input.dataset.knowledgeRequired === 'true';
        });
      });
      dialog?.classList.toggle('is-drafting-import', drafting);
      if (knowledgeImportStatus) {
        knowledgeImportStatus.classList.remove('is-error');
        knowledgeImportStatus.textContent = drafting ? directDraftingStatus : defaultImportStatus;
      }
    };
    document.querySelector('#close-knowledge-preview')?.addEventListener('click', () => document.querySelector('#knowledge-preview-dialog')?.close());
    document.querySelector('#open-knowledge-dialog').addEventListener('click', async () => {
      if (dialog.dataset.allowed === 'false') return;
      if (typeSelect) typeSelect.value = 'company_profile';
      if (dialogTitle) dialogTitle.textContent = '导入公司资料';
      syncKnowledgeImportMode();
      try { await loadKnowledgeCategories(); } catch (error) { showToast(error.message); }
      dialog.showModal();
    });
    const openDraftingMaterialDialog = () => {
      if (dialog.dataset.allowed === 'false') return;
      if (typeSelect) typeSelect.value = 'drafting_materials';
      if (dialogTitle) dialogTitle.textContent = '导入起草文书资料';
      syncKnowledgeImportMode();
      dialog.showModal();
    };
    document.querySelectorAll('#open-drafting-material-dialog, #open-drafting-material-dialog-drafting').forEach((button) => {
      button.addEventListener('click', openDraftingMaterialDialog);
    });
    typeSelect?.addEventListener('change', () => {
      if (dialogTitle) {
        dialogTitle.textContent = typeSelect.value === 'drafting_materials'
          ? '导入起草文书资料'
          : '导入公司资料';
      }
      syncKnowledgeImportMode();
    });
    document.querySelector('#close-knowledge-dialog').addEventListener('click', () => dialog.close());
    document.querySelector('#cancel-knowledge-dialog').addEventListener('click', () => dialog.close());
    fileInput?.addEventListener('change', renderKnowledgeFileSelection);
    folderInput?.addEventListener('change', renderKnowledgeFileSelection);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const draftingImport = typeSelect?.value === 'drafting_materials';
      const files = getKnowledgeFiles();
      const importStatus = document.querySelector('#knowledge-import-status');
      if (!files.length) {
        importStatus.textContent = '请选择至少一份 PDF、Word、XLS/XLSX、CSV、TXT、MD 或 JSON 文件。';
        importStatus.classList.add('is-error');
        return;
      }
      // A folder is a single import operation.  Avoid forcing the operator to
      // type a separate source before all files can be queued.
      const sourceInput = form.elements.source;
      const folderImport = Boolean(folderInput?.files?.length);
      if (folderImport && sourceInput && !String(sourceInput.value || '').trim()) sourceInput.value = '本地文件夹导入';
      if (!form.reportValidity()) return;
      const submit = document.querySelector('#submit-knowledge');
      submit.disabled = true;
      try {
        const metadata = new FormData(form);
        let imported = 0;
        let skipped = 0;
        const failures = [];
        for (let index = 0; index < files.length; index += 1) {
          importStatus.classList.remove('is-error');
          const currentFile = files[index].file;
          const relativePath = files[index].relativePath;
          importStatus.textContent = `正在导入 ${index + 1} / ${files.length}：${relativePath}`;
          const payload = new FormData();
          for (const [key, value] of metadata.entries()) {
            if (typeof value !== 'string') continue;
            payload.append(key, key === 'title' && (files.length > 1 || folderImport)
              ? relativePath.replace(/\.[^.]+$/, '')
              : value);
          }
          payload.set('relative_path', relativePath);
          if (draftingImport) {
            const fileTitle = relativePath.replace(/\.[^.]+$/, '');
            payload.set('document_type', 'drafting_materials');
            payload.set('title', fileTitle);
            payload.set('source', relativePath);
            payload.set('source_type', 'uploaded_drafting_material');
            payload.set('source_name', relativePath);
          }
          payload.append('document', currentFile, currentFile.name);
          try {
            const result = await apiFetch('/api/knowledge/import', { method: 'POST', body: payload });
            if (result.status === 'skipped') skipped += 1;
            else imported += 1;
          } catch (error) {
            failures.push(`${relativePath}：${error.message}`);
          }
        }
        if (failures.length) {
          importStatus.textContent = `导入完成：新增 ${imported}，跳过重复 ${skipped}，失败 ${failures.length}。${failures.slice(0, 3).join('；')}${failures.length > 3 ? '；其余失败文件请稍后重试。' : ''}`;
          importStatus.classList.add('is-error');
          showToast(`文件夹导入完成，但有 ${failures.length} 个文件失败`);
        } else {
          dialog.close();
          form.reset();
          if (knowledgeFileSelection) knowledgeFileSelection.textContent = '尚未选择文件。选择文件夹后，系统会列出并逐份导入其中的支持文件。';
          importStatus.textContent = defaultImportStatus;
          importStatus.classList.remove('is-error');
          syncKnowledgeImportMode();
          showToast(`知识导入完成：新增 ${imported}，跳过重复 ${skipped}`);
        }
        await loadKnowledge();
      } catch (error) {
        importStatus.textContent = error.message;
        importStatus.classList.add('is-error');
        showToast(error.message);
      }
      finally { submit.disabled = false; }
    });
  }

  async function loadAudit() {
    if (!platformState.connected || !platformState.permissions.includes('audit')) return;
    const payload = await apiFetch('/api/audit?limit=150');
    const logs = payload.logs || [];
    document.querySelector('#audit-table-body').innerHTML = logs.length ? logs.map((log) => `<tr><td>${escapeHtml(formatDataTimestamp(log.created_at))}</td><td>${escapeHtml(log.display_name || log.username || '系统')}</td><td><strong>${escapeHtml(log.action)}</strong></td><td>${escapeHtml(log.resource_type)}<small class="table-subline">${escapeHtml(log.resource_id || '')}</small></td><td>${escapeHtml(log.ip || '本机')}</td></tr>`).join('') : '<tr><td colspan="5"><div class="table-empty"><strong>暂无审计记录</strong></div></td></tr>';
  }

  function initAuditControls() {
    document.querySelector('#refresh-audit').addEventListener('click', () => loadAudit().catch((error) => showToast(error.message)));
  }

  async function loadUsage() {
    if (!platformState.connected || !platformState.permissions.includes('audit')) return;
    const payload = await apiFetch('/api/usage');
    usageRates = { input: Number(payload.rates?.input || 0), output: Number(payload.rates?.output || 0) };
    usageRecords = (payload.records || []).map((record) => ({
      date: record.date,
      analyses: Number(record.analyses || 0),
      inputTokens: Number(record.input_tokens || 0),
      outputTokens: Number(record.output_tokens || 0)
    }));
    document.querySelector('.usage-status-band strong').textContent = `${payload.environment || 'development'} 实际记录`;
    const rateValues = document.querySelectorAll('.usage-rate-list strong');
    rateValues[0].textContent = `¥${usageRates.input.toFixed(2)}`;
    rateValues[1].textContent = `¥${usageRates.output.toFixed(2)}`;
    renderUsage();
  }

  function initReportControls() {
    document.querySelector('#export-all-reports').addEventListener('click', () => {
      if (!currentReviewTaskId) {
        showToast('请先从审查任务中打开需要导出的任务');
        return;
      }
      exportReviewReport(currentReviewTaskId);
    });
  }

  function getActiveAnnouncementData() {
    if (announcementSource !== 'peer') return companyData;
    return peerData.companies?.find((item) => item.company?.secCode === selectedPeerCode) || peerData.companies?.[0] || { categories: [], announcements: [], stats: {}, company: {} };
  }

  function resetAnnouncementFilters() {
    announcementCategory = 'all';
    announcementYear = 'all';
    announcementScope = 'all';
    announcementPage = 1;
    document.querySelector('#announcement-search').value = '';
    document.querySelector('#announcement-sort').value = 'newest';
    document.querySelectorAll('[data-announcement-scope]').forEach((item) => item.classList.toggle('is-active', item.dataset.announcementScope === 'all'));
  }

  function renderDataOverview() {
    const announcements = companyData.announcements ?? [];
    const stats = companyData.stats ?? {};
    const latest = announcements[0];
    const peerTotal = (peerData.companies ?? []).reduce((total, item) => total + Number(item.stats?.total || item.announcements?.length || 0), 0);
    document.querySelector('#announcement-total').textContent = Number(stats.total || announcements.length).toLocaleString('zh-CN');
    document.querySelector('#peer-announcement-total').textContent = peerTotal ? peerTotal.toLocaleString('zh-CN') : '待同步';
    document.querySelector('#peer-announcement-note').textContent = peerData.companies?.length ? `${peerData.companies.length} 家公开信息对比参考` : '等待对标公司同步';
    document.querySelector('#data-rule-total').textContent = data.records.length.toLocaleString('zh-CN');
    document.querySelector('#csrc-rule-total').textContent = csrcData.records.length ? csrcData.records.length.toLocaleString('zh-CN') : '待同步';
    document.querySelector('#announcement-range').textContent = stats.earliestAt && stats.latestAt ? `${stats.earliestAt} 至 ${stats.latestAt}` : '等待同步历史公告';
    document.querySelector('#latest-announcement-date').textContent = stats.latestAt || '待同步';
    document.querySelector('#latest-announcement-name').textContent = latest?.title || '以巨潮资讯公开披露为准';
    document.querySelector('#company-sync-meta').textContent = `本地版本 ${formatDataTimestamp(companyData.generatedAt)} · ${announcements.length.toLocaleString('zh-CN')} 条`;
    document.querySelector('#peer-sync-meta').textContent = peerData.companies?.length ? `本地版本 ${formatDataTimestamp(peerData.generatedAt)} · ${peerTotal.toLocaleString('zh-CN')} 条` : '等待本地同步数据';
    document.querySelector('#rules-sync-meta').textContent = `本地版本 ${formatDataTimestamp(data.generatedAt)} · ${data.records.length.toLocaleString('zh-CN')} 条`;
    document.querySelector('#csrc-sync-meta').textContent = csrcData.records.length ? `本地版本 ${formatDataTimestamp(csrcData.generatedAt)} · ${csrcData.records.length.toLocaleString('zh-CN')} 条` : '等待本地同步数据';
    updateSourceHealth(document.querySelector('#company-source-health'), isFreshData(companyData.generatedAt));
    updateSourceHealth(document.querySelector('#peer-source-health'), isFreshData(peerData.generatedAt));
    updateSourceHealth(document.querySelector('#rules-source-health'), isFreshData(data.generatedAt));
    updateSourceHealth(document.querySelector('#csrc-source-health'), isFreshData(csrcData.generatedAt));
  }

  function renderPeerCompanySwitch() {
    const root = document.querySelector('#peer-company-switch');
    const isPeer = announcementSource === 'peer';
    root.hidden = !isPeer;
    if (!isPeer) return;
    const companies = peerData.companies ?? [];
    if (!companies.length) {
      root.innerHTML = '<span>尚未同步对标公司公告。</span>';
      return;
    }
    root.innerHTML = `<span>选择公司</span>${companies.map((item) => {
      const code = item.company?.secCode || '';
      const name = item.company?.secName || `证券代码 ${code}`;
      return `<button type="button" class="${code === selectedPeerCode ? 'is-active' : ''}" data-peer-code="${escapeHtml(code)}">${escapeHtml(name)} · ${escapeHtml(code)}</button>`;
    }).join('')}`;
    root.querySelectorAll('[data-peer-code]').forEach((button) => button.addEventListener('click', () => {
      selectedPeerCode = button.dataset.peerCode;
      resetAnnouncementFilters();
      renderPeerCompanySwitch();
      renderAnnouncementTaxonomy();
      renderAnnouncements();
    }));
  }

  function renderAnnouncementTaxonomy() {
    const activeData = getActiveAnnouncementData();
    const categoriesRoot = document.querySelector('#announcement-categories');
    const categories = (activeData.categories ?? []).filter((category) => category.count > 0);
    const isPeer = announcementSource === 'peer';
    document.querySelector('#announcement-taxonomy-title').textContent = isPeer ? '对标公告分类' : '公告分类';
    document.querySelector('#category-count-all').textContent = Number(activeData.stats?.total || activeData.announcements?.length || 0).toLocaleString('zh-CN');
    document.querySelector('#announcement-source-note').textContent = isPeer
      ? (peerData.note || '对标资料仅作公开信息对比参考，不作为创业黑马事实或审批依据。')
      : (companyData.note || '创业黑马公司公开披露公告索引。');
    document.querySelector('#company-data-note').textContent = isPeer
      ? (peerData.note || '对标资料仅作公开信息对比参考，不作为创业黑马事实或审批依据。')
      : (companyData.note || '公告正文、披露时间及效力以巨潮资讯网原始 PDF 为准。');
    categoriesRoot.innerHTML = categories.map((category) => `
      <button class="announcement-category ${announcementCategory === category.id ? 'is-active' : ''}" type="button" data-announcement-category="${escapeHtml(category.id)}">
        <span>${escapeHtml(category.name)}</span><small>${Number(category.count).toLocaleString('zh-CN')}</small>
      </button>`).join('');

    const allButton = document.querySelector('[data-announcement-category="all"]');
    allButton.classList.toggle('is-active', announcementCategory === 'all');
    allButton.onclick = () => {
      announcementCategory = 'all';
      announcementPage = 1;
      renderAnnouncementTaxonomy();
      renderAnnouncements();
    };
    categoriesRoot.querySelectorAll('[data-announcement-category]').forEach((button) => {
      button.addEventListener('click', () => {
        announcementCategory = button.dataset.announcementCategory;
        announcementPage = 1;
        renderAnnouncementTaxonomy();
        renderAnnouncements();
      });
    });

    const years = Object.entries(activeData.stats?.yearlyCounts ?? {}).sort((left, right) => Number(right[0]) - Number(left[0]));
    document.querySelector('#announcement-years').innerHTML = years.map(([year, count]) => `<button class="year-chip ${String(announcementYear) === String(year) ? 'is-active' : ''}" type="button" data-announcement-year="${year}">${year} <small>${count}</small></button>`).join('');
    const yearSelect = document.querySelector('#announcement-year-select');
    yearSelect.innerHTML = '<option value="all">全部年度</option>' + years.map(([year, count]) => `<option value="${year}">${year} 年（${count}）</option>`).join('');
    yearSelect.value = String(announcementYear);
    document.querySelectorAll('[data-announcement-year]').forEach((button) => button.addEventListener('click', () => {
      announcementYear = button.dataset.announcementYear;
      announcementPage = 1;
      renderAnnouncementTaxonomy();
      renderAnnouncements();
    }));
  }

  function getFilteredAnnouncements() {
    const activeData = getActiveAnnouncementData();
    const keyword = document.querySelector('#announcement-search').value.trim().toLowerCase();
    const sort = document.querySelector('#announcement-sort').value;
    const filtered = (activeData.announcements ?? []).filter((announcement) => {
      const categoryMatch = announcementCategory === 'all' || announcement.categoryId === announcementCategory;
      const yearMatch = announcementYear === 'all' || String(announcement.year) === String(announcementYear);
      const scopeMatch = announcementScope === 'all' || announcement.isPeriodic;
      const keywordMatch = !keyword || `${announcement.title} ${announcement.categoryName} ${announcement.publishedAt}`.toLowerCase().includes(keyword);
      return categoryMatch && yearMatch && scopeMatch && keywordMatch;
    });
    filtered.sort((left, right) => sort === 'oldest'
      ? left.publishedAt.localeCompare(right.publishedAt) || left.id.localeCompare(right.id)
      : right.publishedAt.localeCompare(left.publishedAt) || right.id.localeCompare(left.id));
    return filtered;
  }

  function renderAnnouncements() {
    const activeData = getActiveAnnouncementData();
    const isPeer = announcementSource === 'peer';
    const announcements = getFilteredAnnouncements();
    const totalPages = Math.max(1, Math.ceil(announcements.length / announcementPageSize));
    announcementPage = Math.min(announcementPage, totalPages);
    const pageRecords = announcements.slice((announcementPage - 1) * announcementPageSize, announcementPage * announcementPageSize);
    const list = document.querySelector('#announcement-list');
    const empty = document.querySelector('#announcement-empty');
    const pagination = document.querySelector('#announcement-pagination');
    document.querySelector('#announcement-result-count').textContent = announcements.length.toLocaleString('zh-CN');
    document.querySelector('#announcement-page-current').textContent = announcementPage;
    document.querySelector('#announcement-page-total').textContent = totalPages;
    document.querySelector('#announcement-page-prev').disabled = announcementPage <= 1;
    document.querySelector('#announcement-page-next').disabled = announcementPage >= totalPages;
    empty.hidden = announcements.length !== 0;
    list.hidden = announcements.length === 0;
    pagination.hidden = announcements.length === 0;
    list.innerHTML = pageRecords.map((announcement) => {
      const [year, month, day] = announcement.publishedAt.split('-');
      const pdfUrl = safeOfficialUrl(announcement.pdfUrl);
      const sourceLine = isPeer
        ? `${activeData.company?.secName || activeData.company?.secCode || '对标公司'} · 公告 ID ${announcement.id} · 仅作对比参考`
        : `公告 ID ${announcement.id} · ${announcement.source}`;
      return `<article class="announcement-row">
        <time class="announcement-date" datetime="${escapeHtml(announcement.publishedAt)}"><strong>${month}-${day}</strong><span>${year}</span></time>
        <span class="announcement-type ${announcement.isPeriodic ? 'periodic' : ''}">${escapeHtml(announcement.categoryName)}</span>
        <div class="announcement-main"><a href="${pdfUrl}" target="_blank" rel="noreferrer">${escapeHtml(announcement.title)}</a><small>${escapeHtml(sourceLine)}</small></div>
        <span class="announcement-size">${escapeHtml(formatAnnouncementSize(announcement.sizeKB))}</span>
        <a class="announcement-open" href="${pdfUrl}" target="_blank" rel="noreferrer" aria-label="打开${escapeHtml(announcement.title)}" data-tip="打开官方 PDF"><i data-lucide="external-link" aria-hidden="true"></i></a>
      </article>`;
    }).join('');
    refreshIcons();
  }

  function initDataCenter() {
    renderDataOverview();
    renderPeerCompanySwitch();
    renderAnnouncementTaxonomy();
    renderAnnouncements();
    document.querySelectorAll('[data-announcement-source]').forEach((button) => button.addEventListener('click', () => {
      announcementSource = button.dataset.announcementSource;
      resetAnnouncementFilters();
      document.querySelectorAll('[data-announcement-source]').forEach((item) => item.classList.toggle('is-active', item === button));
      renderPeerCompanySwitch();
      renderAnnouncementTaxonomy();
      renderAnnouncements();
    }));
    document.querySelector('#announcement-search').addEventListener('input', () => { announcementPage = 1; renderAnnouncements(); });
    document.querySelector('#announcement-year-select').addEventListener('change', (event) => {
      announcementYear = event.target.value;
      announcementPage = 1;
      renderAnnouncementTaxonomy();
      renderAnnouncements();
    });
    document.querySelector('#announcement-sort').addEventListener('change', () => { announcementPage = 1; renderAnnouncements(); });
    document.querySelectorAll('[data-announcement-scope]').forEach((button) => button.addEventListener('click', () => {
      announcementScope = button.dataset.announcementScope;
      announcementPage = 1;
      document.querySelectorAll('[data-announcement-scope]').forEach((item) => item.classList.toggle('is-active', item === button));
      renderAnnouncements();
    }));
    document.querySelector('#announcement-page-prev').addEventListener('click', () => { announcementPage = Math.max(1, announcementPage - 1); renderAnnouncements(); });
    document.querySelector('#announcement-page-next').addEventListener('click', () => { announcementPage += 1; renderAnnouncements(); });
    document.querySelector('#clear-announcement-filter').addEventListener('click', () => {
      resetAnnouncementFilters();
      renderAnnouncementTaxonomy();
      renderAnnouncements();
    });
    document.querySelector('#reload-data-page').addEventListener('click', () => location.reload());
  }

  function isRuleSaved(rule) {
    return savedRules.has(rule.uid) || (rule.sourceType === 'szse' && savedRules.has(rule.id));
  }

  function ruleStatusMeta(rule) {
    const status = rule.sourceStatus;
    if (status === 'repealed-list' || status === 'repealed') return { label: status === 'repealed' ? '已被废止' : '废止清单', chip: 'repealed', icon: 'archive-x' };
    if (status === 'current-effective') return { label: '现行有效', chip: 'official', icon: 'badge-check' };
    if (status === 'pending-effective') return { label: '未施行', chip: 'medium', icon: 'clock-3' };
    if (status === 'amended') return { label: '已被修改', chip: 'neutral', icon: 'file-pen-line' };
    if (status === 'draft-consultation') return { label: '征求意见稿', chip: 'neutral', icon: 'message-square-warning' };
    if (status === 'official-interpretation') return { label: '官方解读', chip: 'neutral', icon: 'book-open-check' };
    if (status === 'official-published') return { label: '正式发布', chip: 'official', icon: 'badge-check' };
    return { label: '官网收录', chip: 'official', icon: 'file-text' };
  }

  function initRuleSourceMeta() {
    const notes = [data.note, csrcData.note, mofData.note].filter(Boolean);
    document.querySelector('#source-note').textContent = `${notes.join(' ')} 当前本地索引：深交所 ${data.records.length} 条，证监会 ${csrcData.records.length} 条，财政部会计司 ${mofData.records.length} 条。`;
    const mofTotal = document.querySelector('#mof-rule-total');
    if (mofTotal) mofTotal.textContent = mofData.records.length.toLocaleString('zh-CN');
    const timestamps = [data.generatedAt, csrcData.generatedAt, mofData.generatedAt].filter(Boolean).map((value) => new Date(value).getTime()).filter(Number.isFinite);
    if (timestamps.length) document.querySelector('#rules-generated-at').textContent = `最近同步 ${new Date(Math.max(...timestamps)).toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' }).replaceAll('/', '-')}`;
  }

  function renderTaxonomy() {
    const root = document.querySelector('#rule-taxonomy');
    const visibleCategories = ruleCategories.filter((category) => selectedRuleSource === 'all' || category.sourceType === selectedRuleSource);
    const grouped = visibleCategories.reduce((map, category) => {
      if (!map.has(category.group)) map.set(category.group, []);
      map.get(category.group).push(category);
      return map;
    }, new Map());
    root.innerHTML = [...grouped.entries()].map(([group, categories]) => `
      <div class="taxonomy-group">
        <strong>${escapeHtml(group)}</strong>
        <div class="taxonomy-list">
          ${categories.map((category) => `
            <button type="button" class="taxonomy-item ${selectedCategory === category.id ? 'is-active' : ''}" data-category-id="${escapeHtml(category.id)}">
              <span>${escapeHtml(category.name)}</span><small>${category.count == null ? '—' : category.count}</small>
            </button>
          `).join('')}
        </div>
      </div>
    `).join('') || '<div class="detail-placeholder"><strong>等待规则数据</strong><span>运行数据更新后即可浏览官方索引。</span></div>';
    root.querySelectorAll('[data-category-id]').forEach((button) => {
      button.addEventListener('click', () => {
        selectedCategory = button.dataset.categoryId;
        selectedRulePreset = 'all';
        document.querySelectorAll('[data-rule-preset]').forEach((item) => item.classList.remove('is-active'));
        rulePage = 1;
        renderTaxonomy();
        renderRuleList();
      });
    });
  }

  function getFilteredRules() {
    const keyword = document.querySelector('#rule-search').value.trim().toLowerCase();
    const status = document.querySelector('#rule-status-filter').value;
    const sort = document.querySelector('#rule-sort').value;
    const filtered = rules.filter((rule) => {
      const matchesSource = selectedRuleSource === 'all' || rule.sourceType === selectedRuleSource;
      const matchesCategory = selectedCategory === 'all' || rule.categories.some((category) => category.id === selectedCategory);
      const matchesPreset = selectedRulePreset === 'all' || (rule.reviewScopes ?? []).includes(selectedRulePreset);
      const haystack = [rule.title, rule.summary, rule.navigation, rule.fileNumber, rule.body, ...rule.categories.map((category) => `${category.group} ${category.name}`)].join(' ').toLowerCase();
      const matchesKeyword = !keyword || haystack.includes(keyword);
      const matchesStatus = status === 'all' || (status === 'saved' ? isRuleSaved(rule) : rule.sourceStatus === status);
      return matchesSource && matchesCategory && matchesPreset && matchesKeyword && matchesStatus;
    });
    filtered.sort((left, right) => {
      if (sort === 'oldest') return String(left.publishedAt || '').localeCompare(String(right.publishedAt || ''));
      if (sort === 'title') return left.title.localeCompare(right.title, 'zh-CN');
      return String(right.publishedAt || '').localeCompare(String(left.publishedAt || ''));
    });
    return filtered;
  }

  function renderRuleList() {
    const visibleRules = getFilteredRules();
    const totalPages = Math.max(1, Math.ceil(visibleRules.length / rulePageSize));
    rulePage = Math.min(rulePage, totalPages);
    const pageRules = visibleRules.slice((rulePage - 1) * rulePageSize, rulePage * rulePageSize);
    const list = document.querySelector('#rule-list');
    const empty = document.querySelector('#rule-empty');
    const pagination = document.querySelector('#rule-pagination');
    document.querySelector('#rule-result-count').textContent = visibleRules.length.toLocaleString('zh-CN');
    document.querySelector('#rule-page-current').textContent = rulePage;
    document.querySelector('#rule-page-total').textContent = totalPages;
    document.querySelector('#rule-page-prev').disabled = rulePage <= 1;
    document.querySelector('#rule-page-next').disabled = rulePage >= totalPages;
    const category = ruleCategories.find((item) => item.id === selectedCategory);
    document.querySelector('#active-category-name').textContent = `· ${rulePresetLabel(selectedRulePreset) || category?.name || (selectedRuleSource === 'all' ? '全部分类' : selectedRuleSource === 'csrc' ? '证监会官方' : selectedRuleSource === 'mof' ? '财政部会计司' : '深交所')}`;
    empty.hidden = visibleRules.length !== 0;
    list.hidden = visibleRules.length === 0;
    pagination.hidden = visibleRules.length === 0;
    if (pageRules.length && !pageRules.some((rule) => rule.uid === selectedRuleId)) selectedRuleId = pageRules[0].uid;
    if (!visibleRules.length) selectedRuleId = null;
    list.innerHTML = pageRules.map((rule) => {
      const status = ruleStatusMeta(rule);
      const saved = isRuleSaved(rule);
      const periodicReportRule = (rule.reviewScopes ?? []).includes('periodic-report');
      const financialAccountingRule = (rule.reviewScopes ?? []).includes('financial-accounting');
      const primaryCategory = rule.categories[0];
      const sourceLabel = rule.issuingAuthority || (rule.sourceType === 'csrc' ? '证监会官方' : rule.sourceType === 'mof' ? '财政部会计司' : '深交所官网收录');
      return `
        <button type="button" class="rule-row ${selectedRuleId === rule.uid ? 'is-active' : ''}" data-rule-id="${escapeHtml(rule.uid)}">
          <i data-lucide="${status.icon}" aria-hidden="true"></i>
          <span class="rule-row-main">
            <strong>${escapeHtml(rule.title)}</strong>
            <span class="rule-row-meta">
              <span>${escapeHtml(sourceLabel)}</span><span>·</span><span>${escapeHtml(primaryCategory?.name || '')}</span>
              ${periodicReportRule ? '<span>·</span><span class="periodic-rule-label">定期报告审查</span>' : ''}
              ${financialAccountingRule ? '<span>·</span><span class="financial-rule-label">财务会计审查</span>' : ''}
              ${saved ? '<span>·</span><span><i data-lucide="bookmark-check" aria-hidden="true"></i>已加入规则包</span>' : ''}
            </span>
          </span>
          <span class="rule-row-side">
            <span class="status-chip ${status.chip}">${status.label}</span>
            <time>${escapeHtml(rule.publishedAt || '日期待确认')}</time>
          </span>
        </button>`;
    }).join('');
    list.querySelectorAll('[data-rule-id]').forEach((button) => button.addEventListener('click', () => {
      selectedRuleId = button.dataset.ruleId;
      renderRuleList();
    }));
    renderRuleDetail();
    refreshIcons();
  }

  function renderRuleDetail() {
    const panel = document.querySelector('#rule-detail');
    const rule = rules.find((item) => item.uid === selectedRuleId);
    if (!rule) {
      panel.innerHTML = '<div class="detail-placeholder"><i data-lucide="mouse-pointer-click" aria-hidden="true"></i><strong>选择一条规则</strong><span>查看来源、效力状态和官方原文入口。</span></div>';
      return;
    }
    const status = ruleStatusMeta(rule);
    const saved = isRuleSaved(rule);
    const periodicReportRule = (rule.reviewScopes ?? []).includes('periodic-report');
    const financialAccountingRule = (rule.reviewScopes ?? []).includes('financial-accounting');
    const bodyMarkup = rule.bodyStatus === 'full-text' && (rule.body || rule.sections?.length)
      ? `<section class="rule-detail-section rule-full-text-section"><span class="detail-label">官方正文（本地同步副本）</span>${rule.body ? `<p class="rule-full-text">${escapeHtml(rule.body)}</p>` : ''}${(rule.sections ?? []).map((section) => `<div class="rule-text-section"><strong>${escapeHtml(section.title || '正文')}</strong><p>${escapeHtml(section.content)}</p></div>`).join('')}</section>`
      : rule.sourceType === 'csrc' ? '<section class="rule-detail-section"><span class="detail-label">正文状态</span><p>本次仅获得目录信息，请打开官方原文核对完整内容。</p></section>' : '';
    panel.innerHTML = `
      <div class="rule-detail-content">
        <header class="rule-detail-head">
          <div class="detail-kickers">
            <span class="status-chip ${status.chip}">${escapeHtml(rule.statusLabel || status.label)}</span>
            <span class="category-tag">${escapeHtml(rule.issuingAuthority || (rule.sourceType === 'csrc' ? '中国证监会' : rule.sourceType === 'mof' ? '财政部会计司' : '深交所官网收录'))}</span>
            ${periodicReportRule ? '<span class="category-tag periodic-rule-tag">定期报告审查</span>' : ''}
            ${financialAccountingRule ? '<span class="category-tag financial-rule-tag">财务会计审查</span>' : ''}
            ${rule.categories.map((category) => `<span class="category-tag">${escapeHtml(category.name)}</span>`).join('')}
          </div>
          <h3>${escapeHtml(rule.title)}</h3>
        </header>
        <section class="rule-detail-section">
          <span class="detail-label">摘要</span>
          <p>${escapeHtml(rule.summary || '官方目录未提供可检索摘要，请打开官方原文查看完整内容。')}</p>
        </section>
        <section class="rule-detail-section">
          <span class="detail-label">来源信息</span>
          <div class="detail-meta-list">
            <div class="detail-meta-row"><span>发布机构</span><strong>${escapeHtml(rule.issuingAuthority || rule.source || (rule.sourceType === 'csrc' ? '中国证券监督管理委员会' : rule.sourceType === 'mof' ? '财政部会计司' : '发布机关待官方原文确认'))}</strong></div>
            <div class="detail-meta-row"><span>发布日期</span><strong>${escapeHtml(rule.publishedAt || '待确认')}</strong></div>
            ${rule.effectiveAt ? `<div class="detail-meta-row"><span>生效日期</span><strong>${escapeHtml(rule.effectiveAt)}</strong></div>` : ''}
            ${rule.fileNumber ? `<div class="detail-meta-row"><span>文号</span><strong>${escapeHtml(rule.fileNumber)}</strong></div>` : ''}
            <div class="detail-meta-row"><span>来源范围</span><strong>${escapeHtml(rule.navigation || rule.categories.map((category) => category.name).join('、') || '官方法规库')}</strong></div>
          </div>
        </section>
        ${bodyMarkup}
        <div class="detail-actions">
          <button class="button ${saved ? '' : 'button-primary'}" type="button" id="toggle-saved-rule">
            <i data-lucide="${saved ? 'bookmark-x' : 'bookmark-plus'}" aria-hidden="true"></i>${saved ? '移出规则包' : '加入审查规则包'}
          </button>
          ${rule.sourceType === 'szse' && /20\d{2}/.test(String(rule.title || '')) ? `<button class="button" type="button" id="compare-rule-versions"><i data-lucide="git-compare-arrows" aria-hidden="true"></i>版本对比</button>` : ''}
          <a class="button" href="${safeOfficialUrl(rule.url)}" target="_blank" rel="noreferrer"><i data-lucide="external-link" aria-hidden="true"></i>打开官方原文</a>
        </div>
      </div>`;
    panel.querySelector('#toggle-saved-rule').addEventListener('click', () => toggleSavedRule(rule));
    panel.querySelector('#compare-rule-versions')?.addEventListener('click', () => openRuleCompare(rule));
    refreshIcons();
  }

  function ruleCompareChangeLabel(changeType) {
    return ({ added: '新增条款', removed: '删除条款', modified: '条款修改' })[changeType] || '条款变化';
  }

  function ruleCompareYearFromTitle(title, fallback) {
    const match = String(title || '').match(/20\d{2}/);
    return match ? match[0] : String(fallback);
  }

  function renderRuleCompareDiff(segments) {
    return (Array.isArray(segments) ? segments : []).map((segment) => {
      const type = segment?.type === 'added' ? 'added' : (segment?.type === 'removed' ? 'removed' : 'equal');
      return `<span class="rule-diff-${type}">${escapeHtml(segment?.text || '')}</span>`;
    }).join('') || '<span class="rule-diff-equal">未生成差异片段，请对照前后文本。</span>';
  }

  function renderRuleComparison(payload) {
    currentRuleComparisonPayload = payload;
    const reportButton = document.querySelector('#download-rule-compare-report');
    if (reportButton) reportButton.disabled = false;
    const summary = payload.summary || {};
    const summaryNode = document.querySelector('#rule-compare-summary');
    const resultsNode = document.querySelector('#rule-compare-results');
    if (!summaryNode || !resultsNode) return;
    summaryNode.innerHTML = `
      <div><strong>${escapeHtml(payload.family || '规则版本')}</strong><span>${escapeHtml(payload.oldVersion?.version || '')} → ${escapeHtml(payload.newVersion?.version || '')}</span></div>
      <div class="rule-compare-counts"><span class="is-added">新增 ${Number(summary.added || 0)}</span><span class="is-removed">删除 ${Number(summary.removed || 0)}</span><span class="is-modified">修改 ${Number(summary.modified || 0)}</span><span>相同 ${Number(summary.unchanged || 0)}</span></div>`;
    const changes = Array.isArray(payload.changes) ? payload.changes : [];
    resultsNode.innerHTML = changes.length ? changes.map((change) => {
      const type = ['added', 'removed', 'modified'].includes(change.changeType) ? change.changeType : 'modified';
      const oldSource = payload.oldVersion?.localUrl || payload.oldVersion?.sourceUrl || '';
      const newSource = payload.newVersion?.localUrl || payload.newVersion?.sourceUrl || '';
      const oldLocation = [change.oldPage ? `第 ${change.oldPage} 页` : '', change.oldSection || ''].filter(Boolean).join(' · ') || '位置待确认';
      const newLocation = [change.newPage ? `第 ${change.newPage} 页` : '', change.newSection || ''].filter(Boolean).join(' · ') || '位置待确认';
      return `<article class="rule-compare-card is-${type}">
        <header class="rule-compare-card-head"><span class="rule-compare-badge">${ruleCompareChangeLabel(type)}</span><strong>${escapeHtml(change.articleLabel || change.article || '条款')}</strong></header>
        <div class="rule-compare-locations"><span>旧版：${escapeHtml(oldLocation)}</span><span>新版：${escapeHtml(newLocation)}</span></div>
        <div class="rule-compare-panes">
          <section class="rule-compare-pane old"><span class="detail-label">旧版原文（${escapeHtml(payload.oldVersion?.version || '旧版')}）</span><p>${escapeHtml(change.oldText || '（旧版无此条款）')}</p></section>
          <section class="rule-compare-pane new"><span class="detail-label">新版原文（${escapeHtml(payload.newVersion?.version || '新版')}）</span><p>${escapeHtml(change.newText || '（新版已删除此条款）')}</p></section>
        </div>
        ${type === 'modified' ? `<section class="rule-compare-diff"><span class="detail-label">新版修订标注</span><p>${renderRuleCompareDiff(change.diff)}</p></section>` : ''}
        <div class="rule-compare-links">${type !== 'added' && oldSource && oldSource !== '#' ? `<a href="${safeCitationUrl(oldSource)}" target="_blank" rel="noreferrer"><i data-lucide="file-text" aria-hidden="true"></i>打开旧版原文</a>` : ''}${type !== 'removed' && newSource && newSource !== '#' ? `<a href="${safeCitationUrl(newSource)}" target="_blank" rel="noreferrer"><i data-lucide="file-text" aria-hidden="true"></i>打开新版原文</a>` : ''}</div>
      </article>`;
    }).join('') : '<div class="review-empty-result"><i data-lucide="check-circle-2" aria-hidden="true"></i><strong>两个版本的条款内容没有差异</strong></div>';
    const note = document.querySelector('#rule-compare-status');
    if (note) note.textContent = payload.note || '差异来自本地规则正文解析。';
    refreshIcons();
  }

  function reportHref(value) {
    const safe = safeCitationUrl(value);
    if (safe === '#') return '';
    return safe.startsWith('/') ? `${window.location.origin}${safe}` : safe;
  }

  function ruleCompareReportHtml(payload) {
    const summary = payload.summary || {};
    const oldVersion = payload.oldVersion || {};
    const newVersion = payload.newVersion || {};
    const changes = Array.isArray(payload.changes) ? payload.changes : [];
    const generatedAt = new Intl.DateTimeFormat('zh-CN', {
      dateStyle: 'full', timeStyle: 'medium', timeZone: 'Asia/Shanghai'
    }).format(new Date());
    const sourceLink = (label, value) => {
      const href = reportHref(value);
      return href ? `<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>` : '';
    };
    const diffMarkup = (segments) => (Array.isArray(segments) ? segments : []).map((segment) => {
      const type = segment?.type === 'added' ? 'added' : (segment?.type === 'removed' ? 'removed' : 'equal');
      return `<span class="diff-${type}">${escapeHtml(segment?.text || '')}</span>`;
    }).join('') || '<span class="diff-equal">未生成差异片段，请对照前后文本。</span>';
    const changeMarkup = changes.length ? changes.map((change, index) => {
      const type = ['added', 'removed', 'modified'].includes(change.changeType) ? change.changeType : 'modified';
      const label = ruleCompareChangeLabel(type);
      const oldLocation = [change.oldPage ? `第 ${change.oldPage} 页` : '', change.oldSection || ''].filter(Boolean).join(' · ') || '位置待确认';
      const newLocation = [change.newPage ? `第 ${change.newPage} 页` : '', change.newSection || ''].filter(Boolean).join(' · ') || '位置待确认';
      return `<article class="change change-${type}">
        <h2><span class="badge">${escapeHtml(label)}</span>${escapeHtml(change.articleLabel || change.article || `条款 ${index + 1}`)}</h2>
        <div class="locations"><div><b>旧版位置</b>${escapeHtml(oldLocation)}</div><div><b>新版位置</b>${escapeHtml(newLocation)}</div></div>
        <div class="side-by-side">
          <section class="version old"><h3>旧版原文（${escapeHtml(oldVersion.version || '旧版')}）</h3><p>${escapeHtml(change.oldText || '（旧版无此条款）')}</p></section>
          <section class="version new"><h3>新版原文（${escapeHtml(newVersion.version || '新版')}）</h3><p>${escapeHtml(change.newText || '（新版已删除此条款）')}</p></section>
        </div>
        ${type === 'modified' ? `<section class="revision"><h3>修订标注</h3><p>${diffMarkup(change.diff)}</p></section>` : ''}
        <div class="links">${type !== 'added' ? sourceLink('打开旧版原文', oldVersion.localUrl || oldVersion.sourceUrl) : ''}${type !== 'removed' ? sourceLink('打开新版原文', newVersion.localUrl || newVersion.sourceUrl) : ''}</div>
      </article>`;
    }).join('') : '<p class="empty">两个版本的条款内容没有差异。</p>';
    return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(payload.family || '规则版本')}版本对比报告</title><style>
      :root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#f3f4f6;color:#1f2937;font:15px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}main{max-width:1440px;margin:0 auto;padding:36px 28px 60px}.header,.change{background:#fff;border:1px solid #e5e7eb;border-radius:10px;box-shadow:0 2px 10px #1118270d}.header{padding:30px 36px;margin-bottom:24px}.eyebrow{color:#9f1239;font-size:12px;font-weight:700;letter-spacing:.08em}.header h1{margin:6px 0 10px;font-size:29px;line-height:1.35}.header p{margin:6px 0;color:#4b5563;font-size:16px}.meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 28px;margin:20px 0 0}.meta div{display:flex;gap:10px}.meta b{min-width:78px;color:#6b7280}.counts{display:flex;flex-wrap:wrap;gap:10px;margin-top:22px}.count{padding:6px 14px;border-radius:999px;background:#f3f4f6;font-size:14px}.count.added{color:#166534;background:#dcfce7}.count.removed{color:#991b1b;background:#fee2e2}.count.modified{color:#9a3412;background:#ffedd5}.change{padding:24px 28px;margin:16px 0;break-inside:avoid}.change h2{margin:0 0 16px;font-size:20px;line-height:1.5}.badge{display:inline-block;margin-right:10px;padding:3px 10px;border-radius:999px;background:#e5e7eb;font-size:13px;vertical-align:2px}.change-added .badge{color:#166534;background:#dcfce7}.change-removed .badge{color:#991b1b;background:#fee2e2}.change-modified .badge{color:#9a3412;background:#ffedd5}.locations{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:10px 0 18px;color:#4b5563}.locations div{padding:10px 12px;background:#f9fafb;border-left:4px solid #d1d5db;font-size:14px}.locations b{display:block;color:#6b7280;font-size:12px;margin-bottom:2px}.side-by-side{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:14px 0}.version{min-width:0;min-height:160px;padding:16px 18px;border:1px solid #d1d5db;border-radius:8px;background:#f9fafb}.version.old{border-top:5px solid #9ca3af}.version.new{border-top:5px solid #9f1239;background:#fffafb}.change h3{margin:0 0 8px;font-size:14px;color:#6b7280}.change p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:15px;line-height:1.9}.revision{padding:14px 16px;background:#fff7ed;border-left:4px solid #fb923c}.diff-added{color:#166534;background:#bbf7d0}.diff-removed{color:#991b1b;background:#fecaca;text-decoration:line-through}.diff-equal{color:#374151}.links{display:flex;flex-wrap:wrap;gap:16px;margin-top:18px}.links a{color:#9f1239;text-decoration:none;font-weight:600;font-size:14px}.empty{padding:36px;text-align:center;color:#6b7280}.footer{margin-top:30px;color:#6b7280;font-size:13px}@media(max-width:760px){main{padding:18px 12px 36px}.header{padding:22px 18px}.header h1{font-size:23px}.meta,.locations,.side-by-side{grid-template-columns:1fr}.change{padding:18px}.version{min-height:0}.counts{gap:6px}}
    </style></head><body><main><header class="header"><span class="eyebrow">RULE VERSION DIFF</span><h1>${escapeHtml(payload.family || '规则版本')}版本对比报告</h1><p>${escapeHtml(oldVersion.version || '旧版')} → ${escapeHtml(newVersion.version || '新版')}</p><dl class="meta"><div><b>旧版</b><span>${escapeHtml(oldVersion.title || payload.family || '—')} · ${escapeHtml(oldVersion.publishedAt || '发布日期待确认')}</span></div><div><b>新版</b><span>${escapeHtml(newVersion.title || payload.family || '—')} · ${escapeHtml(newVersion.publishedAt || '发布日期待确认')}</span></div><div><b>来源</b><span>${escapeHtml(newVersion.source || oldVersion.source || '官方规则库')}</span></div><div><b>生成时间</b><span>${escapeHtml(generatedAt)}（北京时间）</span></div></dl><div class="counts"><span class="count added">新增 ${Number(summary.added || 0)}</span><span class="count removed">删除 ${Number(summary.removed || 0)}</span><span class="count modified">修改 ${Number(summary.modified || 0)}</span><span class="count">相同 ${Number(summary.unchanged || 0)}</span></div></header><section>${changeMarkup}</section><footer class="footer">${escapeHtml(payload.note || '差异来自本地完整规则正文解析。')}<br>报告由本地应用生成，正式适用效力以官方现行版本为准。</footer></main></body></html>`;
  }

  function downloadRuleComparisonReport() {
    if (!currentRuleComparisonPayload) {
      showToast('请先完成规则版本比较');
      return;
    }
    const payload = currentRuleComparisonPayload;
    const html = ruleCompareReportHtml(payload);
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const oldYear = payload.oldVersion?.version || '旧版';
    const newYear = payload.newVersion?.version || '新版';
    const filename = `${String(payload.family || '规则版本').replace(/[\\/:*?"<>|]/g, '_')}_${oldYear.replace(/[^0-9-]/g, '')}-${newYear.replace(/[^0-9-]/g, '')}对比报告.html`;
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast('规则对比报告已生成');
  }

  async function loadRuleComparison(rule) {
    const dialog = document.querySelector('#rule-compare-dialog');
    const status = document.querySelector('#rule-compare-status');
    const summary = document.querySelector('#rule-compare-summary');
    const results = document.querySelector('#rule-compare-results');
    const reportButton = document.querySelector('#download-rule-compare-report');
    const submit = document.querySelector('#rule-compare-submit');
    const newYearInput = document.querySelector('#rule-compare-new-year');
    const oldYearInput = document.querySelector('#rule-compare-old-year');
    if (!dialog || !status || !summary || !results || !newYearInput || !oldYearInput) return;
    const newYear = String(newYearInput.value || '').trim();
    const oldYear = String(oldYearInput.value || '').trim();
    if (!/^20\d{2}$/.test(newYear) || !/^20\d{2}$/.test(oldYear) || newYear === oldYear) {
      status.textContent = '请选择两个不同的有效版本年份。';
      status.classList.add('is-error');
      return;
    }
    submit.disabled = true;
    status.classList.remove('is-error');
    status.textContent = '正在读取本地正文并按条款编号比较……';
    summary.innerHTML = '';
    results.innerHTML = '<div class="review-empty-result"><i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在生成差异</strong><span>首次比较会解析本地文件，后续将使用缓存。</span></div>';
    refreshIcons();
    try {
      const query = `?title=${encodeURIComponent(rule.title || '')}&new_year=${encodeURIComponent(newYear)}&old_year=${encodeURIComponent(oldYear)}`;
      const payload = await apiFetch(`/api/rules/compare${query}`);
      renderRuleComparison(payload);
    } catch (error) {
      status.textContent = error.message || '规则版本比较失败。';
      status.classList.add('is-error');
      summary.innerHTML = '';
      results.innerHTML = '<div class="review-empty-result"><i data-lucide="file-warning" aria-hidden="true"></i><strong>暂时无法完成比较</strong><span>请确认规则库已导入两个版本的完整正文。</span></div>';
      currentRuleComparisonPayload = null;
      if (reportButton) reportButton.disabled = true;
      refreshIcons();
    } finally {
      submit.disabled = false;
    }
  }

  function openRuleCompare(rule) {
    const dialog = document.querySelector('#rule-compare-dialog');
    if (!dialog) return;
    const title = document.querySelector('#rule-compare-title');
    const newYear = document.querySelector('#rule-compare-new-year');
    const oldYear = document.querySelector('#rule-compare-old-year');
    const status = document.querySelector('#rule-compare-status');
    const summary = document.querySelector('#rule-compare-summary');
    const results = document.querySelector('#rule-compare-results');
    const reportButton = document.querySelector('#download-rule-compare-report');
    const currentYear = Number(ruleCompareYearFromTitle(rule.title, 2026));
    newYear.value = String(currentYear);
    oldYear.value = String(Math.max(2000, currentYear - 1));
    title.textContent = `${rule.title || '规则'} · 版本对比`;
    status.textContent = '选择版本后点击“开始比较”。';
    status.classList.remove('is-error');
    summary.innerHTML = '';
    results.innerHTML = '<div class="review-empty-result"><i data-lucide="git-compare-arrows" aria-hidden="true"></i><strong>等待比较</strong><span>将显示新增、删除和修改的条款，并保留两版页码。</span></div>';
    currentRuleComparisonPayload = null;
    if (reportButton) reportButton.disabled = true;
    dialog.dataset.ruleTitle = rule.title || '';
    dialog.showModal();
    refreshIcons();
    newYear.focus();
  }

  function initRuleCompareControls() {
    const dialog = document.querySelector('#rule-compare-dialog');
    const form = document.querySelector('#rule-compare-form');
    const submit = document.querySelector('#rule-compare-submit');
    if (!dialog || !form || !submit) return;
    document.querySelector('#close-rule-compare')?.addEventListener('click', () => dialog.close());
    document.querySelector('#cancel-rule-compare')?.addEventListener('click', () => dialog.close());
    document.querySelector('#download-rule-compare-report')?.addEventListener('click', downloadRuleComparisonReport);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const rule = { title: dialog.dataset.ruleTitle || '' };
      loadRuleComparison(rule);
    });
  }

  function toggleSavedRule(rule) {
    if (isRuleSaved(rule)) {
      savedRules.delete(rule.uid);
      if (rule.sourceType === 'szse') savedRules.delete(rule.id);
      showToast('已从审查规则包移除');
    } else {
      savedRules.add(rule.uid);
      showToast('已加入审查规则包');
    }
    writeJson(userStorageKey(storageKeys.savedRules), [...savedRules]);
    updateRulePackCount();
    renderRuleList();
  }

  function updateRulePackCount() {
    const rulePackCount = document.querySelector('#rule-pack-count');
    if (rulePackCount) rulePackCount.textContent = rules.filter((rule) => isRuleSaved(rule)).length;
  }

  function initRuleControls() {
    const search = document.querySelector('#rule-search');
    search.addEventListener('input', () => { rulePage = 1; renderRuleList(); });
    document.querySelector('#rule-status-filter').addEventListener('change', () => { rulePage = 1; renderRuleList(); });
    document.querySelector('#rule-sort').addEventListener('change', () => { rulePage = 1; renderRuleList(); });
    document.querySelectorAll('[data-rule-source]').forEach((button) => button.addEventListener('click', () => {
      selectedRuleSource = button.dataset.ruleSource;
      selectedRulePreset = 'all';
      selectedCategory = 'all';
      selectedRuleId = null;
      rulePage = 1;
      document.querySelectorAll('[data-rule-source]').forEach((item) => item.classList.toggle('is-active', item === button));
      document.querySelectorAll('[data-rule-preset]').forEach((item) => item.classList.remove('is-active'));
      renderTaxonomy();
      renderRuleList();
    }));
    document.querySelectorAll('[data-rule-preset]').forEach((button) => button.addEventListener('click', () => {
      selectedRulePreset = button.dataset.rulePreset;
      selectedRuleSource = 'all';
      selectedCategory = 'all';
      selectedRuleId = null;
      rulePage = 1;
      search.value = '';
      document.querySelector('#rule-status-filter').value = 'all';
      document.querySelectorAll('[data-rule-source]').forEach((item) => item.classList.toggle('is-active', item.dataset.ruleSource === 'all'));
      document.querySelectorAll('[data-rule-preset]').forEach((item) => item.classList.toggle('is-active', item === button));
      renderTaxonomy();
      renderRuleList();
    }));
    document.querySelector('#rule-page-prev').addEventListener('click', () => { rulePage = Math.max(1, rulePage - 1); renderRuleList(); });
    document.querySelector('#rule-page-next').addEventListener('click', () => { rulePage += 1; renderRuleList(); });
    document.querySelector('#clear-rule-filter').addEventListener('click', () => {
      selectedRuleSource = 'all';
      selectedRulePreset = 'all';
      selectedCategory = 'all';
      rulePage = 1;
      search.value = '';
      document.querySelector('#rule-status-filter').value = 'all';
      document.querySelectorAll('[data-rule-source]').forEach((item) => item.classList.toggle('is-active', item.dataset.ruleSource === 'all'));
      document.querySelectorAll('[data-rule-preset]').forEach((item) => item.classList.remove('is-active'));
      renderTaxonomy();
      renderRuleList();
    });
    document.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        showView('tasks');
        document.querySelector('#open-task-dialog')?.click();
      }
    });
  }

  initNavigation();
  initDecisionControls();
  initDataCenter();
  initRuleSourceMeta();
  renderTaxonomy();
  initRuleControls();
  initRuleCompareControls();
  updateRulePackCount();
  renderRuleList();
  initTaskControls();
  initDraftingControls();
  renderTasks();
  initReviewControls();
  initFinancialAuditControls();
  initUsageControls();
  initLibraryControls();
  initKnowledgeControls();
  initKnowledgeCategoryControls();
  initWorkspaceChatControls();
  initUserControls();
  initAuditControls();
  initReportControls();
  refreshIcons();
  initPlatform();
})();
