'use strict';

const state = {
  user: null,
  tab: 'pending',
  rows: [],
  employees: [],
  actor: null,      // кто сейчас работает на складе
  openItem: null,
};

const el = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
));
const num = (value) => {
  const n = Number(value || 0);
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
};

let toastTimer = null;
function toast(message) {
  const node = el('toast');
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, message.length > 70 ? 8000 : 3000);
}

async function api(path, options = {}) {
  const init = { ...options };
  if (init.body) init.headers = { 'Content-Type': 'application/json', ...(init.headers || {}) };
  const response = await fetch(path, init);
  if (response.status === 401) { showLogin(); throw new Error('unauthorized'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(data.error || 'failed'), { data });
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
}

el('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const response = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login: el('login').value.trim(), password: el('password').value }),
  });
  if (!response.ok) { showLogin('Неверный логин или пароль.'); return; }
  const data = await response.json();
  state.user = data.user;
  el('password').value = '';
  el('login-screen').hidden = true;
  el('app').hidden = false;
  el('user-chip').textContent = state.user || '';
  await boot();
});

el('logout-btn').addEventListener('click', async () => {
  await fetch('/api/logout', { method: 'POST' });
  showLogin();
});

/* ------------------------------------------------------- кто работает */

async function loadEmployees() {
  const data = await api('/api/employees');
  state.employees = data.employees;
  const saved = localStorage.getItem('pb_stock_actor');
  const select = el('actor');
  select.innerHTML = '<option value="">— выберите —</option>' + state.employees.map((e) => `
    <option value="${e.id}" ${String(e.id) === saved ? 'selected' : ''}>
      ${esc(e.full_name)}${e.department ? ` · ${esc(e.department)}` : ''}
    </option>`).join('');
  state.actor = state.employees.find((e) => String(e.id) === saved) || null;
}

el('actor').addEventListener('change', (event) => {
  const id = event.target.value;
  state.actor = state.employees.find((e) => String(e.id) === id) || null;
  try { localStorage.setItem('pb_stock_actor', id); } catch (e) { /* приватный режим */ }
});

el('add-employee').addEventListener('click', async () => {
  const name = prompt('ФИО сотрудника:');
  if (!name || !name.trim()) return;
  const data = await api('/api/employees', {
    method: 'POST',
    body: JSON.stringify({ full_name: name.trim(), is_stock: true }),
  });
  await loadEmployees();
  el('actor').value = data.employee.id;
  el('actor').dispatchEvent(new Event('change'));
  toast('Сотрудник добавлен');
});

/* --------------------------------------------------------------- списки */

function card(row) {
  const ordered = row.qty_number;
  const done = state.tab === 'pending' ? row.received : row.issued;
  const left = ordered !== null ? Math.max(ordered - done, 0) : null;
  const percent = ordered ? Math.min(100, Math.round((done / ordered) * 100)) : 0;

  const bits = [`заявка №${row.request_id}`, esc(row.requester || '')];
  if (row.deadline) bits.push(esc(row.deadline));
  const link = row.link
    ? ` · <a href="${esc(row.link)}" target="_blank" rel="noopener">ссылка</a>` : '';

  const actions = state.tab === 'pending'
    ? `<button class="btn btn-primary btn-lg" data-full="${row.id}">Принял полностью</button>
       <button class="btn btn-lg" data-part="${row.id}">Частично</button>`
    : `<button class="btn btn-primary btn-lg" data-issue="${row.id}">Выдать</button>`;

  return `
    <article class="stock-card">
      <div class="stock-main">
        <div class="stock-name">${esc(row.name)}<span class="stock-code">${esc(row.stock_code || '')}</span></div>
        <div class="stock-meta">${bits.filter(Boolean).join(' · ')}${link}</div>
        ${ordered !== null ? `<div class="progress"><i style="width:${percent}%"></i></div>` : ''}
      </div>
      <div class="stock-qty">
        <div class="big">${ordered !== null ? `${num(done)} / ${num(ordered)}` : num(done)}</div>
        <div class="sub">${esc(row.qty_unit || row.quantity || '')}${
          left ? ` · осталось ${num(left)}` : ''}</div>
      </div>
      <div class="stock-actions">${actions}</div>
    </article>`;
}

