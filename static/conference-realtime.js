(() => {
  const liveRegion = document.querySelector('#conference-live-region');
  const status = document.querySelector('#conference-refresh-status');
  const configNode = document.querySelector('#conference-realtime-config');
  if (!liveRegion || !status || !configNode) return;

  const tokenUrl = configNode.dataset.tokenUrl;
  const competency = configNode.dataset.competency;
  const unit = configNode.dataset.unit;
  let refreshing = false;
  let refreshQueued = false;
  let realtimeConnected = false;
  let realtimeClient = null;
  let currentToken = '';
  let channelsCreated = false;
  let tokenRefreshTimer = null;
  let channelStates = new Map();
  let reconnecting = false;

  const refresh = async () => {
    if (refreshing) {
      refreshQueued = true;
      return;
    }
    if (document.visibilityState !== 'visible') return;
    const currentCard = liveRegion.querySelector('#conference-events-card');
    if (!currentCard) return;

    const fields = [...liveRegion.querySelectorAll('input, textarea')];
    const hasDraftText = fields.some(field => field.value.trim());
    if (hasDraftText || fields.includes(document.activeElement)) {
      status.textContent = 'Atualização aguardando: conclua a justificativa em edição para renovar a lista.';
      return;
    }

    refreshing = true;
    try {
      const response = await fetch(window.location.pathname + window.location.search, {
        method: 'GET',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { 'Accept': 'text/html', 'X-Requested-With': 'XMLHttpRequest' },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const html = await response.text();
      const documentFragment = new DOMParser().parseFromString(html, 'text/html');
      const updatedCard = documentFragment.querySelector('#conference-events-card');
      if (!updatedCard) throw new Error('Resposta de atualização inválida');
      const changed = currentCard.innerHTML !== updatedCard.innerHTML;
      if (changed) currentCard.replaceWith(updatedCard);
      const time = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date());
      status.textContent = changed ? `Eventos atualizados às ${time}.` : `Conferência sincronizada às ${time}.`;
    } catch (_error) {
      status.textContent = 'Não foi possível atualizar agora. A lista atual permanece disponível.';
    } finally {
      refreshing = false;
      if (refreshQueued) {
        refreshQueued = false;
        window.setTimeout(refresh, 150);
      }
    }
  };

  window.refreshConferenceList = refresh;
  const fallbackPoll = window.setInterval(() => {
    if (!realtimeConnected) refresh();
  }, 30000);

  const getToken = async () => {
    const url = new URL(tokenUrl, window.location.origin);
    if (competency) url.searchParams.set('competency', competency);
    if (unit) url.searchParams.set('unit', unit);
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { 'Accept': 'application/json' } });
    if (!response.ok) throw new Error(`Token endpoint respondeu HTTP ${response.status}`);
    return response.json();
  };

  const connect = async () => {
    if (reconnecting || document.visibilityState !== 'visible') return;
    reconnecting = true;
    try {
      const config = await getToken();
      if (!config.topics?.length) {
        status.textContent = 'Aguardando unidades autorizadas para atualização em tempo real.';
        return;
      }
      currentToken = config.token;
      if (!realtimeClient) {
        const { createClient } = await import('https://esm.sh/@supabase/supabase-js@2.107.0?bundle');
        realtimeClient = createClient(config.supabase_url, config.publishable_key, {
          accessToken: async () => currentToken,
        });
      }
      await realtimeClient.realtime.setAuth(config.token);
      if (channelsCreated) return;
      channelsCreated = true;
      channelStates = new Map(config.topics.map(topic => [topic, false]));
      const allSubscribed = () => {
        realtimeConnected = channelStates.size > 0 && [...channelStates.values()].every(Boolean);
        if (realtimeConnected) status.textContent = 'Atualização em tempo real conectada.';
        else status.textContent = 'Conectando atualização em tempo real; atualização de contingência ativa.';
      };

      for (const topic of config.topics) {
        const channel = realtimeClient
          .channel(topic, { config: { private: true } })
          .on('broadcast', { event: 'conference.changed' }, () => window.refreshConferenceList?.())
          .subscribe(channelStatus => {
            channelStates.set(topic, channelStatus === 'SUBSCRIBED');
            allSubscribed();
          });
        void channel;
      }

      tokenRefreshTimer = tokenRefreshTimer || window.setInterval(async () => {
        if (document.visibilityState !== 'visible' || !realtimeClient) return;
        try {
          const renewed = await getToken();
          currentToken = renewed.token;
          await realtimeClient.realtime.setAuth(renewed.token);
        } catch (_error) {
          realtimeConnected = false;
          status.textContent = 'Renovando conexão em tempo real; atualização de contingência ativa.';
        }
      }, 180000);
    } catch (_error) {
      realtimeConnected = false;
      status.textContent = 'Atualização em tempo real indisponível; verificação de contingência ativa.';
    } finally {
      reconnecting = false;
    }
  };

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      if (!realtimeConnected) connect();
      refresh();
    }
  });

  connect();
  void fallbackPoll;
})();
