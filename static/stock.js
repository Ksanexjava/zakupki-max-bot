'use strict';

/* ================================================================ основа */

const state = {
  user: null,
  role: null,
  employees: [],
  actor: null,          // кто сейчас работает
  categories: [],       // дерево
  catPath: {},          // id -> «Медицина → Расходники»
  catParent: {},        // id подкатегории -> id раздела
  locations: [],
  view: 'priemka',
  arg: null,
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
  toastTimer = setTimeout(() => { node.hidden = true; }, message.length > 70 ? 8000 : 3200);
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
const post = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body) });

function explain(error) {
  const data = error.data || {};
  if (data.error === 'not_enough') return `Столько нет: в этом месте ${num(data.available)}`;
  if (data.error === 'forbidden') return 'Нет прав на это действие';
  return 'Не получилось — проверьте данные';
}

/* =============================================================== вход */

function showLogin(message) {
  el('app').hidden = true;
  el('overlay').hidden = true;
  el('login-screen').hidden = false;
  el('login-error').hidden = !message;
  el('login-error').textContent = message || '';
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
  el('password').value = '';
  await start(data.user, data.role);
});

el('logout-btn').addEventListener('click', async () => {
  await fetch('/api/logout', { method: 'POST' });
  showLogin();
});

/* ===================================================== справочники */

async function loadEmployees() {
  state.employees = (await api('/api/employees')).employees;
  let saved = null;
  try { saved = localStorage.getItem('pb_stock_actor'); } catch (e) { /* приватный режим */ }
  el('actor').innerHTML = '<option value="">— кто работает —</option>' + state.employees.map((e) =>
    `<option value="${e.id}" ${String(e.id) === saved ? 'selected' : ''}>${esc(e.full_name)}</option>`
  ).join('');
  state.actor = state.employees.find((e) => String(e.id) === saved) || null;
}

async function loadCategories() {
  state.categories = (await api('/api/stock/categories')).categories;
  state.catPath = {};
  state.catParent = {};
  for (const top of state.categories) {
    state.catPath[top.id] = top.name;
    for (const child of top.children) {
      state.catPath[child.id] = `${top.name} → ${child.name}`;
      state.catParent[child.id] = top.id;
    }
  }
}

async function loadLocations() {
  state.locations = (await api('/api/stock/locations')).locations;
}

el('actor').addEventListener('change', (event) => {
  const id = event.target.value;
  state.actor = state.employees.find((e) => String(e.id) === id) || null;
  try { localStorage.setItem('pb_stock_actor', id); } catch (e) { /* приватный режим */ }
});

el('add-employee').addEventListener('click', () => {
  openModal('Новый сотрудник', `
    <div class="form-row"><label>ФИО</label>
      <input type="text" id="f-emp-name" placeholder="Иванова Мария Петровна"></div>
    <div class="form-row"><label>Отделение (необязательно)</label>
      <input type="text" id="f-emp-dep"></div>
    <label class="check-row"><input type="checkbox" id="f-emp-stock" checked> Работает на складе — сразу выбрать</label>
    <button class="btn btn-primary btn-lg btn-block" id="f-ok">Добавить</button>`);
  el('f-ok').addEventListener('click', async () => {
    const name = el('f-emp-name').value.trim();
    if (!name) { toast('Введите ФИО'); return; }
    const isStock = el('f-emp-stock').checked;
    const data = await post('/api/employees', {
      full_name: name, department: el('f-emp-dep').value.trim(), is_stock: isStock,
    });
    closeModal();
    await loadEmployees();
    if (isStock) {
      el('actor').value = data.employee.id;
      el('actor').dispatchEvent(new Event('change'));
    }
    toast('Сотрудник добавлен');
  });
});

function requireActor() {
  if (state.actor) return true;
  toast('Сначала выберите, кто работает — список вверху');
  el('actor').focus();
  return false;
}
const actorPayload = () => ({ actor_name: state.actor.full_name, actor_employee_id: state.actor.id });