function historyRow(movement) {
  return `
    <div class="hist-row">
      <span class="hist-kind ${esc(movement.kind)}">${movement.kind === 'in' ? 'Принято' : 'Выдано'} ${num(movement.quantity)}</span>
      <span>${esc(movement.item_name || '')} <span class="stock-code">${esc(movement.stock_code || '')}</span></span>
      <span class="muted">${esc(movement.actor_name)}${
        movement.recipient_name ? ` → ${esc(movement.recipient_name)}` : ''}</span>
      <span class="hist-when">${esc(movement.created_at)}</span>
    </div>`;
}

async function load() {
  if (state.tab === 'history') {
    const data = await api('/api/stock/history');
    state.rows = data.movements;
    el('list').className = 'hist';
    el('list').innerHTML = data.movements.map(historyRow).join('');
  } else {
    const data = await api(`/api/stock/queue?kind=${state.tab}`);
    state.rows = data.items;
    el('list').className = 'stock-list';
    el('list').innerHTML = data.items.map(card).join('');
    bindCards();
  }
  el('empty').hidden = state.rows.length > 0;
  await refreshCounts();
}

async function refreshCounts() {
  const [pending, onHand] = await Promise.all([
    api('/api/stock/queue?kind=pending'),
    api('/api/stock/queue?kind=on_hand'),
  ]);
  el('count-pending').textContent = pending.items.length;
  el('count-onhand').textContent = onHand.items.length;
}

function bindCards() {
  el('list').querySelectorAll('[data-full]').forEach((button) => {
    button.addEventListener('click', () => receiveFull(Number(button.dataset.full)));
  });
  el('list').querySelectorAll('[data-part]').forEach((button) => {
    button.addEventListener('click', () => openForm(Number(button.dataset.part), 'in'));
  });
  el('list').querySelectorAll('[data-issue]').forEach((button) => {
    button.addEventListener('click', () => openForm(Number(button.dataset.issue), 'out'));
  });
}

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t === tab));
    state.tab = tab.dataset.tab;
    load();
  });
});

el('refresh-btn').addEventListener('click', () => load());

/* ----------------------------------------------------------- операции */

function requireActor() {
  if (!state.actor) {
    toast('Сначала выберите, кто работает — список вверху справа');
    el('actor').focus();
    return false;
  }
  return true;
}

async function send(payload) {
  const result = await api('/api/stock/movement', { method: 'POST', body: JSON.stringify(payload) });
  const messages = [];
  if (payload.kind === 'in') messages.push('Принято');
  else messages.push('Выдано');
  if (result.request_arrived) {
    messages.push(result.author_notified
      ? 'заявка собрана, автору отправлено сообщение'
      : 'заявка собрана');
  }
  if (result.request_completed) messages.push('заявка закрыта');
  toast(messages.join(' · '));
  closeModal();
  await load();
}

async function receiveFull(itemId) {
  if (!requireActor()) return;
  const row = state.rows.find((r) => r.id === itemId);
  const left = row.qty_number !== null ? Math.max(row.qty_number - row.received, 0) : 0;
  await send({
    kind: 'in',
    item_id: itemId,
    quantity: left,
    close: true,
    actor_name: state.actor.full_name,
    actor_employee_id: state.actor.id,
  });
}

