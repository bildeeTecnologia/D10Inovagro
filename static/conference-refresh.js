(() => {
  const liveRegion = document.querySelector('#conference-live-region');
  const status = document.querySelector('#conference-refresh-status');
  if (!liveRegion || !status) return;

  let refreshing = false;
  const refresh = async () => {
    if (refreshing || document.visibilityState !== 'visible') return;
    const currentCard = liveRegion.querySelector('#conference-events-card');
    if (!currentCard) return;

    const fields = [...liveRegion.querySelectorAll('input, textarea')];
    const hasFocusedField = fields.includes(document.activeElement);
    const hasDraftText = fields.some(field => field.value.trim());
    if (hasFocusedField || hasDraftText) {
      status.textContent = 'Atualização aguardando: conclua a justificativa em edição para renovar a lista.';
      return;
    }

    refreshing = true;
    try {
      const response = await fetch(window.location.pathname + window.location.search, {
        method: 'GET',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: {
          'Accept': 'text/html',
          'X-Requested-With': 'XMLHttpRequest',
        },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const html = await response.text();
      const documentFragment = new DOMParser().parseFromString(html, 'text/html');
      const updatedCard = documentFragment.querySelector('#conference-events-card');
      if (!updatedCard) throw new Error('Resposta de atualização inválida');

      const changed = currentCard.innerHTML !== updatedCard.innerHTML;
      if (changed) currentCard.replaceWith(updatedCard);
      const time = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date());
      status.textContent = changed ? `Eventos atualizados automaticamente às ${time}.` : `Lista verificada às ${time}; sem novos eventos.`;
    } catch (_error) {
      status.textContent = 'Não foi possível atualizar agora. A lista atual permanece disponível.';
    } finally {
      refreshing = false;
    }
  };

  window.setInterval(refresh, 30000);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refresh();
  });
})();