function categoryOptions(selected) {
  return '<option value="">— без категории —</option>' + state.categories.map((top) => `
    <optgroup label="${esc(top.name)}">
      <option value="${top.id}" ${top.id === selected ? 'selected' : ''}>${esc(top.name)} (весь раздел)</option>
      ${top.children.map((c) => `<option value="${c.id}" ${c.id === selected ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
    </optgroup>`).join('');
}

/** Подходит ли место под категорию товара: совпадает подкатегория или раздел. */
function locationFits(location, categoryId) {
  if (!categoryId || !location.category_ids.length) return false;
  const parent = state.catParent[categoryId];
  return location.category_ids.includes(categoryId) || (parent && location.category_ids.includes(parent));
}

/** Где лежит — коротко: «в приёмке», «SH-01» или «SH-01 › BX-001» для коробки на полке. */
function whereText(locationId, code) {
  if (!code) return '';
  const loc = state.locations.find((l) => l.id === locationId);
  if (loc && loc.kind === 'zone') return 'в приёмке';
  const parent = loc && loc.parent_id ? state.locations.find((l) => l.id === loc.parent_id) : null;
  return parent ? `${parent.code} › ${code}` : code;
}

function locationLabel(location) {
  const kind = location.kind === 'box' ? 'коробка' : location.kind === 'zone' ? 'зона' : 'полка';
  return `${location.code} · ${location.name} (${kind})`;
}

function locationOptions(categoryId, excludeId) {
  const usable = state.locations.filter((l) => l.kind !== 'zone' && l.id !== excludeId);
  const fit = usable.filter((l) => locationFits(l, categoryId));
  const rest = usable.filter((l) => !locationFits(l, categoryId));
  const opt = (l) => `<option value="${l.id}">${esc(locationLabel(l))}</option>`;
  return (fit.length ? `<optgroup label="Подходят по категории">${fit.map(opt).join('')}</optgroup>` : '')
    + (rest.length ? `<optgroup label="${fit.length ? 'Остальные' : 'Места'}">${rest.map(opt).join('')}</optgroup>` : '');
}

function employeeOptions(selectedName) {
  return '<option value="">— не из списка —</option>' + state.employees.map((e) =>
    `<option value="${e.id}" ${e.full_name === selectedName ? 'selected' : ''}>${esc(e.full_name)}</option>`
  ).join('');
}

function recipientFrom(selectId, otherId) {
  const chosen = el(selectId).value;
  if (chosen) {
    const person = state.employees.find((e) => String(e.id) === chosen);
    return { recipient_employee_id: person.id, recipient_name: person.full_name };
  }
  const other = el(otherId).value.trim();
  return other ? { recipient_name: other } : {};
}

/* ============================================================= модалка */

function openModal(title, html) {
  el('modal-title').textContent = title;
  el('modal-body').innerHTML = html;
  el('overlay').hidden = false;
  const first = el('modal-body').querySelector('input, select, textarea');
  if (first) first.focus();
}
function closeModal() {
  el('overlay').hidden = true;
  el('modal-body').innerHTML = '';
}
el('modal-close').addEventListener('click', closeModal);
el('overlay').addEventListener('click', (event) => { if (event.target === el('overlay')) closeModal(); });
document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  if (!el('scan-overlay').hidden) closePickScanner();
  else if (!el('overlay').hidden) closeModal();
});

/* ============================================================ сканер */

const Scanner = {
  stream: null,
  raf: null,
  detector: null,

  /** Живая камера работает только по HTTPS (или на localhost). */
  liveAvailable() {
    return window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;
  },

  async start(video, onCode) {
    this.stop();
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } }, audio: false,
    });
    video.srcObject = this.stream;
    video.setAttribute('playsinline', '');
    await video.play();
    if ('BarcodeDetector' in window) {
      try { this.detector = new BarcodeDetector({ formats: ['qr_code'] }); } catch (e) { this.detector = null; }
    }
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    const tick = async () => {
      if (!this.stream) return;
      if (video.readyState === video.HAVE_ENOUGH_DATA) {
        let text = null;
        if (this.detector) {
          try {
            const found = await this.detector.detect(video);
            if (found.length) text = found[0].rawValue;
          } catch (e) { this.detector = null; }
        } else {
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          ctx.drawImage(video, 0, 0);
          const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);
          const code = window.jsQR && jsQR(frame.data, frame.width, frame.height, { inversionAttempts: 'dontInvert' });
          if (code) text = code.data;
        }
        if (text) {
          this.stop();
          if (navigator.vibrate) navigator.vibrate(60);
          onCode(text);
          return;
        }
      }
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  },

  stop() {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = null;
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null;
  },

  /** Запасной путь без HTTPS: сфотографировать код и распознать снимок. */
  async decodeFile(file) {
    const url = URL.createObjectURL(file);
    try {
      const image = await new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = url;
      });
      const scale = Math.min(1, 1600 / Math.max(image.width, image.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(image.width * scale);
      canvas.height = Math.round(image.height * scale);
      const ctx = canvas.getContext('2d');
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const code = jsQR(frame.data, frame.width, frame.height);
      return code ? code.data : null;
    } finally {
      URL.revokeObjectURL(url);
    }
  },
};

/** Блок сканера: камера, фото или ручной ввод. onCode получает строку из QR. */
function scannerHtml(prefix) {
  const live = Scanner.liveAvailable();
  return `
    <div class="scanner">
      ${live ? `
        <div class="scanner-video" id="${prefix}-box" hidden>
          <video id="${prefix}-video" muted playsinline></video>
          <div class="frame"></div>
        </div>` : ''}
      <div class="scanner-actions">
        ${live
          ? `<button class="btn btn-primary btn-lg" id="${prefix}-start">Включить камеру</button>`
          : `<label class="btn btn-primary btn-lg" style="text-align:center">
               Сфотографировать QR
               <input type="file" accept="image/*" capture="environment" id="${prefix}-photo" hidden>
             </label>`}
        <div class="inline-row">
          <input type="text" id="${prefix}-manual" placeholder="или введите код: SH-01, BX-001, IN-00001">
          <button class="btn" id="${prefix}-go" style="flex:0">Найти</button>
        </div>
      </div>
      ${live ? '' : `<p class="scanner-note">Живая камера включится, когда у сайта появится HTTPS.
        Пока можно сфотографировать код или навести на него обычную камеру телефона — откроется эта же страница.</p>`}
    </div>`;
}

function bindScanner(prefix, onCode) {
  const go = () => {
    const value = el(`${prefix}-manual`).value.trim();
    if (value) onCode(value);
  };
  el(`${prefix}-go`).addEventListener('click', go);
  el(`${prefix}-manual`).addEventListener('keydown', (event) => { if (event.key === 'Enter') go(); });

  const startBtn = el(`${prefix}-start`);
  if (startBtn) {
    startBtn.addEventListener('click', async () => {
      el(`${prefix}-box`).hidden = false;
      startBtn.hidden = true;
      try {
        await Scanner.start(el(`${prefix}-video`), (text) => {
          el(`${prefix}-box`).hidden = true;
          startBtn.hidden = false;
          startBtn.textContent = 'Сканировать ещё';
          onCode(text);
        });
      } catch (error) {
        el(`${prefix}-box`).hidden = true;
        startBtn.hidden = false;
        toast('Камера недоступна — разрешите доступ в настройках браузера');
      }
    });
  }
  const photo = el(`${prefix}-photo`);
  if (photo) {
    photo.addEventListener('change', async () => {
      const file = photo.files[0];
      if (!file) return;
      const text = await Scanner.decodeFile(file);
      photo.value = '';
      if (text) onCode(text);
      else toast('Не вижу QR на снимке — попробуйте ближе и ровнее');
    });
  }
}

/* «Скан полки» внутри формы: открывает сканер поверх и возвращает место */
let pickResolve = null;
function pickLocationByScan() {
  return new Promise((resolve) => {
    pickResolve = resolve;
    el('scan-overlay-title').textContent = 'Отсканируйте полку или коробку';
    el('scan-overlay-body').innerHTML = scannerHtml('pick');
    el('scan-overlay').hidden = false;
    bindScanner('pick', async (text) => {
      try {
        const found = await api(`/api/stock/resolve?code=${encodeURIComponent(text)}`);
        if (!['shelf', 'box'].includes(found.type)) { toast('Это не полка и не коробка'); return; }
        const location = state.locations.find((l) => l.id === found.id);
        closePickScanner(location || null);
      } catch (e) {
        toast(`Код ${text} не найден`);
      }
    });
  });
}
function closePickScanner(result = null) {
  Scanner.stop();
  el('scan-overlay').hidden = true;
  el('scan-overlay-body').innerHTML = '';
  if (pickResolve) { pickResolve(result); pickResolve = null; }
}
el('scan-overlay-close').addEventListener('click', () => closePickScanner());

/* ============================================================ навигация */

const VIEWS = {
  priemka: { title: 'Приёмка', render: viewReceiving },
  hranenie: { title: 'Хранение', render: viewStorage },
  vydacha: { title: 'Выдача', render: viewIssue },
  scan: { title: 'Сканер', render: viewScan },
  tovary: { title: 'Товары', render: viewProducts },
  istoriya: { title: 'История', render: viewHistory },
};
// старые адреса из закладок ведут в новые разделы
const ALIASES = { razmeshchenie: 'priemka', mesta: 'scan', qr: 'scan' };

function renderNav() {
  el('stock-nav').innerHTML = Object.entries(VIEWS).map(([key, view]) =>
    `<a href="#/${key}" class="${key === state.view ? 'active' : ''}" data-view="${key}">${esc(view.title)}<span class="count" id="nav-count-${key}"></span></a>`
  ).join('');
  // на телефоне вкладки прокручиваются — держим текущую в поле зрения
  const active = el('stock-nav').querySelector('.active');
  if (active) active.scrollIntoView({ inline: 'center', block: 'nearest' });
}

async function route() {
  Scanner.stop();
  closeModal();
  const [, raw, ...rest] = (location.hash || '#/priemka').split('/');
  const view = ALIASES[raw] || raw;
  state.view = VIEWS[view] ? view : 'priemka';
  state.arg = rest.length ? decodeURIComponent(rest.join('/')) : null;
  renderNav();
  document.title = `${VIEWS[state.view].title} — склад`;
  el('view').innerHTML = '<p class="muted">Загружаю…</p>';
  try {
    await VIEWS[state.view].render(el('view'));
  } catch (error) {
    if (error.message !== 'unauthorized') {
      el('view').innerHTML = '<p class="empty">Не удалось загрузить. Обновите страницу.</p>';
    }
  }
  refreshCounts().catch(() => {});
}
window.addEventListener('hashchange', route);

async function refreshCounts() {
  const [pending, receiving, onHand] = await Promise.all([
    api('/api/stock/queue?kind=pending'),
    api('/api/stock/receiving'),
    api('/api/stock/queue?kind=on_hand'),
  ]);
  const set = (key, value) => { const n = el(`nav-count-${key}`); if (n) n.textContent = value || ''; };
  // ждём поставку + лежит неразложенным
  set('priemka', pending.items.length + bulkItems(receiving).length + receiving.instances.length);
  set('vydacha', onHand.items.length);
}

/* =============================================== приёмка и размещение */

/** Поштучный товар показываем экземплярами, а не строкой количества (в приёмке и на полке). */
const bulkItems = (zone) => zone.items.filter((i) => !zone.instances.some((x) => x.product_id === i.product_id));
const hasPlaces = () => state.locations.some((l) => l.kind !== 'zone');
const labelsUrl = (codes) => `/labels?codes=${encodeURIComponent(codes.join(','))}`;

function requestCard(row, mode) {
  const ordered = row.qty_number;
  const done = mode === 'in' ? row.received : row.issued;
  const left = ordered !== null ? Math.max(ordered - done, 0) : null;
  const percent = ordered ? Math.min(100, Math.round((done / ordered) * 100)) : 0;
  const link = row.link ? ` · <a href="${esc(row.link)}" target="_blank" rel="noopener">ссылка</a>` : '';
  const actions = mode === 'in'
    ? `<button class="btn btn-primary btn-lg" data-full="${row.id}">Принял полностью</button>
       <button class="btn btn-lg" data-part="${row.id}">Частично</button>`
    : `<button class="btn btn-primary btn-lg" data-issue="${row.id}">Выдать</button>`;
  return `
    <article class="stock-card">
      <div class="stock-main">
        <div class="stock-name">${esc(row.name)} <span class="code-chip">${esc(row.stock_code || '')}</span></div>
        <div class="stock-meta">заявка №${row.request_id} · ${esc(row.requester || '')}${row.deadline ? ` · ${esc(row.deadline)}` : ''}${link}</div>
        ${ordered !== null ? `<div class="progress"><i style="width:${percent}%"></i></div>` : ''}
      </div>
      <div class="stock-qty">
        <div class="big">${ordered !== null ? `${num(done)} / ${num(ordered)}` : num(done)}</div>
        <div class="sub">${esc(row.qty_unit || row.quantity || '')}${left ? ` · осталось ${num(left)}` : ''}</div>
      </div>
      <div class="stock-actions">${actions}</div>
    </article>`;
}

async function viewReceiving(root) {
  await loadLocations();
  const [data, zone] = await Promise.all([api('/api/stock/queue?kind=pending'), api('/api/stock/receiving')]);
  const bulk = bulkItems(zone);
  const waiting = bulk.length + zone.instances.length;
  root.innerHTML = `
    <div class="view-head"><h2>Приёмка и размещение</h2></div>
    <p class="view-hint">Отметьте, что привезли, и сразу положите на полку или в коробку.
      Что не успели разложить — ждёт ниже, в «Лежит в приёмке».</p>
    ${hasPlaces() ? '' : `<p class="view-hint">Полок пока нет — заведите их в разделе <a href="#/scan">«Сканер»</a>,
      тогда принятое можно будет сразу раскладывать.</p>`}

    <div class="group-title">Ждём поставку${data.items.length ? ` · ${data.items.length}` : ''}</div>
    <div class="stock-list">${data.items.map((row) => requestCard(row, 'in')).join('')}</div>
    ${data.items.length ? '' : '<p class="empty">Ничего не ждём — все заказы приняты.</p>'}

    <div class="group-title" style="margin-top:26px">Лежит в приёмке — разложить${waiting ? ` · ${waiting}` : ''}</div>
    <div class="stock-list">
      ${zone.instances.map((i) => `
        <article class="stock-card">
          <div class="stock-main">
            <div class="stock-name">${esc(i.product_name)} <span class="code-chip">${esc(i.code)}</span></div>
            <div class="stock-meta">поштучно · ${esc(state.catPath[i.category_id] || 'без категории')}</div>
          </div>
          <div class="stock-actions">
            <a class="btn btn-lg" href="${labelsUrl([i.code])}" target="_blank" rel="noopener">QR</a>
            <button class="btn btn-primary btn-lg" data-place-inst="${i.id}">Разместить</button>
          </div>
        </article>`).join('')}
      ${bulk.map((i) => `
        <article class="stock-card">
          <div class="stock-main">
            <div class="stock-name">${esc(i.name)}</div>
            <div class="stock-meta">${esc(i.path)}</div>
          </div>
          <div class="stock-qty"><div class="big">${num(i.quantity)}</div><div class="sub">${esc(i.unit || '')}</div></div>
          <div class="stock-actions"><button class="btn btn-primary btn-lg" data-place="${i.product_id}">Разместить</button></div>
        </article>`).join('')}
    </div>
    ${waiting ? '' : '<p class="empty">Всё разложено по местам.</p>'}`;

  const rows = Object.fromEntries(data.items.map((r) => [r.id, r]));
  root.querySelectorAll('[data-full]').forEach((b) => b.addEventListener('click', () => {
    const row = rows[b.dataset.full];
    const left = row.qty_number !== null ? Math.max(row.qty_number - row.received, 0) : 1;
    receive(row, left, true);
  }));
  root.querySelectorAll('[data-part]').forEach((b) => b.addEventListener('click', () => receiveForm(rows[b.dataset.part])));
  root.querySelectorAll('[data-place]').forEach((b) => b.addEventListener('click', () => {
    placeForm(bulk.find((i) => String(i.product_id) === b.dataset.place));
  }));
  root.querySelectorAll('[data-place-inst]').forEach((b) => b.addEventListener('click', () => {
    placeForm(null, zone.instances.find((i) => String(i.id) === b.dataset.placeInst));
  }));
}

function receiveForm(row) {
  if (!requireActor()) return;
  const left = row.qty_number !== null ? Math.max(row.qty_number - row.received, 0) : 1;
  openModal('Приёмка', `
    <div class="stock-name">${esc(row.name)}</div>
    <div class="stock-meta" style="margin-bottom:14px">заявка №${row.request_id} · заказано ${row.qty_number !== null ? num(row.qty_number) : '—'} ${esc(row.qty_unit || '')} · принято ${num(row.received)}</div>
    <div class="form-row"><label>Сколько приняли</label>
      <input type="number" id="f-qty" class="qty-input" min="0" step="any" value="${num(left)}"></div>
    <div class="form-row"><label>Примечание</label>
      <input type="text" id="f-note" placeholder="например: остальное привезут в пятницу"></div>
    <div class="row-actions">
      <button class="btn btn-primary btn-lg" id="f-ok">Принять</button>
      <button class="btn btn-lg" id="f-close">Принять и закрыть позицию</button>
    </div>`);
  const submit = (close) => receive(row, Number(el('f-qty').value || 0), close, el('f-note').value.trim());
  el('f-ok').addEventListener('click', () => submit(false));
  el('f-close').addEventListener('click', () => submit(true));
}

async function receive(row, quantity, close, note = '') {
  if (!requireActor()) return;
  const result = await post('/api/stock/movement', {
    kind: 'in', item_id: row.id, quantity, close, note, ...actorPayload(),
  });
  const parts = ['Принято'];
  if (result.request_arrived) parts.push(result.author_notified ? 'автору отправлено сообщение' : 'заявка собрана');
  toast(parts.join(' · '));
  await route();  // перерисовка закрывает модалки — следующий шаг открываем после
  if (quantity > 0) await afterReceive(result);
}

/** Сразу после приёмки: наклейки для поштучного товара и выбор места. */
async function afterReceive(result) {
  const codes = result.instances_created || [];
  const zone = await api('/api/stock/receiving');
  if (codes.length) {
    placeInstancesForm(zone.instances.filter((i) => codes.includes(i.code)), codes);
    return;
  }
  if (!hasPlaces()) return;
  const item = bulkItems(zone).find((i) => i.product_id === (result.item && result.item.product_id));
  if (item) placeForm(item, null, null, 'Принято — куда положить?');
}

/** Поштучный товар: печать наклеек и одно место для всех единиц сразу. */
function placeInstancesForm(instances, codes) {
  const categoryId = instances.length ? instances[0].category_id : null;
  openModal('Принято поштучно', `
    <div class="stock-name">${esc(instances.length ? instances[0].product_name : '')}</div>
    <div class="stock-meta" style="margin-bottom:12px">Каждой единице присвоен номер:
      ${codes.map((c) => `<span class="code-chip">${esc(c)}</span>`).join(' ')}</div>
    <a class="btn btn-lg btn-block" href="${labelsUrl(codes)}" target="_blank" rel="noopener" style="margin-bottom:16px">Напечатать наклейки</a>
    ${hasPlaces() ? `
      <div class="form-row"><label>Куда поставить</label>
        <select id="f-loc">${locationOptions(categoryId)}</select></div>
      <div class="row-actions">
        <button class="btn btn-lg" id="f-scan">Сканировать полку</button>
        <button class="btn btn-primary btn-lg" id="f-ok">Поставить ${instances.length > 1 ? 'все' : ''}</button>
      </div>
      <button class="btn btn-quiet btn-block" id="f-later">Оставить в приёмке</button>` : `
      <p class="muted">Полок пока нет — товар полежит в приёмке.</p>`}`);
  if (!hasPlaces()) return;
  el('f-later').addEventListener('click', closeModal);
  el('f-scan').addEventListener('click', async () => {
    const location = await pickLocationByScan();
    if (location) { el('f-loc').value = location.id; toast(`Выбрано: ${location.code}`); }
  });
  el('f-ok').addEventListener('click', async () => {
    if (!requireActor()) return;
    const target = Number(el('f-loc').value);
    if (!target) { toast('Выберите место'); return; }
    let placed = 0;
    for (const instance of instances) {
      try {
        await post('/api/stock/place', { instance_id: instance.id, to_location_id: target, ...actorPayload() });
        placed += 1;
      } catch (error) { /* покажем итог ниже */ }
    }
    toast(placed === instances.length ? 'Поставлено' : `Поставлено ${placed} из ${instances.length}`);
    await route();
  });
}

/** Форма размещения. item — товар количеством, instance — экземпляр поштучно. */
function placeForm(item, instance = null, fromLocationId = null, title = null) {
  if (!requireActor()) return;
  if (!hasPlaces()) { toast('Сначала заведите полки в разделе «Сканер»'); return; }
  const categoryId = item ? item.category_id : instance.category_id;
  openModal(title || (instance ? 'Разместить экземпляр' : 'Разместить'), `
    <div class="stock-name">${esc(item ? item.name : instance.product_name)}
      ${instance ? `<span class="code-chip">${esc(instance.code)}</span>` : ''}</div>
    <div class="stock-meta" style="margin-bottom:14px">${esc(state.catPath[categoryId] || 'без категории')}</div>
    ${item ? `<div class="form-row"><label>Сколько кладём</label>
      <input type="number" id="f-qty" class="qty-input" min="0" step="any" value="${num(item.quantity)}"></div>` : ''}
    <div class="form-row"><label>Куда</label>
      <select id="f-loc">${locationOptions(categoryId, fromLocationId)}</select></div>
    <div class="row-actions">
      <button class="btn btn-lg" id="f-scan">Сканировать полку</button>
      <button class="btn btn-primary btn-lg" id="f-ok">Положить</button>
    </div>
    ${title ? '<button class="btn btn-quiet btn-block" id="f-later">Оставить в приёмке</button>' : ''}`);
  if (title) el('f-later').addEventListener('click', closeModal);
  el('f-scan').addEventListener('click', async () => {
    const location = await pickLocationByScan();
    if (location) { el('f-loc').value = location.id; toast(`Выбрано: ${location.code}`); }
  });
  el('f-ok').addEventListener('click', async () => {
    const target = Number(el('f-loc').value);
    if (!target) { toast('Выберите место'); return; }
    try {
      const result = await post('/api/stock/place', {
        to_location_id: target,
        from_location_id: fromLocationId,
        product_id: item ? item.product_id : null,
        quantity: item ? Number(el('f-qty').value || 0) : 1,
        instance_id: instance ? instance.id : null,
        ...actorPayload(),
      });
      closeModal();
      toast(`Положено: ${result.to}`);
      await route();
    } catch (error) {
      toast(explain(error));
    }
  });
}

/* ============================================================ хранение */

/** 1 товар, 2 товара, 5 товаров. */
function plural(n, one, few, many) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
const productsCount = (n) => `${n} ${plural(n, 'товар', 'товара', 'товаров')}`;

// какие разделы раскрыты — переживает перерисовку после выдачи
const openGroups = new Set();

/** Раскладывает остатки по дереву: раздел → подкатегория → товары. */
function storageTree(products) {
  const tops = state.categories.map((top) => ({
    id: `t${top.id}`,
    name: top.name,
    direct: [],
    subs: top.children.map((child) => ({ id: `s${child.id}`, name: child.name, products: [] })),
  }));
  const byTop = Object.fromEntries(state.categories.map((top, index) => [top.id, tops[index]]));
  const none = { id: 'none', name: 'Без категории', direct: [], subs: [] };
  for (const row of products) {
    const cid = row.category_id;
    const parent = state.catParent[cid];
    if (parent && byTop[parent]) {
      byTop[parent].subs.find((s) => s.id === `s${cid}`).products.push(row);
    } else if (byTop[cid]) {
      byTop[cid].direct.push(row);
    } else {
      none.direct.push(row);
    }
  }
  return none.direct.length ? [...tops, none] : tops;
}

function productRow(row) {
  return `
    <div class="prod-row ${row.low ? 'low' : ''}">
      <div class="prod-main">
        <div class="prod-name">${esc(row.name)}${row.low ? '<span class="badge-low">мало</span>' : ''}</div>
        <div class="place-chips">${row.places.map((p) =>
          `<span class="place-chip">${esc(whereText(p.location_id, p.code))} · <b>${num(p.quantity)}</b></span>`).join('')}</div>
      </div>
      <div class="prod-qty"><b>${num(row.total)}</b> ${esc(row.unit || '')}
        ${row.min_stock ? `<div class="sub">мин. ${num(row.min_stock)}</div>` : ''}</div>
      <button class="btn" data-out="${row.product_id}">Выдать</button>
    </div>`;
}

async function viewStorage(root) {
  await loadLocations();
  const data = await api('/api/stock/overview');
  const products = data.products;
  const lowCount = products.filter((r) => r.low).length;
  const inZone = products.filter((r) => r.places.some((p) => whereText(p.location_id, p.code) === 'в приёмке')).length;

  root.innerHTML = `
    <div class="view-head"><h2>Хранение</h2></div>
    <div class="dash-stats">
      <div class="dash-stat"><div class="dash-num">${products.length}</div><div class="dash-label">${plural(products.length, 'товар', 'товара', 'товаров')} на складе</div></div>
      <div class="dash-stat ${lowCount ? 'warn' : ''}"><div class="dash-num">${lowCount}</div><div class="dash-label">заканчивается</div></div>
      <a class="dash-stat" href="#/priemka"><div class="dash-num">${inZone}</div><div class="dash-label">ждут размещения</div></a>
    </div>
    <div class="search-row"><input type="search" id="f-search" placeholder="Поиск по названию"></div>
    <div id="storage-tree"></div>`;

  const draw = (query) => {
    const q = query.trim().toLowerCase();
    const match = (row) => !q || row.name.toLowerCase().includes(q);
    const tree = storageTree(products.filter(match));
    const html = tree.map((top) => {
      const subs = top.subs.filter((s) => s.products.length || !q);
      const total = top.direct.length + top.subs.reduce((sum, s) => sum + s.products.length, 0);
      if (q && !total) return '';
      const low = [...top.direct, ...top.subs.flatMap((s) => s.products)].filter((r) => r.low).length;
      const open = q ? total > 0 : openGroups.has(top.id);
      return `
        <details class="cat-block ${total ? '' : 'is-empty'}" data-group="${top.id}" ${open ? 'open' : ''}>
          <summary class="cat-head">
            <span class="cat-name">${esc(top.name)}</span>
            <span class="cat-meta">${total ? productsCount(total) : 'пусто'}${low ? ` · <span class="warn-text">мало: ${low}</span>` : ''}</span>
          </summary>
          <div class="cat-body">
            ${subs.map((sub) => {
              const subLow = sub.products.filter((r) => r.low).length;
              const subOpen = q ? sub.products.length > 0 : openGroups.has(sub.id);
              return `
                <details class="sub-block ${sub.products.length ? '' : 'is-empty'}" data-group="${sub.id}" ${subOpen ? 'open' : ''}>
                  <summary class="sub-head">
                    <span>${esc(sub.name)}</span>
                    <span class="cat-meta">${sub.products.length ? productsCount(sub.products.length) : 'пусто'}${subLow ? ` · <span class="warn-text">мало: ${subLow}</span>` : ''}</span>
                  </summary>
                  <div class="sub-body">${sub.products.map(productRow).join('')}</div>
                </details>`;
            }).join('')}
            ${top.direct.length ? `
              <div class="sub-block direct">
                ${top.subs.length ? '<div class="sub-head static">Без подкатегории</div>' : ''}
                <div class="sub-body">${top.direct.map(productRow).join('')}</div>
              </div>` : ''}
          </div>
        </details>`;
    }).join('');
    el('storage-tree').innerHTML = html || `<p class="empty">${products.length ? 'Ничего не нашлось.' : 'На складе пока пусто.'}</p>`;

    el('storage-tree').querySelectorAll('details[data-group]').forEach((node) => node.addEventListener('toggle', () => {
      if (q) return;  // при поиске раскрытие временное
      if (node.open) openGroups.add(node.dataset.group); else openGroups.delete(node.dataset.group);
    }));
    el('storage-tree').querySelectorAll('[data-out]').forEach((b) => b.addEventListener('click', () => {
      issueForm(products.find((r) => String(r.product_id) === b.dataset.out));
    }));
  };
  draw('');
  el('f-search').addEventListener('input', (event) => draw(event.target.value));
}

/** Выдача со склада без заявки — так разбирают расходники. */
async function issueForm(product, presetLocationId = null) {
  if (!requireActor()) return;
  let instances = [];
  if (product.serialized) {
    instances = (await api(`/api/stock/instances?product_id=${product.product_id}`)).instances
      .filter((i) => i.status === 'stock');
  }
  // принятое до обновления лежит без инвентарных номеров — его выдаём количеством
  const byInstance = instances.length > 0;
  openModal('Выдача со склада', `
    <div class="stock-name">${esc(product.name)}</div>
    <div class="stock-meta" style="margin-bottom:14px">всего ${num(product.total)} ${esc(product.unit || '')}</div>
    ${byInstance ? `
      <div class="form-row"><label>Какой экземпляр</label>
        <div class="pick-list">${instances.map((i, index) => `
          <label><input type="radio" name="f-inst" value="${i.id}" ${index === 0 ? 'checked' : ''}>
            <span class="code-chip">${esc(i.code)}</span> <span class="muted">${esc(whereText(i.location_id, i.location_code))}</span></label>`).join('')}</div></div>`
    : `
      <div class="form-row"><label>Откуда</label>
        <select id="f-from">${product.places.map((p) =>
          `<option value="${p.location_id}" ${p.location_id === presetLocationId ? 'selected' : ''}>${esc(whereText(p.location_id, p.code))} · ${esc(p.name)} — ${num(p.quantity)}</option>`).join('')}</select></div>
      <div class="form-row"><label>Сколько</label>
        <input type="number" id="f-qty" class="qty-input" min="0" step="any" value="1"></div>`}
    <div class="form-row"><label>Кому</label><select id="f-to">${employeeOptions('')}</select></div>
    <div class="form-row"><label>Если нет в списке — впишите</label><input type="text" id="f-to-other" placeholder="ФИО или отделение"></div>
    <div class="form-row"><label>Примечание</label><input type="text" id="f-note"></div>
    <button class="btn btn-primary btn-lg btn-block" id="f-ok">Выдать</button>`);

  el('f-ok').addEventListener('click', async () => {
    const payload = { ...actorPayload(), ...recipientFrom('f-to', 'f-to-other'), note: el('f-note').value.trim() };
    if (byInstance) {
      const chosen = el('modal-body').querySelector('input[name="f-inst"]:checked');
      if (!chosen) { toast('Выберите экземпляр'); return; }
      payload.instance_id = Number(chosen.value);
    } else {
      payload.product_id = product.product_id;
      payload.location_id = Number(el('f-from').value);
      payload.quantity = Number(el('f-qty').value || 0);
    }
    try {
      await post('/api/stock/issue', payload);
      closeModal();
      toast('Выдано');
      await route();
    } catch (error) {
      toast(explain(error));
    }
  });
}

/* ================================================= выдача по заявкам */

async function viewIssue(root) {
  const data = await api('/api/stock/queue?kind=on_hand');
  root.innerHTML = `
    <div class="view-head"><h2>Выдача по заявкам</h2></div>
    <p class="view-hint">Принятые позиции, которые ещё не отдали заказчику. Когда выдано всё по заявке — она закрывается сама.</p>
    <div class="stock-list">${data.items.map((row) => requestCard(row, 'out')).join('')}</div>
    ${data.items.length ? '' : '<p class="empty">Всё выдано.</p>'}`;
  const rows = Object.fromEntries(data.items.map((r) => [r.id, r]));
  root.querySelectorAll('[data-issue]').forEach((b) => b.addEventListener('click', () => issueByRequestForm(rows[b.dataset.issue])));
}

async function issueByRequestForm(row) {
  if (!requireActor()) return;
  const instances = (await api(`/api/stock/instances?item_id=${row.id}`)).instances.filter((i) => i.status === 'stock');
  const serialized = instances.length > 0;
  openModal('Выдача по заявке', `
    <div class="stock-name">${esc(row.name)}</div>
    <div class="stock-meta" style="margin-bottom:14px">заявка №${row.request_id} · на складе ${num(row.on_hand)} ${esc(row.qty_unit || '')}</div>
    ${serialized ? `
      <div class="form-row"><label>Какие экземпляры</label>
        <div class="pick-list">${instances.map((i) => `
          <label><input type="checkbox" class="check" value="${i.id}" checked>
            <span class="code-chip">${esc(i.code)}</span> <span class="muted">${esc(whereText(i.location_id, i.location_code))}</span></label>`).join('')}</div></div>`
    : `<div class="form-row"><label>Сколько</label>
        <input type="number" id="f-qty" class="qty-input" min="0" step="any" value="${num(row.on_hand)}"></div>`}
    <div class="form-row"><label>Кому выдали</label><select id="f-to">${employeeOptions(row.author_name)}</select></div>
    <div class="form-row"><label>Если нет в списке — впишите</label><input type="text" id="f-to-other" placeholder="ФИО"></div>
    <div class="form-row"><label>Примечание</label><input type="text" id="f-note"></div>
    <div class="row-actions">
      <button class="btn btn-primary btn-lg" id="f-ok">Выдать</button>
      <button class="btn btn-lg" id="f-close">Выдать и закрыть позицию</button>
    </div>`);
  const submit = async (close) => {
    const payload = {
      kind: 'out', item_id: row.id, close, note: el('f-note').value.trim(),
      ...actorPayload(), ...recipientFrom('f-to', 'f-to-other'),
    };
    if (serialized) {
      payload.instance_ids = [...el('modal-body').querySelectorAll('.check:checked')].map((c) => Number(c.value));
      payload.quantity = payload.instance_ids.length;
      if (!payload.quantity) { toast('Отметьте хотя бы один экземпляр'); return; }
    } else {
      payload.quantity = Number(el('f-qty').value || 0);
    }
    const result = await post('/api/stock/movement', payload);
    closeModal();
    toast(result.request_completed ? 'Выдано · заявка закрыта' : 'Выдано');
    await route();
  };
  el('f-ok').addEventListener('click', () => submit(false));
  el('f-close').addEventListener('click', () => submit(true));
}

/* ============================================================== сканер */

async function viewScan(root) {
  await loadLocations();
  root.innerHTML = `
    <div class="view-head"><h2>Сканер</h2></div>
    ${scannerHtml('main')}
    <div class="scan-result" id="scan-result"></div>

    <div class="view-head places-head">
      <h2>Места хранения</h2>
      <button class="btn" id="m-print" disabled>QR на выбранные</button>
      <button class="btn" id="m-add-box">+ Коробка</button>
      <button class="btn btn-primary" id="m-add-shelf">+ Полка</button>
    </div>
    <p class="view-hint">У каждой полки и коробки свой QR. Назначьте месту категорию — при раскладке оно будет предлагаться первым.</p>
    <div id="places"></div>`;
  bindScanner('main', (text) => showScanned(text));
  renderPlaces(el('places'));
  if (state.arg) showScanned(state.arg);
}

async function showScanned(text, scroll = false) {
  const box = el('scan-result');
  if (!box) return;
  box.innerHTML = '<p class="muted">Ищу…</p>';
  let found;
  try {
    found = await api(`/api/stock/resolve?code=${encodeURIComponent(text)}`);
  } catch (error) {
    box.innerHTML = `<p class="empty">Код «${esc(text)}» не найден.</p>`;
    return;
  }
  // адрес с кодом: после обновления страницы карточка откроется снова
  state.arg = found.code;
  history.replaceState(null, '', `#/scan/${encodeURIComponent(found.code)}`);
  if (found.type === 'shelf' || found.type === 'box' || found.type === 'zone') renderLocationCard(box, found.details);
  else if (found.type === 'instance') renderInstanceCard(box, found.details);
  else if (found.type === 'position') renderPositionCard(box, found.details);
  if (scroll) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function placeCounts(location) {
  if (!location) return '';
  return [
    location.products ? productsCount(location.products) : '',
    location.instances ? `${location.instances} шт. поштучно` : '',
  ].filter(Boolean).join(' · ') || 'пусто';
}

function renderLocationCard(box, details) {
  const loc = details.location;
  const kind = loc.kind === 'box' ? 'Коробка' : loc.kind === 'zone' ? 'Зона' : 'Полка';
  const purpose = loc.category_ids.map((id) => state.catPath[id]).filter(Boolean).join(', ');
  // назначение не задано — подсказываем по тому, что лежит на самом деле
  const actual = [...new Set([
    ...details.items.map((i) => i.path),
    ...details.instances.map((i) => state.catPath[i.category_id]).filter(Boolean),
  ])];
  const parent = loc.parent_id ? state.locations.find((l) => l.id === loc.parent_id) : null;
  const items = bulkItems(details);
  const empty = !items.length && !details.instances.length && !details.boxes.length;

  box.innerHTML = `
    <div class="scan-card">
      <div class="scan-top">
        <div>
          <div class="scan-kind">${kind} <span class="code-chip">${esc(loc.code)}</span>
            ${parent ? ` на полке <button class="link-btn" data-open="${esc(parent.code)}">${esc(parent.code)}</button>` : ''}</div>
          <h3>${esc(loc.name)}</h3>
        </div>
        ${loc.kind !== 'zone' ? `
          <div class="scan-tools">
            <a class="btn" href="${labelsUrl([loc.code])}" target="_blank" rel="noopener">QR</a>
            <button class="btn" id="s-edit">Изменить</button>
          </div>` : ''}
      </div>
      <div class="purpose">${purpose
        ? `Категория: <b>${esc(purpose)}</b>`
        : actual.length ? `По содержимому: ${esc(actual.join(', '))}` : 'Категория не задана'}</div>
      <div class="scan-contents">
        ${items.map((i) => `
          <div class="scan-line">
            <div class="scan-item">${esc(i.name)}<div class="small muted">${esc(i.path)}</div></div>
            <div class="scan-qty"><b>${num(i.quantity)}</b> ${esc(i.unit || '')}</div>
            <button class="btn" data-take="${i.product_id}">Выдать</button>
          </div>`).join('')}
        ${details.instances.map((i) => `
          <div class="scan-line">
            <div class="scan-item">${esc(i.product_name)} <span class="code-chip">${esc(i.code)}</span></div>
            <div class="scan-qty"><b>1</b> шт</div>
            <button class="btn" data-take-inst="${i.id}">Выдать</button>
          </div>`).join('')}
        ${details.boxes.map((b) => `
          <div class="scan-line">
            <div class="scan-item">Коробка «${esc(b.name)}» <span class="code-chip">${esc(b.code)}</span></div>
            <div class="scan-qty muted">${esc(placeCounts(state.locations.find((l) => l.id === b.id)))}</div>
            <button class="btn" data-open="${esc(b.code)}">Открыть</button>
          </div>`).join('')}
        ${empty ? '<p class="muted">Здесь пока ничего нет.</p>' : ''}
      </div>
      ${loc.kind !== 'zone' ? '<button class="btn btn-primary btn-lg btn-block" id="s-put" style="margin-top:14px">Положить сюда из приёмки</button>' : ''}
    </div>`;

  const put = el('s-put');
  if (put) put.addEventListener('click', () => putHereForm(loc));
  const edit = el('s-edit');
  if (edit) edit.addEventListener('click', () => locationForm(loc.kind, loc));
  box.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', () => showScanned(b.dataset.open)));
  box.querySelectorAll('[data-take]').forEach((b) => b.addEventListener('click', () => {
    const item = details.items.find((i) => String(i.product_id) === b.dataset.take);
    issueForm({
      product_id: item.product_id, name: item.name, unit: item.unit, total: item.quantity, serialized: false,
      places: [{ location_id: loc.id, code: loc.code, name: loc.name, quantity: item.quantity }],
    }, loc.id);
  }));
  box.querySelectorAll('[data-take-inst]').forEach((b) => b.addEventListener('click', () => {
    const inst = details.instances.find((i) => String(i.id) === b.dataset.takeInst);
    issueInstanceForm(inst);
  }));
}

/** «Скан полки → положить сюда»: выбираем, что из приёмки кладём на эту полку. */
async function putHereForm(location) {
  if (!requireActor()) return;
  const zone = await api('/api/stock/receiving');
  const bulk = bulkItems(zone);
  if (!bulk.length && !zone.instances.length) { toast('Зона приёмки пуста'); return; }
  openModal(`Положить на ${location.code}`, `
    <div class="form-row"><label>Что кладём</label>
      <select id="f-what">
        ${zone.instances.map((i) => `<option value="i:${i.id}">${esc(i.code)} · ${esc(i.product_name)}</option>`).join('')}
        ${bulk.map((i) => `<option value="p:${i.product_id}">${esc(i.name)} — в приёмке ${num(i.quantity)}</option>`).join('')}
      </select></div>
    <div class="form-row" id="f-qty-row"><label>Сколько</label>
      <input type="number" id="f-qty" class="qty-input" min="0" step="any" value="1"></div>
    <button class="btn btn-primary btn-lg btn-block" id="f-ok">Положить</button>`);
  const sync = () => {
    const [kind, id] = el('f-what').value.split(':');
    el('f-qty-row').hidden = kind === 'i';
    if (kind === 'p') el('f-qty').value = num(bulk.find((i) => String(i.product_id) === id).quantity);
  };
  el('f-what').addEventListener('change', sync);
  sync();
  el('f-ok').addEventListener('click', async () => {
    const [kind, id] = el('f-what').value.split(':');
    try {
      await post('/api/stock/place', {
        to_location_id: location.id,
        product_id: kind === 'p' ? Number(id) : null,
        instance_id: kind === 'i' ? Number(id) : null,
        quantity: kind === 'p' ? Number(el('f-qty').value || 0) : 1,
        ...actorPayload(),
      });
      closeModal();
      toast(`Положено на ${location.code}`);
      showScanned(location.code);
    } catch (error) {
      toast(explain(error));
    }
  });
}

function renderInstanceCard(box, inst) {
  box.innerHTML = `
    <div class="scan-card">
      <div class="scan-kind">Экземпляр <span class="code-chip">${esc(inst.code)}</span></div>
      <h3>${esc(inst.product_name)}</h3>
      <div class="purpose">${inst.status === 'issued'
        ? `Выдан${inst.issued_to ? `: ${esc(inst.issued_to)}` : ''}`
        : `Лежит: ${esc(whereText(inst.location_id, inst.location_code) || '—')}${inst.location_name ? ` · ${esc(inst.location_name)}` : ''}`}</div>
      ${inst.status === 'stock' ? `
        <div class="row-actions" style="margin-top:12px">
          <button class="btn btn-primary btn-lg" id="s-move">Переложить — скан полки</button>
          <button class="btn btn-lg" id="s-out">Выдать</button>
        </div>` : ''}
    </div>`;
  if (inst.status !== 'stock') return;
  // механика как на Озоне: отсканировали товар — теперь сканируем полку
  el('s-move').addEventListener('click', async () => {
    if (!requireActor()) return;
    const location = await pickLocationByScan();
    if (!location) return;
    try {
      await post('/api/stock/place', { instance_id: inst.id, to_location_id: location.id, ...actorPayload() });
      toast(`${inst.code} → ${location.code}`);
      showScanned(inst.code);
    } catch (error) {
      toast(explain(error));
    }
  });
  el('s-out').addEventListener('click', () => issueInstanceForm(inst));
}

function issueInstanceForm(inst) {
  if (!requireActor()) return;
  openModal('Выдача экземпляра', `
    <div class="stock-name">${esc(inst.product_name)} <span class="code-chip">${esc(inst.code)}</span></div>
    <div class="form-row" style="margin-top:14px"><label>Кому</label><select id="f-to">${employeeOptions('')}</select></div>
    <div class="form-row"><label>Если нет в списке — впишите</label><input type="text" id="f-to-other"></div>
    <div class="form-row"><label>Примечание</label><input type="text" id="f-note"></div>
    <button class="btn btn-primary btn-lg btn-block" id="f-ok">Выдать</button>`);
  el('f-ok').addEventListener('click', async () => {
    try {
      await post('/api/stock/issue', {
        instance_id: inst.id, note: el('f-note').value.trim(),
        ...actorPayload(), ...recipientFrom('f-to', 'f-to-other'),
      });
      closeModal();
      toast('Выдано');
      if (state.view === 'scan') showScanned(inst.code); else await route();
    } catch (error) {
      toast(explain(error));
    }
  });
}

function renderPositionCard(box, item) {
  box.innerHTML = `
    <div class="scan-card">
      <div class="scan-kind">Позиция заявки <span class="code-chip">${esc(item.stock_code)}</span></div>
      <h3>${esc(item.name)}</h3>
      <div class="purpose">заявка №${item.request_id} · заказано ${item.qty_number !== null ? num(item.qty_number) : '—'} ${esc(item.qty_unit || '')}
        · принято ${num(item.received)} · выдано ${num(item.issued)}</div>
      <div class="row-actions" style="margin-top:12px">
        ${!item.received_done ? '<button class="btn btn-primary btn-lg" id="s-in">Принять</button>' : ''}
        ${item.received_done && !item.issued_done ? '<a class="btn btn-primary btn-lg" href="#/vydacha">К выдаче</a>' : ''}
      </div>
    </div>`;
  const receiveBtn = el('s-in');
  if (receiveBtn) receiveBtn.addEventListener('click', () => receiveForm(item));
}

/* =============================================================== места */

/** Список полок с коробками под сканером. */
function renderPlaces(root) {
  const shelves = state.locations.filter((l) => l.kind === 'shelf');
  const boxes = state.locations.filter((l) => l.kind === 'box');
  const purpose = (l) => l.category_ids.map((id) => state.catPath[id]).filter(Boolean).join(', ');
  const row = (l, cls) => `
    <div class="${cls}">
      <input type="checkbox" class="check" data-sel="${l.id}" aria-label="Выбрать ${esc(l.code)}">
      <span class="code-chip">${esc(l.code)}</span>
      <span class="place-name">${esc(l.name)}
        <span class="small muted">${esc(placeCounts(l))}${purpose(l) ? ` · ${esc(purpose(l))}` : ''}</span></span>
      <button class="btn" data-open="${esc(l.code)}">Открыть</button>
    </div>`;

  root.innerHTML = `
    <div class="stock-list">
      ${shelves.map((s) => `
        <div class="shelf-card">
          ${row(s, 'shelf-head')}
          ${boxes.some((b) => b.parent_id === s.id) ? `
            <div class="shelf-boxes">${boxes.filter((b) => b.parent_id === s.id).map((b) => row(b, 'box-row')).join('')}</div>` : ''}
        </div>`).join('')}
      ${boxes.some((b) => !b.parent_id) ? `
        <div class="shelf-card">
          <div class="small muted" style="margin-bottom:6px">Коробки не на полке</div>
          ${boxes.filter((b) => !b.parent_id).map((b) => row(b, 'box-row')).join('')}
        </div>` : ''}
    </div>
    ${shelves.length || boxes.length ? '' : '<p class="empty">Мест пока нет. Начните с полок: «+ Полка».</p>'}`;

  const selected = () => [...root.querySelectorAll('[data-sel]:checked')].map((c) => c.dataset.sel);
  root.querySelectorAll('[data-sel]').forEach((c) => c.addEventListener('change', () => {
    el('m-print').disabled = !selected().length;
  }));
  el('m-print').addEventListener('click', () => {
    window.open(`/labels?locations=${selected().join(',')}`, '_blank', 'noopener');
  });
  el('m-add-shelf').addEventListener('click', () => locationForm('shelf'));
  el('m-add-box').addEventListener('click', () => locationForm('box'));
  root.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', () => showScanned(b.dataset.open, true)));
}

function locationForm(kind, existing = null) {
  const shelves = state.locations.filter((l) => l.kind === 'shelf');
  const chosen = existing ? existing.category_ids : [];
  openModal(existing ? `Изменить ${existing.code}` : (kind === 'shelf' ? 'Новая полка' : 'Новая коробка'), `
    <div class="form-row"><label>Название</label>
      <input type="text" id="f-name" value="${esc(existing ? existing.name : '')}"
        placeholder="${kind === 'shelf' ? 'например: Стеллаж 2, полка 3' : 'например: Салфетки для обработки'}"></div>
    ${kind === 'box' ? `<div class="form-row"><label>На какой полке стоит</label>
      <select id="f-parent"><option value="">— не на полке —</option>
        ${shelves.map((s) => `<option value="${s.id}" ${existing && existing.parent_id === s.id ? 'selected' : ''}>${esc(s.code)} · ${esc(s.name)}</option>`).join('')}
      </select></div>` : ''}
    <div class="form-row"><label>Что здесь хранится (можно несколько — Ctrl/Cmd + клик)</label>
      <select id="f-cats" multiple>
        ${state.categories.map((top) => `
          <optgroup label="${esc(top.name)}">
            <option value="${top.id}" ${chosen.includes(top.id) ? 'selected' : ''}>${esc(top.name)} — весь раздел</option>
            ${top.children.map((c) => `<option value="${c.id}" ${chosen.includes(c.id) ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
          </optgroup>`).join('')}
      </select></div>
    <button class="btn btn-primary btn-lg btn-block" id="f-ok">${existing ? 'Сохранить' : 'Создать'}</button>`);

  el('f-ok').addEventListener('click', async () => {
    const name = el('f-name').value.trim();
    if (!name) { toast('Введите название'); return; }
    const payload = {
      kind,
      name,
      category_ids: [...el('f-cats').selectedOptions].map((o) => Number(o.value)),
    };
    if (kind === 'box') payload.parent_id = el('f-parent').value ? Number(el('f-parent').value) : null;
    const result = existing
      ? await post(`/api/stock/locations/${existing.id}`, payload)
      : await post('/api/stock/locations', payload);
    closeModal();
    toast(existing ? 'Сохранено' : `Создано: ${result.location.code} — напечатайте для него QR`);
    await loadLocations();
    if (state.view === 'scan') {
      renderPlaces(el('places'));
      showScanned(result.location.code, !existing);
    } else {
      await route();
    }
  });
}

/* ============================================================== товары */

async function viewProducts(root) {
  const products = (await api('/api/stock/products')).products;
  const isAdmin = state.role === 'admin';
  root.innerHTML = `
    <div class="view-head"><h2>Товары и категории</h2></div>
    <div class="search-row"><input type="search" id="p-search" placeholder="Поиск по названию"></div>
    <table class="products-table">
      <thead><tr><th>Товар</th><th>Категория</th><th>Учёт</th><th>Мин. остаток</th></tr></thead>
      <tbody id="p-rows"></tbody>
    </table>
    ${products.length ? '' : '<p class="empty">Товаров пока нет — они появятся после первой приёмки.</p>'}
    ${isAdmin ? `
      <div class="group-title" style="margin-top:28px">Словарь автоматической разбивки</div>
      <p class="view-hint">Слова через запятую. <code>перчат</code> — начало слова, <code>=чай</code> — слово целиком,
        <code>перчат+нитрил</code> — нужны оба. Изменения сразу применяются к товарам без категории.</p>
      <div id="kw-list"></div>` : ''}`;

  const draw = (query) => {
    const q = query.trim().toLowerCase();
    el('p-rows').innerHTML = products.filter((p) => !q || p.name.toLowerCase().includes(q)).map((p) => `
      <tr>
        <td>${esc(p.name)}</td>
        <td><select data-cat="${p.id}">${categoryOptions(p.category_id)}</select>
          ${p.category_manual ? '' : '<div class="auto-tag">определена автоматически</div>'}</td>
        <td><select data-ser="${p.id}">
          <option value="" ${p.serialized_override === null ? 'selected' : ''}>как у категории (${p.serialized ? 'поштучно' : 'количеством'})</option>
          <option value="1" ${p.serialized_override === true ? 'selected' : ''}>поштучно</option>
          <option value="0" ${p.serialized_override === false ? 'selected' : ''}>количеством</option>
        </select></td>
        <td><input type="number" class="num" min="0" step="any" data-min="${p.id}" value="${p.min_stock ?? ''}"></td>
      </tr>`).join('');
    el('p-rows').querySelectorAll('[data-cat]').forEach((s) => s.addEventListener('change', async () => {
      await post(`/api/stock/products/${s.dataset.cat}`, { category_id: s.value ? Number(s.value) : null });
      toast('Категория сохранена — запомнил за товаром');
    }));
    el('p-rows').querySelectorAll('[data-ser]').forEach((s) => s.addEventListener('change', async () => {
      await post(`/api/stock/products/${s.dataset.ser}`, { serialized: s.value === '' ? null : s.value === '1' });
      toast('Способ учёта сохранён');
    }));
    el('p-rows').querySelectorAll('[data-min]').forEach((i) => i.addEventListener('change', async () => {
      await post(`/api/stock/products/${i.dataset.min}`, { min_stock: i.value === '' ? null : Number(i.value) });
      toast('Минимальный остаток сохранён');
    }));
  };
  draw('');
  el('p-search').addEventListener('input', (event) => draw(event.target.value));

  if (isAdmin) {
    el('kw-list').innerHTML = state.categories.map((top) => top.children.map((c) => `
      <div class="kw-row">
        <div><b>${esc(top.name)}</b><br><span class="muted">${esc(c.name)}</span></div>
        <textarea data-kw="${c.id}">${esc(c.keywords || '')}</textarea>
        <button class="btn" data-kw-save="${c.id}">Сохранить</button>
      </div>`).join('')).join('');
    el('kw-list').querySelectorAll('[data-kw-save]').forEach((b) => b.addEventListener('click', async () => {
      const id = b.dataset.kwSave;
      await post(`/api/stock/categories/${id}/keywords`, {
        keywords: el('kw-list').querySelector(`[data-kw="${id}"]`).value,
      });
      await loadCategories();
      toast('Словарь обновлён');
    }));
  }
}

/* ============================================================= история */

async function viewHistory(root) {
  const data = await api('/api/stock/history?limit=150');
  const label = { in: 'Принято', out: 'Выдано', move: 'Перемещено', adjust: 'Инвентаризация' };
  root.innerHTML = `
    <div class="view-head"><h2>История</h2></div>
    <div class="hist">${data.movements.map((m) => `
      <div class="hist-row">
        <span class="hist-kind ${esc(m.kind)}">${label[m.kind] || m.kind} ${num(m.quantity)}</span>
        <span>${esc(m.item_name || '')}${m.instance_code ? ` <span class="code-chip">${esc(m.instance_code)}</span>` : ''}</span>
        <span class="muted">${m.from_code ? esc(m.from_code) : ''}${m.from_code && m.to_code ? ' → ' : ''}${m.to_code ? esc(m.to_code) : ''}</span>
        <span class="muted">${esc(m.actor_name)}${m.recipient_name ? ` → ${esc(m.recipient_name)}` : ''}</span>
        <span class="hist-when">${esc(m.created_at)}</span>
      </div>`).join('')}</div>
    ${data.movements.length ? '' : '<p class="empty">Движений пока не было.</p>'}`;
}

/* =============================================================== старт */

async function start(user, role) {
  state.user = user;
  state.role = role;
  el('login-screen').hidden = true;
  el('app').hidden = false;
  el('user-chip').textContent = user;
  await Promise.all([loadEmployees(), loadCategories(), loadLocations()]);
  await route();
}

(async () => {
  const meta = await fetch('/api/meta').then((r) => r.json()).catch(() => null);
  if (!meta || !meta.user) { showLogin(); return; }
  await start(meta.user, meta.role);
})();

setInterval(() => {
  const busy = !el('overlay').hidden || !el('scan-overlay').hidden || Scanner.stream || state.view === 'scan';
  if (!el('app').hidden && !busy) refreshCounts().catch(() => {});
}, 30000);
