'use strict';

const state = {
  statuses: [],
  user: null,
  filter: '',          // '' = все
  query: '',
  requests: [],
  counts: {},
  total: 0,
  openId: null,        // какая заявка открыта в модальном окне
  selected: new Set(), // отмеченные галочками заявки
  lastIndex: null,     // для выбора диапазона с Shift
  knownIds: new Set(),
  firstLoad: true,
};

const el = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
));
const statusMeta = (key) => state.statuses.find((s) => s.key === key) || { label: key };
const dot = (status) => `<span class="dot" style="--st: var(--st-${esc(status)})"></span>`;

let toastTimer = null;
function toast(message) {
  const node = el('toast');
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, message.length > 70 ? 9000 : 3200);
}

async function api(path, options = {}) {
  const init = { ...options };
  if (init.body && !(init.body instanceof FormData)) {
    init.headers = { 'Content-Type': 'application/json', ...(init.headers || {}) };
  }
  const response = await fetch(path, init);
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
  el('overlay').hidden = true;
  el('login-screen').hidden = false;
  const error = el('login-error');
  error.hidden = !message;
  error.textContent = message || '';
  el('login').focus();
}

function showApp() {
  el('login-screen').hidden = true;
  el('app').hidden = false;
  el('user-chip').textContent = state.user || '';
}

el('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const response = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login: el('login').value.trim(), password: el('password').value }),
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
  const tabs = [{ key: '', label: 'Все', count: state.total }].concat(
    state.statuses.map((s) => ({ ...s, count: state.counts[s.key] || 0 }))
  );
  el('tabs').innerHTML = tabs.map((tab) => `
    <button class="tab ${state.filter === tab.key ? 'active' : ''}" data-filter="${esc(tab.key)}">
      ${esc(tab.label)}<span class="count">${tab.count}</span>
    </button>`).join('');
  el('tabs').querySelectorAll('.tab').forEach((button) => {
    button.addEventListener('click', () => {
      state.filter = button.dataset.filter;
      loadList();
    });
  });
}

/* --------------------------------------------------------------- таблица */

function rowHtml(row, index) {
  const marks = [];
  if (row.items_count > 1) marks.push(`позиций ${row.items_count}`);
  if (row.items_count > 1 && row.bought_count) marks.push(`куплено ${row.bought_count}`);
  if (row.example_url) marks.push('ссылка');
  if (row.photo_href) marks.push('фото');
  if (row.attachments_count) marks.push(`скрин. ${row.attachments_count}`);
  const checked = state.selected.has(row.id) ? 'checked' : '';
  return `
    <tr data-id="${row.id}" data-index="${index}">
      <td class="cell-check"><input type="checkbox" data-check="${row.id}" ${checked}></td>
      <td class="cell-num">${row.id}</td>
      <td>
        <div class="cell-item">${esc(row.item)}${marks.length ? `<span class="cell-mark">${esc(marks.join(' · '))}</span>` : ''}</div>
        <div class="cell-purpose">${esc(row.purpose)}</div>
      </td>
      <td>${esc(row.requester)}</td>
      <td class="cell-qty">${esc(row.quantity || '—')}</td>
      <td class="cell-due">${esc(row.deadline || '—')}</td>
      <td><span class="status">${dot(row.status)}${esc(row.status_label)}</span></td>
      <td class="cell-date">${esc(row.created_at_human)}</td>
    </tr>`;
}

function renderList() {
  el('rows').innerHTML = state.requests.map((row, index) => rowHtml(row, index)).join('');
  el('empty').hidden = state.requests.length > 0;
  document.querySelector('.requests').hidden = state.requests.length === 0;
  el('rows').querySelectorAll('tr').forEach((tr) => {
    tr.addEventListener('click', (event) => {
      if (event.target.closest('.cell-check')) return;   // клик по галочке не открывает карточку
      openRequest(Number(tr.dataset.id));
    });
  });
  el('rows').querySelectorAll('[data-check]').forEach((box) => {
    box.addEventListener('click', (event) => {
      const id = Number(box.dataset.check);
      const index = Number(box.closest('tr').dataset.index);
      if (event.shiftKey && state.lastIndex !== null) {
        const [from, to] = [state.lastIndex, index].sort((a, b) => a - b);
        state.requests.slice(from, to + 1).forEach((row) => {
          if (box.checked) state.selected.add(row.id); else state.selected.delete(row.id);
        });
      } else if (box.checked) {
        state.selected.add(id);
      } else {
        state.selected.delete(id);
      }
      state.lastIndex = index;
      renderList();
    });
  });
  renderBulkbar();
}

