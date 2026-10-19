'use strict';

const state = {
  statuses: [],
  user: null,
  filter: '',          // '' = все
  query: '',
  requests: [],
  counts: {},
  total: 0,
  selectedId: null,
  knownIds: new Set(),
  firstLoad: true,
};

const el = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
));
const statusMeta = (key) => state.statuses.find((s) => s.key === key) || { label: key, emoji: '•' };

let toastTimer = null;
function toast(message) {
  const node = el('toast');
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, message.length > 70 ? 9000 : 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (response.status === 401) {
    showLogin();
    throw new Error('unauthorized');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(data.error || 'request_failed'), { data });
  return data;
}

/* ------------------------------------------------------------------ вход */

function showLogin(message) {
  el('app').hidden = true;
  el('login-screen').hidden = false;
  const error = el('login-error');
  error.hidden = !message;
  error.textContent = message || '';
  el('login').focus();
}

function showApp() {
  el('login-screen').hidden = true;
  el('app').hidden = false;
  el('user-chip').textContent = state.user ? `👤 ${state.user}` : '';
}

el('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const login = el('login').value.trim();
  const password = el('password').value;
  try {
    const response = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login, password }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      showLogin(data.error === 'too_many_attempts'
        ? 'Слишком много попыток. Подождите 10 минут.'
        : 'Неверный логин или пароль.');
      return;
    }
    state.user = data.user;
    el('password').value = '';
    showApp();
    await boot();
  } catch (err) {
    showLogin('Сервер недоступен.');
  }
});

el('logout-btn').addEventListener('click', async () => {
  await fetch('/api/logout', { method: 'POST' });
  state.user = null;
  showLogin();
});

/* ------------------------------------------------------------------ табы */

function renderTabs() {
  const tabs = el('tabs');
  const buttons = [{ key: '', label: 'Все', emoji: '📋', count: state.total }].concat(
    state.statuses.map((s) => ({ ...s, count: state.counts[s.key] || 0 }))
  );
  tabs.innerHTML = buttons.map((tab) => `
    <button class="tab ${state.filter === tab.key ? 'active' : ''}" data-filter="${esc(tab.key)}">
      <span>${esc(tab.emoji)} ${esc(tab.label)}</span>
      <span class="count">${tab.count}</span>
    </button>`).join('');
  tabs.querySelectorAll('.tab').forEach((button) => {
    button.addEventListener('click', () => {
      state.filter = button.dataset.filter;
      loadList();
    });
  });
}

/* --------------------------------------------------------------- список */

function cardHtml(row) {
  const badges = [];
  if (row.example_url) badges.push('🔗');
  if (row.photo_href) badges.push('🖼');
  return `
    <article class="card ${row.id === state.selectedId ? 'selected' : ''} ${row.status === 'new' ? 'is-new' : ''}"
             style="--st: var(--st-${esc(row.status)}); --st-bg: var(--st-${esc(row.status)}-bg)"
             data-id="${row.id}">
      <div class="card-top">
        <span class="card-id">№${row.id} · ${esc(row.created_at_human)}</span>
        <span class="chip">${esc(row.status_emoji)} ${esc(row.status_label)}</span>
      </div>
      <div class="card-title">${esc(row.item)} ${badges.join(' ')}</div>
      <div class="card-meta">
        <span>👤 ${esc(row.requester)}</span>
        <span>🔢 ${esc(row.quantity || '—')}</span>
        <span>📅 ${esc(row.deadline || '—')}</span>
      </div>
      <div class="card-purpose">🎯 ${esc(row.purpose)}</div>
    </article>`;
}

function renderList() {
  const list = el('list');
  list.innerHTML = state.requests.map(cardHtml).join('');
  el('empty').hidden = state.requests.length > 0;
  list.querySelectorAll('.card').forEach((card) => {
    card.addEventListener('click', () => openDetail(Number(card.dataset.id)));
  });
  el('total-badge').textContent = state.total;
}