function openForm(itemId, kind) {
  if (!requireActor()) return;
  const row = state.rows.find((r) => r.id === itemId);
  state.openItem = row;

  const left = kind === 'in'
    ? (row.qty_number !== null ? Math.max(row.qty_number - row.received, 0) : 1)
    : row.on_hand;

  const people = state.employees.map((e) =>
    `<option value="${e.id}" ${e.full_name === row.author_name ? 'selected' : ''}>${esc(e.full_name)}</option>`
  ).join('');

  el('modal-title').textContent = kind === 'in' ? 'Приём на склад' : 'Выдача со склада';
  el('modal-body').innerHTML = `
    <div class="stock-name">${esc(row.name)}</div>
    <div class="stock-meta" style="margin-bottom:16px">
      заявка №${row.request_id} · заказано ${row.qty_number !== null ? num(row.qty_number) : '—'}
      ${esc(row.qty_unit || '')} · ${kind === 'in' ? `принято ${num(row.received)}` : `на складе ${num(row.on_hand)}`}
    </div>

    <div class="form-row">
      <label>Количество</label>
      <input type="number" id="qty" class="qty-input" min="0" step="any" value="${num(left)}">
    </div>

    ${kind === 'out' ? `
    <div class="form-row">
      <label>Кому выдали</label>
      <select id="recipient">
        <option value="">— не из списка —</option>
        ${people}
      </select>
    </div>
    <div class="form-row">
      <label>Если получателя нет в списке — впишите</label>
      <input type="text" id="recipient-other" placeholder="ФИО">
    </div>` : ''}

    <div class="form-row">
      <label>Примечание (необязательно)</label>
      <input type="text" id="note" placeholder="например: привезли частично, остальное в пятницу">
    </div>

    <div class="row-actions">
      <button class="btn btn-primary btn-lg" id="do-move">${kind === 'in' ? 'Принять' : 'Выдать'}</button>
      <button class="btn btn-lg" id="do-close">${kind === 'in' ? 'Принять и закрыть' : 'Выдать всё и закрыть'}</button>
    </div>`;

  el('overlay').hidden = false;
  el('qty').focus();
  el('qty').select();

  const collect = (close) => {
    const payload = {
      kind,
      item_id: itemId,
      quantity: Number(el('qty').value || 0),
      close,
      note: el('note').value.trim(),
      actor_name: state.actor.full_name,
      actor_employee_id: state.actor.id,
    };
    if (kind === 'out') {
      const chosen = el('recipient').value;
      const other = el('recipient-other').value.trim();
      if (chosen) {
        const person = state.employees.find((e) => String(e.id) === chosen);
        payload.recipient_employee_id = person.id;
        payload.recipient_name = person.full_name;
      } else if (other) {
        payload.recipient_name = other;
      }
    }
    return payload;
  };

  el('do-move').addEventListener('click', () => send(collect(false)));
  el('do-close').addEventListener('click', () => send(collect(true)));
}

function closeModal() {
  el('overlay').hidden = true;
  el('modal-body').innerHTML = '';
  state.openItem = null;
}

el('modal-close').addEventListener('click', closeModal);
el('overlay').addEventListener('click', (event) => {
  if (event.target === el('overlay')) closeModal();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !el('overlay').hidden) closeModal();
});

/* -------------------------------------------------- поиск по коду */

el('scan').addEventListener('keydown', async (event) => {
  if (event.key !== 'Enter') return;
  const code = el('scan').value.trim();
  if (!code) return;
  el('scan').value = '';
  try {
    const found = await api(`/api/stock/find?code=${encodeURIComponent(code)}`);
    const item = found.item;
    // открываем ту вкладку, где позиция реально находится
    state.tab = item.received_done ? 'on_hand' : 'pending';
    document.querySelectorAll('.tab').forEach((t) =>
      t.classList.toggle('active', t.dataset.tab === state.tab));
    await load();
    const row = state.rows.find((r) => r.id === item.id);
    if (row) openForm(item.id, state.tab === 'pending' ? 'in' : 'out');
    else toast(`Позиция ${code} уже закрыта`);
  } catch (error) {
    toast(`Код ${code} не найден`);
  }
});

/* ------------------------------------------------------------- старт */

async function boot() {
  await loadEmployees();
  await load();
  setInterval(() => { if (!el('app').hidden && el('overlay').hidden) load().catch(() => {}); }, 30000);
}

async function init() {
  const meta = await fetch('/api/meta').then((r) => r.json()).catch(() => null);
  if (!meta || !meta.user) { showLogin(); return; }
  state.user = meta.user;
  el('login-screen').hidden = true;
  el('app').hidden = false;
  el('user-chip').textContent = state.user;
  await boot();
}

init();