/* ------------------------------------------------- массовые действия */

function renderBulkbar() {
  const bar = el('bulkbar');
  const count = state.selected.size;
  bar.hidden = count === 0;
  const visible = state.requests.map((row) => row.id);
  el('check-all').checked = count > 0 && visible.every((id) => state.selected.has(id));
  if (!count) return;

  el('bulk-count').textContent = `Выбрано: ${count}`;
  el('bulk-statuses').innerHTML = state.statuses.map((s) => `
    <button class="btn" data-bulk-status="${esc(s.key)}">
      <span class="dot" style="--st: var(--st-${esc(s.key)})"></span> ${esc(s.label)}
    </button>`).join('');
  el('bulk-statuses').querySelectorAll('[data-bulk-status]').forEach((button) => {
    button.addEventListener('click', () => bulkStatus(button.dataset.bulkStatus));
  });
}

el('check-all').addEventListener('change', (event) => {
  state.requests.forEach((row) => {
    if (event.target.checked) state.selected.add(row.id); else state.selected.delete(row.id);
  });
  state.lastIndex = null;
  renderList();
});

el('bulk-clear').addEventListener('click', () => {
  state.selected.clear();
  state.lastIndex = null;
  renderList();
});

async function bulkStatus(status) {
  const ids = [...state.selected];
  const comment = el('bulk-comment').value.trim();
  const result = await api('/api/requests/bulk-status', {
    method: 'POST',
    body: JSON.stringify({ ids, status, comment }),
  });
  const label = statusMeta(status).label;
  toast(result.changed
    ? `Статус «${label}» у ${result.changed} заявок. Уведомлено авторов: ${result.authors_notified}.`
      + (result.notify_error ? ` Ошибка отправки: ${result.notify_error}` : '')
    : 'Ничего не изменилось — этот статус уже стоял');
  el('bulk-comment').value = '';
  state.selected.clear();
  await loadList();
}

el('bulk-delete').addEventListener('click', async () => {
  const button = el('bulk-delete');
  if (button.dataset.armed !== '1') {
    button.dataset.armed = '1';
    button.textContent = `Точно удалить ${state.selected.size}? Нажмите ещё раз`;
    button.classList.add('bulk-confirm');
    setTimeout(() => {
      button.dataset.armed = '';
      button.textContent = 'Удалить';
      button.classList.remove('bulk-confirm');
    }, 4000);
    return;
  }
  const ids = [...state.selected];
  const result = await api('/api/requests/bulk-delete', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  });
  toast(`Удалено заявок: ${result.deleted}`);
  button.dataset.armed = '';
  button.textContent = 'Удалить';
  button.classList.remove('bulk-confirm');
  state.selected.clear();
  await loadList();
});

async function loadList(silent = false) {
  const params = new URLSearchParams();
  if (state.filter) params.set('status', state.filter);
  if (state.query) params.set('q', state.query);
  const data = await api(`/api/requests?${params.toString()}`);

  const incoming = data.requests.map((row) => row.id);
  if (!state.firstLoad && silent) {
    const fresh = incoming.filter((id) => !state.knownIds.has(id));
    if (fresh.length) {
      toast(fresh.length === 1 ? `Новая заявка №${fresh[0]}` : `Новых заявок: ${fresh.length}`);
    }
  }
  incoming.forEach((id) => state.knownIds.add(id));
  state.firstLoad = false;

  const alive = new Set(data.requests.map((row) => row.id));
  [...state.selected].forEach((id) => { if (!alive.has(id)) state.selected.delete(id); });

  state.requests = data.requests;
  state.counts = data.counts;
  state.total = data.total;
  renderTabs();
  renderList();
  const unseen = state.counts.new || 0;
  document.title = unseen ? `(${unseen}) Заявки на закупку` : 'Заявки на закупку';
}

