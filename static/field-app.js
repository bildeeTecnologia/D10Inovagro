(() => {
  const config = window.FIELD_APP_CONFIG || {};
  const userId = config.userId == null ? '' : String(config.userId);
  const tenantId = config.tenantId == null ? 'none' : String(config.tenantId);
  const storageScope = /^\d+$/.test(userId) ? `tenant-${tenantId}-user-${userId}` : null;
  const DB_NAME = storageScope ? `fechamento-campo-${storageScope}` : null;
  const UNIT_PREFERENCE_KEY = storageScope ? `field-last-unit:${storageScope}` : null;
  const STORE = 'pending-events';
  const DB_VERSION = 3;
  const CATALOG_STORE = 'field-catalog';
  let selectedType = null;
  let selectedApplication = null;
  let selectedApplicationMode = null;
  let db;
  let syncing = false;

  const uuid = () => window.crypto?.randomUUID ? window.crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16); });
  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
  const getCookie = name => document.cookie.split('; ').find(row => row.startsWith(name + '='))?.split('=')[1];
  const today = () => new Date().toISOString().slice(0, 10);

  const openDb = () => new Promise((resolve, reject) => {
    if (!DB_NAME) { reject(new Error('Não foi possível identificar a conta deste aparelho.')); return; }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE)) database.createObjectStore(STORE, { keyPath: 'client_id' });
      if (!database.objectStoreNames.contains(CATALOG_STORE)) database.createObjectStore(CATALOG_STORE, { keyPath: 'key' });
    };
    request.onsuccess = () => { db = request.result; resolve(db); };
    request.onerror = () => reject(request.error);
  });
  const allPending = () => new Promise((resolve, reject) => { const req = db.transaction(STORE, 'readonly').objectStore(STORE).getAll(); req.onsuccess = () => resolve(req.result.sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)))); req.onerror = () => reject(req.error); });
  const putPending = item => new Promise((resolve, reject) => { const req = db.transaction(STORE, 'readwrite').objectStore(STORE).put(item); req.onsuccess = resolve; req.onerror = () => reject(req.error); });
  const removePending = id => new Promise((resolve, reject) => { const req = db.transaction(STORE, 'readwrite').objectStore(STORE).delete(id); req.onsuccess = resolve; req.onerror = () => reject(req.error); });
  const saveCatalog = catalog => new Promise((resolve, reject) => { const req = db.transaction(CATALOG_STORE, 'readwrite').objectStore(CATALOG_STORE).put({key: 'bootstrap', catalog, saved_at: new Date().toISOString()}); req.onsuccess = resolve; req.onerror = () => reject(req.error); });
  const loadCatalog = () => new Promise((resolve, reject) => { const req = db.transaction(CATALOG_STORE, 'readonly').objectStore(CATALOG_STORE).get('bootstrap'); req.onsuccess = () => resolve(req.result?.catalog || null); req.onerror = () => reject(req.error); });
  const saveLastUnit = unitId => {
    if (!UNIT_PREFERENCE_KEY) return;
    try { localStorage.setItem(UNIT_PREFERENCE_KEY, String(unitId || '')); } catch (_) { /* preferência é opcional */ }
  };
  const lastUnit = () => {
    if (!UNIT_PREFERENCE_KEY) return '';
    try { return localStorage.getItem(UNIT_PREFERENCE_KEY) || ''; } catch (_) { return ''; }
  };

  const setSyncStatus = message => { const element = document.querySelector('#sync-status'); if (element) element.textContent = message; };
  const statusInfo = item => item.status === 'error' ? ['Erro', 'danger'] : item.status === 'syncing' ? ['Enviando', 'warning'] : ['Aguardando envio', 'warning'];
  const renderQueue = async () => {
    const items = await allPending();
    const waiting = items.filter(item => item.status !== 'error').length;
    const errors = items.filter(item => item.status === 'error').length;
    document.querySelector('#queue-count').textContent = `${items.length} pendente${items.length === 1 ? '' : 's'}`;
    setSyncStatus(errors ? `${errors} com erro · revise a fila` : waiting ? `${waiting} aguardando sincronização` : 'Fila sincronizada');
    document.querySelector('#queue-list').innerHTML = items.length ? items.map(item => {
      const [label, style] = statusInfo(item);
      const detail = item.last_error ? `<small class="queue-error">${escapeHtml(item.last_error)}</small>` : `<small>${escapeHtml(item.reason)}</small>`;
      const actions = item.status === 'error' ? `<button class="button small secondary queue-retry" data-id="${escapeHtml(item.client_id)}" type="button">Tentar novamente</button>` : '';
      return `<div class="queue-item"><span class="event-dot"></span><div><strong>${escapeHtml(item.event_label)}</strong>${detail}<small>Tentativas: ${item.attempts || 0}</small></div><span class="status ${style}">${label}</span>${actions}<button class="queue-remove" data-id="${escapeHtml(item.client_id)}" type="button" title="Remover item">×</button></div>`;
    }).join('') : '<p class="empty">Nenhum item aguardando sincronização.</p>';
  };
  const updateConnection = () => {
    const online = navigator.onLine;
    const el = document.querySelector('#connection-status');
    el.textContent = online ? 'Conectado' : 'Sem sinal';
    el.className = `connection ${online ? 'online' : 'offline'}`;
    document.querySelector('#offline-title').textContent = online ? 'Lançamento rápido' : 'Sem sinal — salvo no aparelho';
    document.querySelector('#offline-message').textContent = online ? 'Registre ocorrências e sincronize com o RH.' : 'O lançamento ficará na fila e será enviado quando a conexão voltar.';
  };
  const markItems = async (items, result) => {
    const successes = new Set((result.synced || []).map(item => item.client_id));
    const conflicts = new Map((result.conflicts || []).map(item => [item.client_id, item.reason]));
    const errors = new Map((result.errors || []).map(item => [item.client_id, item.reason]));
    for (const item of items) {
      if (successes.has(item.client_id)) await removePending(item.client_id);
      else if (conflicts.has(item.client_id) || errors.has(item.client_id)) await putPending({...item, status: 'error', attempts: (item.attempts || 0) + 1, last_error: conflicts.get(item.client_id) || errors.get(item.client_id)});
    }
  };
  const sync = async () => {
    if (syncing || !navigator.onLine) { if (!navigator.onLine) setSyncStatus('Sem conexão — itens permanecem no aparelho'); return; }
    const items = (await allPending()).filter(item => item.status !== 'error');
    if (!items.length) { await renderQueue(); return; }
    syncing = true;
    setSyncStatus(`Enviando ${items.length} item(ns)...`);
    try {
      items.forEach(item => { item.status = 'syncing'; });
      await Promise.all(items.map(putPending));
      const response = await fetch('/api/v1/events/sync/', { method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(getCookie('csrftoken') || ''), 'X-D10-Account': userId}, body: JSON.stringify({events: items}) });
      if (!response.ok) {
        let message = `Servidor respondeu HTTP ${response.status}`;
        try { message = (await response.json()).error || message; } catch (_) { /* resposta não JSON */ }
        throw new Error(message);
      }
      await markItems(items, await response.json());
      setSyncStatus('Sincronização concluída');
    } catch (error) {
      for (const item of items) await putPending({...item, status: 'error', attempts: (item.attempts || 0) + 1, last_error: error.message || 'Falha de conexão'});
      setSyncStatus('Falha de sincronização — revise a fila');
    } finally { syncing = false; await renderQueue(); }
  };
  const validateForm = () => {
    const collaborator = document.querySelector('#collaborator-id').value;
    const eventDate = document.querySelector('#event-date').value;
    const quantity = Number(document.querySelector('#event-quantity').value);
    const reason = document.querySelector('#event-reason').value.trim();
    if (!config.unitId || !collaborator || !selectedType || !eventDate || !reason) return 'Preencha colaborador, tipo, data e motivo.';
    if (eventDate > today()) return 'A data do evento não pode estar no futuro.';
    if (!Number.isFinite(quantity) || quantity <= 0) return 'Informe uma quantidade válida.';
    if (selectedType === 'additional_12h' && quantity !== 1) return 'O Adicional 12h aceita somente uma ocorrência por lançamento.';
    if (selectedType === 'rubric' && (!selectedApplication || (selectedApplicationMode !== 'cumulative' && quantity !== 1))) return 'Selecione uma regra de rubrica e informe uma quantidade válida.';
    if (reason.length < 5) return 'O motivo precisa ter pelo menos 5 caracteres.';
    return '';
  };
  const catalogUnits = () => (config.catalog?.units || []);
  const activeUnitId = () => {
    const units = catalogUnits();
    const authorized = new Set(units.map(unit => String(unit.id)));
    const explicitlyRequested = String(config.requestedUnitId || '');
    if (explicitlyRequested && authorized.has(explicitlyRequested)) return explicitlyRequested;
    const previouslySelected = lastUnit();
    if (previouslySelected && authorized.has(previouslySelected)) return previouslySelected;
    const serverDefault = String(config.unitId || '');
    if (serverDefault && authorized.has(serverDefault)) return serverDefault;
    return units.length ? String(units[0].id) : '';
  };
  const renderCollaborators = unitId => {
    const select = document.querySelector('#collaborator-id');
    if (!select) return;
    const people = (config.catalog?.collaborators || []).filter(person => (person.unit_ids || []).map(String).includes(String(unitId)));
    select.innerHTML = '<option value="">Selecione o colaborador</option>' + people.map(person => `<option value="${escapeHtml(person.id)}">${escapeHtml(person.name)}${person.employee_code ? ` — ${escapeHtml(person.employee_code)}` : ''}</option>`).join('');
  };
  const selectEventType = button => {
    selectedType = button.dataset.eventType;
    selectedApplication = button.dataset.applicationId || null;
    selectedApplicationMode = button.dataset.applicationMode || null;
    document.querySelectorAll('.event-type').forEach(b => b.classList.remove('selected'));
    button.classList.add('selected');
    const quantity = document.querySelector('#event-quantity');
    quantity.value = '1';
    quantity.disabled = selectedType === 'additional_12h' || (selectedType === 'rubric' && selectedApplicationMode !== 'cumulative');
    const guidance = document.querySelector('#event-guidance');
    guidance.textContent = button.dataset.hint || '';
    guidance.hidden = !button.dataset.hint;
    const form = document.querySelector('#field-event-form');
    form.hidden = false;
    form.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  };
  const renderEventButtons = unitId => {
    const container = document.querySelector('#event-types');
    if (!container) return;
    const cards = config.catalog?.event_cards || [];
    const apps = (config.catalog?.rubric_applications || []).filter(app => String(app.unit_id) === String(unitId));
    const fixed = cards.map(card => `<button type="button" class="event-type event-card tone-${escapeHtml(card.tone || 'blue')}" data-event-type="${escapeHtml(card.value)}" data-label="${escapeHtml(card.label)}" data-hint="${escapeHtml(card.value === 'additional_12h' ? 'Adicional 12h: uma ocorrência por vez. O líder lança e o DP aprova para pagamento no dia 10.' : card.value === 'advance' ? 'Adiantamento: registra uma solicitação. Não confirma pagamento nem autoriza desconto automático.' : '')}"><span class="event-card-icon" aria-hidden="true">${escapeHtml(card.icon || '•')}</span><span class="event-card-title">${escapeHtml(card.short || card.label)}</span><span class="event-card-arrow" aria-hidden="true">›</span></button>`).join('');
    const configured = apps.map(app => `<button type="button" class="event-type event-card tone-gold" data-event-type="rubric" data-application-id="${escapeHtml(app.id)}" data-application-mode="${escapeHtml(app.mode || 'event')}" data-label="${escapeHtml(app.label)}" data-hint="${escapeHtml(app.instructions)}"><span class="event-card-icon" aria-hidden="true">＋</span><span class="event-card-title">${escapeHtml(app.label)}</span><span class="event-card-arrow" aria-hidden="true">›</span></button>`).join('');
    container.innerHTML = fixed + configured;
    container.querySelectorAll('.event-type').forEach(button => button.addEventListener('click', () => selectEventType(button)));
  };
  const applyOfflineCatalog = unitId => {
    const resolved = String(unitId || activeUnitId());
    if (!resolved) return;
    config.unitId = resolved;
    saveLastUnit(resolved);
    const selector = document.querySelector('#field-unit');
    if (selector) selector.value = resolved;
    const unit = catalogUnits().find(item => String(item.id) === resolved);
    const subtitle = document.querySelector('.field-header .subtitle');
    if (subtitle && unit) subtitle.textContent = unit.name;
    renderCollaborators(resolved);
    renderEventButtons(resolved);
  };
  const setupInstallCard = () => {
    const card = document.querySelector('#pwa-install-card');
    if (!card) return;
    const button = document.querySelector('#pwa-install-button');
    const status = document.querySelector('#pwa-install-status');
    const guide = id => document.querySelector(`#${id}`);
    const userAgent = navigator.userAgent || '';
    const isIOS = /iphone|ipad|ipod/i.test(userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    const isAndroid = /android/i.test(userAgent);
    const isStandalone = window.matchMedia?.('(display-mode: standalone)').matches || navigator.standalone === true;
    let installPrompt = null;

    if (isStandalone) {
      card.hidden = true;
      return;
    }
    if (isIOS) guide('install-iphone').open = true;
    else if (isAndroid) guide('install-android').open = true;
    else guide('install-computer').open = true;

    window.addEventListener('beforeinstallprompt', event => {
      event.preventDefault();
      installPrompt = event;
      button.hidden = false;
    });
    window.addEventListener('appinstalled', () => {
      installPrompt = null;
      button.hidden = true;
      card.hidden = true;
      status.hidden = false;
      status.textContent = 'App instalado. Abra pelo ícone D10 Agro na tela do aparelho.';
    });
    button.addEventListener('click', async () => {
      if (!installPrompt) return;
      button.disabled = true;
      await installPrompt.prompt();
      const choice = await installPrompt.userChoice;
      installPrompt = null;
      button.disabled = false;
      button.hidden = true;
      status.hidden = false;
      status.textContent = choice.outcome === 'accepted'
        ? 'Instalação iniciada. Procure o ícone D10 Agro na tela do aparelho.'
        : 'Tudo bem. Se quiser instalar depois, siga os passos do seu aparelho acima.';
    });
  };
  const init = async () => {
    await openDb();
    if (config.catalog?.units?.length) await saveCatalog(config.catalog);
    const cachedCatalog = await loadCatalog();
    if (cachedCatalog) config.catalog = cachedCatalog;
    applyOfflineCatalog(activeUnitId());
    document.querySelector('#event-date').value = today();
    await renderQueue();
    updateConnection();
    setupInstallCard();
    const unitSelector = document.querySelector('#field-unit');
    if (unitSelector) unitSelector.addEventListener('change', event => {
      saveLastUnit(event.target.value);
      if (navigator.onLine) event.target.form.submit();
      else applyOfflineCatalog(event.target.value);
    });
    document.querySelector('#field-event-form').addEventListener('submit', async event => {
      event.preventDefault();
      const error = validateForm();
      if (error) { window.alert(error); return; }
      const selectedButton = document.querySelector('.event-type.selected');
      await putPending({client_id: uuid(), idempotency_key: uuid(), event_id: null, unit_id: config.unitId, collaborator_id: document.querySelector('#collaborator-id').value, event_type: selectedType, application_id: selectedApplication, event_label: selectedButton.dataset.label || selectedButton.textContent.trim(), event_date: document.querySelector('#event-date').value, quantity: document.querySelector('#event-quantity').value, reason: document.querySelector('#event-reason').value.trim(), status: 'pending', attempts: 0, last_error: '', created_at: new Date().toISOString()});
      event.target.reset();
      document.querySelector('#event-date').value = today();
      document.querySelector('#event-quantity').disabled = false;
      event.target.hidden = true;
      document.querySelector('#event-guidance').hidden = true;
      selectedType = null;
      selectedApplication = null;
      selectedApplicationMode = null;
      document.querySelectorAll('.event-type').forEach(b => b.classList.remove('selected'));
      await renderQueue();
      await sync();
    });
    document.querySelector('#sync-button').addEventListener('click', sync);
    document.querySelector('#queue-list').addEventListener('click', async event => {
      const id = event.target.dataset.id;
      if (!id) return;
      const item = (await allPending()).find(entry => entry.client_id === id);
      if (!item) return;
      if (event.target.classList.contains('queue-remove')) {
        if (window.confirm('Remover este lançamento pendente do aparelho? Esta ação não envia o evento ao RH.')) await removePending(id);
      } else if (event.target.classList.contains('queue-retry')) {
        await putPending({...item, status: 'pending', last_error: ''});
        await sync();
      }
      await renderQueue();
    });
    window.addEventListener('online', () => { updateConnection(); sync(); });
    window.addEventListener('offline', updateConnection);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { updateConnection(); sync(); } });
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/static/sw.js');
  };
  window.addEventListener('DOMContentLoaded', () => {
    init().catch(() => setSyncStatus('Não foi possível abrir os dados offline desta conta. Recarregue a página enquanto estiver conectado.'));
  });
})();