async function loadList(silent = false) {
  const params = new URLSearchParams();
  if (state.filter) params.set('status', state.filter);
  if (state.query) params.set('q', state.query);
  const data = await api(`/api/requests?${params.toString()}`);

  const incoming = data.requests.map((row) => row.id);
  if (!state.firstLoad) {
    const fresh = incoming.filter((id) => !state.knownIds.has(id));
    if (fresh.length && silent) {
      toast(fresh.length === 1 ? `Новая заявка №${fresh[0]}` : `Новых заявок: ${fresh.length}`);
    }
  }
  incoming.forEach((id) => state.knownIds.add(id));
  state.firstLoad = false;

  state.requests = data.requests;
  state.counts = data.counts;
  state.total = data.total;
  renderTabs();
  renderList();
  updateTitle();
}

function updateTitle() {
  const unseen = state.counts.new || 0;
  document.title = unseen ? `(${unseen}) Заявки на закупку` : 'Заявки на закупку';
}

/* ---------------------------------------------------------------- деталь */

function detailHtml(row, history) {
  const example = row.example_url
    ? (row.example_is_link
      ? `<a href="${esc(row.example_url)}" target="_blank" rel="noopener">${esc(row.example_url)}</a>`
      : esc(row.example_url))
    : '<span class="muted">не приложен</span>';

  const photo = row.photo_href
    ? `<a href="${esc(row.photo_href)}" target="_blank" rel="noopener">
         <img class="photo" src="${esc(row.photo_href)}" alt="Пример товара"></a>`
    : '';

  const author = `${esc(row.author_name || '—')}${row.author_username ? ` (@${esc(row.author_username)})` : ''}`;

  const statusButtons = state.statuses.map((s) => `
    <button class="status-btn ${s.key === row.status ? 'current' : ''}"
            style="--st: var(--st-${esc(s.key)}); --st-bg: var(--st-${esc(s.key)}-bg)"
            data-status="${esc(s.key)}" ${s.key === row.status ? 'disabled' : ''}>
      ${esc(s.emoji)} ${esc(s.label)}
    </button>`).join('');

  const historyHtml = history.map((item) => {
    const transition = item.to_label
      ? `${item.from_label ? `${esc(item.from_label)} → ` : ''}<b>${esc(item.to_label)}</b>`
      : 'комментарий';
    return `
      <div class="history-item">
        <div>${transition} · ${esc(item.actor)}</div>
        <div class="history-when">${esc(item.at_human)}</div>
        ${item.comment ? `<div class="history-comment">${esc(item.comment)}</div>` : ''}
      </div>`;
  }).reverse().join('');

  return `
    <div class="detail-head" style="--st: var(--st-${esc(row.status)}); --st-bg: var(--st-${esc(row.status)}-bg)">
      <div class="row">
        <span class="card-id">Заявка №${row.id}</span>
        <span class="chip">${esc(row.status_emoji)} ${esc(row.status_label)}</span>
      </div>
      <h2>${esc(row.item)}</h2>
    </div>

    <dl class="fields">
      <div class="field"><dt>Кто заказывает</dt><dd>${esc(row.requester)}</dd></div>
      <div class="field"><dt>Количество</dt><dd>${esc(row.quantity || '—')}</dd></div>
      <div class="field"><dt>Нужно к сроку</dt><dd>${esc(row.deadline || '—')}</dd></div>
      <div class="field"><dt>Цель</dt><dd>${esc(row.purpose)}</dd></div>
      <div class="field"><dt>Пример</dt><dd>${example}</dd></div>
      <div class="field"><dt>Автор в MAX</dt><dd>${author}</dd></div>
      <div class="field"><dt>Создана</dt><dd>${esc(row.created_at_human)}</dd></div>
      <div class="field"><dt>Изменена</dt><dd>${esc(row.updated_at_human)}</dd></div>
      ${row.admin_comment ? `<div class="field"><dt>Комментарий</dt><dd>${esc(row.admin_comment)}</dd></div>` : ''}
    </dl>

    ${photo}

    <div>
      <div class="section-title">Комментарий для автора</div>
      <div class="comment-box">
        <textarea id="comment" placeholder="Например: уточните, нужен ли чайник с терморегулятором"></textarea>
        <p class="comment-hint">Уйдёт автору в MAX — вместе со сменой статуса или отдельной кнопкой ниже.</p>
        <button class="btn" id="comment-only-btn">💬 Отправить комментарий без смены статуса</button>
      </div>
    </div>

    <div>
      <div class="section-title">Поставить статус</div>
      <div class="status-grid">${statusButtons}</div>
    </div>

    <div>
      <div class="section-title">История</div>
      <div class="history">${historyHtml}</div>
    </div>

    <div class="detail-footer">
      <button class="btn btn-danger" id="delete-btn">🗑 Удалить заявку</button>
      <div class="delete-confirm" id="delete-confirm" hidden>
        <p>Удалить заявку №${row.id} вместе с историей и фотографией? Вернуть будет нельзя,
           автору уйдёт сообщение об удалении.</p>
        <div class="delete-actions">
          <button class="btn btn-danger" id="delete-yes">Да, удалить</button>
          <button class="btn" id="delete-no">Отмена</button>
        </div>
      </div>
    </div>`;
}