/* ------------------------------------------------------- карточка заявки */

function shotHtml(item) {
  return `
    <div class="shot" data-attachment="${item.id}">
      <a href="${esc(item.url)}" target="_blank" rel="noopener">
        <img src="${esc(item.url)}" alt="${esc(item.original_name || 'Скриншот')}" loading="lazy">
      </a>
      <button class="shot-remove" data-remove="${item.id}" title="Удалить скриншот">&times;</button>
      <div class="shot-caption">${esc(item.uploaded_at)}</div>
    </div>`;
}

function itemHtml(item) {
  const meta = [];
  if (item.quantity) meta.push(esc(item.quantity));
  if (item.link) {
    meta.push(`<a href="${esc(item.link)}" target="_blank" rel="noopener">${esc(item.link)}</a>`);
  }
  return `
    <li class="${item.bought ? 'bought' : ''}" data-row="${item.id}">
      <input type="checkbox" data-item="${item.id}" ${item.bought ? 'checked' : ''}
             title="Отметить купленным">
      <div class="item-body">
        <div class="item-name">${item.position}. ${esc(item.name)}</div>
        ${meta.length ? `<div class="item-meta">${meta.join(' · ')}</div>` : ''}
      </div>
      ${item.photo_url
        ? `<a href="${esc(item.photo_url)}" target="_blank" rel="noopener">
             <img class="item-photo" src="${esc(item.photo_url)}" alt="Фото позиции"></a>`
        : ''}
    </li>`;
}

function itemsTitle(row) {
  const total = row.items_count || 0;
  if (total <= 1) return 'Позиция';
  return row.bought_count
    ? `Позиции · куплено ${row.bought_count} из ${total}`
    : `Позиции (${total})`;
}

function modalHtml(row, history, attachments) {
  const items = row.items || [];
  const author = `${esc(row.author_name || '—')}${row.author_username ? ` (@${esc(row.author_username)})` : ''}`;

  const fromBot = row.photo_href
    ? `<div class="shot">
         <a href="${esc(row.photo_href)}" target="_blank" rel="noopener">
           <img src="${esc(row.photo_href)}" alt="Фото от заказчика" loading="lazy"></a>
         <div class="shot-caption">от заказчика</div>
       </div>`
    : '';

  const statusButtons = state.statuses.map((s) => `
    <button class="status-btn ${s.key === row.status ? 'current' : ''}"
            style="--st: var(--st-${esc(s.key)})" data-status="${esc(s.key)}"
            ${s.key === row.status ? 'disabled' : ''}>
      ${dot(s.key)}${esc(s.label)}
    </button>`).join('');

  const historyHtml = history.slice().reverse().map((item) => {
    const line = item.to_label
      ? `${item.from_label ? `${esc(item.from_label)} → ` : ''}<b>${esc(item.to_label)}</b>`
      : 'комментарий';
    return `
      <div class="history-item">
        <div>${line} · ${esc(item.actor)}</div>
        <div class="history-when">${esc(item.at_human)}</div>
        ${item.comment ? `<div class="history-comment">${esc(item.comment)}</div>` : ''}
      </div>`;
  }).join('');

  return `
    <div class="modal-title-item">${esc(row.item)}${row.items_count > 1
      ? `<span class="muted"> и ещё ${row.items_count - 1}</span>` : ''}</div>

    <dl class="fields">
      <div class="field"><dt>Кто заказывает</dt><dd>${esc(row.requester)}</dd></div>
      <div class="field"><dt>Нужно к сроку</dt><dd>${esc(row.deadline || '—')}</dd></div>
      <div class="field"><dt>Цель</dt><dd>${esc(row.purpose)}</dd></div>
      <div class="field"><dt>Оформил в MAX</dt><dd>${author}</dd></div>
      <div class="field"><dt>Создана</dt><dd>${esc(row.created_at_human)}</dd></div>
      <div class="field"><dt>Изменена</dt><dd>${esc(row.updated_at_human)}</dd></div>
      ${row.admin_comment ? `<div class="field"><dt>Комментарий</dt><dd>${esc(row.admin_comment)}</dd></div>` : ''}
    </dl>

    <div class="section">
      <div class="section-title" id="items-title">${esc(itemsTitle(row))}</div>
      <ul class="items" id="items">${items.map(itemHtml).join('')}</ul>
    </div>

    <div class="section">
      <div class="section-title">Скриншоты заказа</div>
      <div class="shots" id="shots">${fromBot}${attachments.map(shotHtml).join('')}</div>
      <div class="dropzone" id="dropzone">
        Перетащите сюда файл, вставьте из буфера (Cmd+V) или нажмите, чтобы выбрать.
        PNG, JPEG, WebP, GIF до 10 МБ.
      </div>
      <input type="file" id="file-input" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden>
    </div>

    <div class="section">
      <div class="section-title">Комментарий для автора</div>
      <textarea id="comment" placeholder="Например: уточните, нужен ли чайник с терморегулятором"></textarea>
      <p class="hint">Уйдёт автору в MAX — вместе со сменой статуса или отдельной кнопкой.</p>
      <div class="row-actions">
        <button class="btn" id="comment-only-btn">Отправить комментарий</button>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Статус</div>
      <div class="status-grid">${statusButtons}</div>
    </div>

    <div class="section">
      <div class="section-title">История</div>
      <div class="history">${historyHtml}</div>
    </div>

    <div class="modal-footer">
      <div class="row-actions">
        <button class="btn btn-danger" id="delete-btn">Удалить заявку</button>
      </div>
      <div id="delete-confirm" hidden>
        <p class="hint">Заявка исчезнет вместе с историей и скриншотами, вернуть будет нельзя.
           Автору уйдёт сообщение об удалении.</p>
        <div class="row-actions">
          <button class="btn btn-danger" id="delete-yes">Да, удалить</button>
          <button class="btn" id="delete-no">Отмена</button>
        </div>
      </div>
    </div>`;
}

