(() => {
  const DB_NAME = 'fechamento-campo';
  const STORE = 'pending-events';
  const DB_VERSION = 2;
  const config = window.FIELD_APP_CONFIG || {};
  let selectedType = null;
  let selectedApplication = null;
  let db;
  let syncing = false;

  const uuid = () => window.crypto?.randomUUID ? window.crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16); });
  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
  const getCookie = name => document.cookie.split('; ').find(row => row.startsWith(name + '='))?.split('=')[1];
  const today = () => new Date().toISOString().slice(0, 10);

  const openDb = () => new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE)) database.createObjectStore(STORE, { keyPath: 'client_id' });
    };
    request.onsuccess = () => { db = request.result; resolve(db); };
    request.onerror = () => reject(request.error);
  });
  const allPending = () => new Promise((resolve, reject) => { const req = db.transaction(STORE, 'readonly').objectStore(STORE).getAll(); req.onsuccess = () => resolve(req.result.sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)))); req.onerror = () => reject(req.error); });
  const putPending = item => new Promise((resolve, reject) => { const req = db.transaction(STORE, 'readwrite').objectStore(STORE).put(item); req.onsuccess = resolve; req.onerror = () => reject(req.error); });
  const removePending = id => new Promise((resolve, reject) => { const req = db.transaction(STORE, 'readwrite').objectStore(STORE).delete(id); req.onsuccess = resolve; req.onerror = () => reject(req.error); });

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
      const response = await fetch('/api/v1/events/sync/', { method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(getCookie('csrftoken') || '')}, body: JSON.stringify({events: items}) });
      if (!response.ok) throw new Error(`Servidor respondeu HTTP ${response.status}`);
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
    if (selectedType === 'rubric' && (!selectedApplication || quantity !== 1)) return 'Selecione uma regra de rubrica e registre uma ocorrência.';
    if (reason.length < 5) return 'O motivo precisa ter pelo menos 5 caracteres.';
    return '';
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
      status.textContent = 'App instalado. Abra pelo ícone Campo na tela do aparelho.';
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
        ? 'Instalação iniciada. Procure o ícone Campo na tela do aparelho.'
        : 'Tudo bem. Se quiser instalar depois, siga os passos do seu aparelho acima.';
    });
  };
  const init = async () => {
    await openDb();
    document.querySelector('#event-date').value = today();
    await renderQueue();
    updateConnection();
    setupInstallCard();
    document.querySelectorAll('.event-type').forEach(button => button.addEventListener('click', () => {
      selectedType = button.dataset.eventType;
      selectedApplication = button.dataset.applicationId || null;
      document.querySelectorAll('.event-type').forEach(b => b.classList.remove('selected'));
      button.classList.add('selected');
      const quantity = document.querySelector('#event-quantity');
      quantity.value = '1';
      quantity.disabled = selectedType === 'additional_12h' || selectedType === 'rubric';
      document.querySelector('#field-event-form').hidden = false;
    }));
    document.querySelector('#field-event-form').addEventListener('submit', async event => {
      event.preventDefault();
      const error = validateForm();
      if (error) { window.alert(error); return; }
      const selectedButton = document.querySelector('.event-type.selected');
      await putPending({client_id: uuid(), idempotency_key: uuid(), event_id: null, unit_id: config.unitId, collaborator_id: document.querySelector('#collaborator-id').value, event_type: selectedType, application_id: selectedApplication, event_label: selectedButton.textContent.trim(), event_date: document.querySelector('#event-date').value, quantity: document.querySelector('#event-quantity').value, reason: document.querySelector('#event-reason').value.trim(), status: 'pending', attempts: 0, last_error: '', created_at: new Date().toISOString()});
      event.target.reset();
      document.querySelector('#event-date').value = today();
      document.querySelector('#event-quantity').disabled = false;
      event.target.hidden = true;
      selectedType = null;
      selectedApplication = null;
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
  window.addEventListener('DOMContentLoaded', init);
})();