async function openDetail(id) {
  state.selectedId = id;
  history.replaceState(null, '', `#${id}`);
  renderList();
  const data = await api(`/api/requests/${id}`);
  el('detail-placeholder').hidden = true;
  const detail = el('detail');
  detail.hidden = false;
  detail.innerHTML = detailHtml(data.request, data.history);

  detail.querySelectorAll('.status-btn').forEach((button) => {
    button.addEventListener('click', () => setStatus(id, button.dataset.status));
  });
  el('comment-only-btn').addEventListener('click', () => saveComment(id));

  const askDelete = el('delete-btn');
  const confirmBox = el('delete-confirm');
  askDelete.addEventListener('click', () => {
    askDelete.hidden = true;
    confirmBox.hidden = false;
  });
  el('delete-no').addEventListener('click', () => {
    confirmBox.hidden = true;
    askDelete.hidden = false;
  });
  el('delete-yes').addEventListener('click', () => deleteRequest(id));
}

async function setStatus(id, status) {
  const comment = (el('comment')?.value || '').trim();
  const result = await api(`/api/requests/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status, comment }),
  });
  toast(result.author_notified
    ? `Статус: ${statusMeta(status).label}. Автору отправлено уведомление.`
    : `Статус: ${statusMeta(status).label}. Автору НЕ отправлено${result.notify_error ? `: ${result.notify_error}` : ''}`);
  await loadList();
  await openDetail(id);
}

async function saveComment(id) {
  const comment = (el('comment')?.value || '').trim();
  if (!comment) { toast('Комментарий пустой'); return; }
  const result = await api(`/api/requests/${id}/comment`, {
    method: 'POST',
    body: JSON.stringify({ comment }),
  });
  toast(result.author_notified
    ? 'Комментарий отправлен автору'
    : `Комментарий сохранён, но автору НЕ отправлен${result.notify_error ? `: ${result.notify_error}` : ''}`);
  await openDetail(id);
}

async function deleteRequest(id) {
  const result = await api(`/api/requests/${id}`, { method: 'DELETE' });
  toast(result.author_notified
    ? `Заявка №${id} удалена, автору отправлено сообщение`
    : `Заявка №${id} удалена. Автору НЕ отправлено${result.notify_error ? `: ${result.notify_error}` : ''}`);
  state.selectedId = null;
  state.knownIds.delete(id);
  history.replaceState(null, '', location.pathname);
  el('detail').hidden = true;
  el('detail-placeholder').hidden = false;
  await loadList();
}

/* ------------------------------------------------------- поиск и старт */

let searchTimer = null;
el('search').addEventListener('input', (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.query = event.target.value.trim();
    loadList();
  }, 250);
});

el('refresh-btn').addEventListener('click', () => loadList());

async function boot() {
  const meta = await api('/api/meta');
  state.statuses = meta.statuses;
  await loadList();
  const hashId = Number(location.hash.replace('#', ''));
  if (hashId) openDetail(hashId).catch(() => {});
}

async function init() {
  const meta = await fetch('/api/meta').then((r) => r.json()).catch(() => null);
  if (!meta) { showLogin('Сервер недоступен.'); return; }
  state.statuses = meta.statuses;
  if (!meta.user) { showLogin(); return; }
  state.user = meta.user;
  showApp();
  await boot();
}

setInterval(() => {
  if (!el('app').hidden) loadList(true).catch(() => {});
}, 20000);

init();