async function openRequest(id) {
  const data = await api(`/api/requests/${id}`);
  const row = data.request;
  state.openId = id;
  history.replaceState(null, '', `#${id}`);

  el('modal-title').innerHTML = `${dot(row.status)}Заявка №${row.id} · ${esc(row.status_label)}`;
  el('modal-body').innerHTML = modalHtml(row, data.history, data.attachments || []);
  el('overlay').hidden = false;
  document.body.style.overflow = 'hidden';

  el('modal-body').querySelectorAll('.status-btn').forEach((button) => {
    button.addEventListener('click', () => setStatus(id, button.dataset.status));
  });
  el('items').querySelectorAll('[data-item]').forEach((box) => {
    box.addEventListener('change', () => toggleBought(id, Number(box.dataset.item), box.checked));
  });

  el('comment-only-btn').addEventListener('click', () => saveComment(id));

  const askDelete = el('delete-btn');
  const confirmBox = el('delete-confirm');
  askDelete.addEventListener('click', () => { askDelete.hidden = true; confirmBox.hidden = false; });
  el('delete-no').addEventListener('click', () => { confirmBox.hidden = true; askDelete.hidden = false; });
  el('delete-yes').addEventListener('click', () => deleteRequest(id));

  bindUpload(id);
}

function closeModal() {
  el('overlay').hidden = true;
  el('modal-body').innerHTML = '';
  state.openId = null;
  document.body.style.overflow = '';
  history.replaceState(null, '', location.pathname);
}

el('modal-close').addEventListener('click', closeModal);
el('overlay').addEventListener('click', (event) => {
  if (event.target === el('overlay')) closeModal();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !el('overlay').hidden) closeModal();
});

// Ссылка «Открыть панель» из MAX ведёт на /#<номер>. Если вкладка уже открыта,
// страница не перезагружается — ловим смену адреса вручную.
window.addEventListener('hashchange', () => {
  const id = Number(location.hash.replace('#', ''));
  if (id && id !== state.openId) {
    openRequest(id).catch(() => toast(`Заявки №${id} нет`));
  } else if (!id && !el('overlay').hidden) {
    closeModal();
  }
});

/* ------------------------------------------------------------- скриншоты */

function bindUpload(id) {
  const zone = el('dropzone');
  const input = el('file-input');

  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => uploadFiles(id, input.files));

  zone.addEventListener('dragover', (event) => {
    event.preventDefault();
    zone.classList.add('over');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', (event) => {
    event.preventDefault();
    zone.classList.remove('over');
    uploadFiles(id, event.dataTransfer.files);
  });

  el('shots').querySelectorAll('[data-remove]').forEach((button) => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      removeAttachment(id, Number(button.dataset.remove));
    });
  });
}

document.addEventListener('paste', (event) => {
  if (el('overlay').hidden || !state.openId) return;
  const files = [...(event.clipboardData?.files || [])];
  if (files.length) {
    event.preventDefault();
    uploadFiles(state.openId, files);
  }
});

async function uploadFiles(id, files) {
  const list = [...(files || [])].filter((file) => file.type.startsWith('image/'));
  if (!list.length) { toast('Нужен файл-картинка'); return; }

  let saved = 0;
  for (const file of list) {
    const form = new FormData();
    form.append('file', file, file.name || 'screenshot.png');
    try {
      await api(`/api/requests/${id}/attachments`, { method: 'POST', body: form });
      saved += 1;
    } catch (error) {
      const code = error.data?.error;
      toast(code === 'too_large' ? 'Файл больше 10 МБ'
        : code === 'unsupported_type' ? `Такой формат не принимаем: ${error.data.detail || ''}`
        : 'Не удалось загрузить файл');
    }
  }
  if (saved) {
    toast(saved === 1 ? 'Скриншот приложен' : `Приложено скриншотов: ${saved}`);
    await openRequest(id);
    await loadList();
  }
}

async function toggleBought(requestId, itemId, bought) {
  const result = await api(`/api/items/${itemId}/bought`, {
    method: 'POST',
    body: JSON.stringify({ bought }),
  });
  const row = document.querySelector(`[data-row="${itemId}"]`);
  if (row) row.classList.toggle('bought', bought);
  if (result.request) el('items-title').textContent = itemsTitle(result.request);
  await loadList();
}

async function removeAttachment(id, attachmentId) {
  await api(`/api/attachments/${attachmentId}`, { method: 'DELETE' });
  toast('Скриншот удалён');
  await openRequest(id);
  await loadList();
}

/* ------------------------------------------------------- статус и удаление */

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
  await openRequest(id);
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
  await openRequest(id);
}

async function deleteRequest(id) {
  const result = await api(`/api/requests/${id}`, { method: 'DELETE' });
  toast(result.author_notified
    ? `Заявка №${id} удалена, автору отправлено сообщение`
    : `Заявка №${id} удалена. Автору НЕ отправлено${result.notify_error ? `: ${result.notify_error}` : ''}`);
  state.knownIds.delete(id);
  closeModal();
  await loadList();
}

/* --------------------------------------------------------- поиск и старт */

let searchTimer = null;
el('search').addEventListener('input', (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.query = event.target.value.trim();
    loadList();
  }, 250);
});

el('refresh-btn').addEventListener('click', () => loadList());

/* ----------------------------------------------------------------- тема */

function currentTheme() {
  const chosen = document.documentElement.dataset.theme;
  if (chosen === 'light' || chosen === 'dark') return chosen;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  el('theme-toggle').setAttribute('aria-checked', String(theme === 'dark'));
  try {
    localStorage.setItem('pb_theme', theme);
  } catch (error) {
    /* приватный режим — просто не запоминаем выбор */
  }
}

el('theme-toggle').addEventListener('click', () => {
  applyTheme(currentTheme() === 'dark' ? 'light' : 'dark');
});
el('theme-toggle').setAttribute('aria-checked', String(currentTheme() === 'dark'));

async function boot() {
  const meta = await api('/api/meta');
  state.statuses = meta.statuses;
  await loadList();
  const hashId = Number(location.hash.replace('#', ''));
  if (hashId) openRequest(hashId).catch(() => history.replaceState(null, '', location.pathname));
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
  if (!el('app').hidden && el('overlay').hidden) loadList(true).catch(() => {});
}, 20000);

init();
