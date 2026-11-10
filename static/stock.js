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
  if (data.error === 'bad_category') return 'Полке назначают раздел, коробке и месту на полке — подраздел';
  if (data.error === 'bad_parent') return 'Место на полке должно стоять на полке';
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

const KIND_TITLES = { shelf: 'Полка', box: 'Коробка', lot: 'Место на полке', zone: 'Зона' };
const ON_SHELF = ['box', 'lot'];

/** Насколько место подходит товару: 2 — коробка или место его подраздела, 1 — полка его раздела, 0 — нет.

Полка целиком под раздел (Медицина), коробки и места на ней — под подразделы (Медицина → Расходники). */
function locationFit(location, categoryId) {
  if (!categoryId) return 0;
  const top = state.catParent[categoryId] || categoryId;
  if (ON_SHELF.includes(location.kind)) {
    if (location.category_ids.includes(categoryId)) return 2;
    if (location.category_ids.length) return 0;
    // своего подраздела нет — смотрим на раздел полки, где стоит
    const shelf = state.locations.find((l) => l.id === location.parent_id);
    return shelf && shelf.category_ids.includes(top) ? 1 : 0;
  }
  return location.kind === 'shelf' && location.category_ids.includes(top) ? 1 : 0;
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
  return `${whereText(location.id, location.code)} · ${location.name} (${KIND_TITLES[location.kind].toLowerCase()})`;
}

function locationOptions(categoryId, excludeId) {
  const usable = state.locations.filter((l) => l.kind !== 'zone' && l.id !== excludeId);
  const exact = usable.filter((l) => locationFit(l, categoryId) === 2);
  const section = usable.filter((l) => locationFit(l, categoryId) === 1);
  const rest = usable.filter((l) => locationFit(l, categoryId) === 0);
  const opt = (l) => `<option value="${l.id}">${esc(locationLabel(l))}</option>`;
  const group = (label, rows) => (rows.length ? `<optgroup label="${label}">${rows.map(opt).join('')}</optgroup>` : '');
  return group('Коробки и места этого подраздела', exact)
    + group('Полки этого раздела', section)
    + group(exact.length || section.length ? 'Остальные места' : 'Места', rest);
}

/** Список «кому выдать»: сотрудники по отделениям. */
function employeeOptions(selectedName) {
  const groups = {};
  for (const employee of state.employees) {
    (groups[employee.department || 'Без отделения'] ||= []).push(employee);
  }
  const names = Object.keys(groups).sort((a, b) =>
    (a === 'Без отделения') - (b === 'Без отделения') || a.localeCompare(b, 'ru'));
  const option = (e) => `<option value="${e.id}" ${e.full_name === selectedName ? 'selected' : ''}>${esc(e.full_name)}</option>`;
  return '<option value="">— выберите сотрудника —</option>' + (names.length > 1
    ? names.map((name) => `<optgroup label="${esc(name)}">${groups[name].map(option).join('')}</optgroup>`).join('')
    : state.employees.map(option).join(''));
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
  else if (!el('drawer').hidden) closeDrawer();
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
        if (!['shelf', 'box', 'lot'].includes(found.type)) { toast('Это не полка, не коробка и не место'); return; }
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

const WAREHOUSES = [
  { slug: 'snab', name: 'Склад снабжения', ready: true },
  { slug: 'mebel', name: 'Мебельный склад', ready: false },
  { slug: 'kanc', name: 'Склад канцелярии', ready: false },
];

const VIEWS = {
  home: { title: 'Склад снабжения', render: viewWarehouseHome, hidden: true },
  w: { title: 'Склад', render: viewWarehouseSoon, hidden: true },
  priemka: { title: 'Приёмка', render: viewReceiving },
  hranenie: { title: 'Хранение', render: viewStorage },
  vydacha: { title: 'Выдача', render: viewIssue },
  scan: { title: 'Сканер', render: viewScan },
  dashboard: { title: 'Дашборд', render: viewDashboard, admin: true },
  tovary: { title: 'Товары', render: viewProducts },
};
// старые адреса из закладок ведут в новые разделы
const ALIASES = { razmeshchenie: 'priemka', mesta: 'scan', qr: 'scan', istoriya: 'dashboard' };

const canSee = (key) => !VIEWS[key].admin || state.role === 'admin';

function renderNav() {
  const inSnab = state.view !== 'w';
  el('stock-nav').hidden = !inSnab;
  el('stock-nav').innerHTML = Object.entries(VIEWS)
    .filter(([key, view]) => !view.hidden && canSee(key))
    .map(([key, view]) =>
      `<a href="#/${key}" class="${key === state.view ? 'active' : ''}" data-view="${key}">${esc(view.title)}<span class="count" id="nav-count-${key}"></span></a>`
    ).join('');
  // на телефоне вкладки прокручиваются — держим текущую в поле зрения
  const active = el('stock-nav').querySelector('.active');
  if (active) active.scrollIntoView({ inline: 'center', block: 'nearest' });

  // название склада в шапке — ссылка ко всем его разделам; сменить склад можно на главной портала
  const current = WAREHOUSES.find((w) => w.slug === (state.view === 'w' ? state.arg : 'snab')) || WAREHOUSES[0];
  const link = el('warehouse');
  link.textContent = current.name;
  link.href = current.ready ? '#/home' : `#/w/${current.slug}`;
  link.classList.toggle('active', state.view === 'home' || state.view === 'w');
}

async function route() {
  Scanner.stop();
  closeModal();
  closeDrawer();
  const [, raw = '', ...rest] = (location.hash || '#/home').split('/');
  let view = ALIASES[raw] || raw || 'home';
  if (!VIEWS[view] || !canSee(view)) view = 'home';
  state.view = view;
  state.arg = rest.length ? decodeURIComponent(rest.join('/')) : null;
  renderNav();
  const warehouse = WAREHOUSES.find((w) => w.slug === state.arg);
  document.title = view === 'w' ? (warehouse ? warehouse.name : 'Склад')
    : view === 'home' ? 'Склад снабжения' : `${VIEWS[view].title} — склад снабжения`;
  el('view').innerHTML = '<p class="muted">Загружаю…</p>';
  try {
    await VIEWS[view].render(el('view'));
  } catch (error) {
    if (error.message !== 'unauthorized') {
      el('view').innerHTML = '<p class="empty">Не удалось загрузить. Обновите страницу.</p>';
    }
  }
  if (view !== 'w') refreshCounts().catch(() => {});
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

/* ======================================================= главная склада */

const TILE_ICONS = {
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7l10-5z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
  out: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>',
  scan: '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M7 12h10"/>',
  chart: '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>',
  tag: '<path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><path d="M7 7h.01"/>',
  tools: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4 2.5-2.5z"/>',
};
const tileIcon = (name) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${TILE_ICONS[name]}</svg>`;

async function viewWarehouseHome(root) {
  const tiles = [
    { key: 'priemka', icon: 'inbox', title: 'Приёмка и размещение', text: 'Отметить, что привезли, разложить по полкам, напечатать QR' },
    { key: 'hranenie', icon: 'layers', title: 'Хранение', text: 'Остатки по категориям и подкатегориям' },
    { key: 'vydacha', icon: 'out', title: 'Выдача по заявкам', text: 'Отдать заказчику то, что он заказывал' },
    { key: 'scan', icon: 'scan', title: 'Сканер и места', text: 'Что лежит в коробке или на полке, полки и коробки' },
    { key: 'dashboard', icon: 'chart', title: 'Дашборд', text: 'Остатки, приход и выдача, кто что забирал, история' },
    { key: 'tovary', icon: 'tag', title: 'Товары и категории', text: 'Справочник и распределение по категориям' },
  ].filter((tile) => canSee(tile.key));
  root.innerHTML = `
    <div class="view-head"><h2>Склад снабжения</h2></div>
    <p class="view-hint">Сюда приходят заказы из заявок и всё, что приносят на склад лично.</p>
    <div class="tiles">${tiles.map((tile) => `
      <a class="tile" href="#/${tile.key}">
        <span class="tile-icon">${tileIcon(tile.icon)}</span>
        <span>
          <div class="tile-title">${esc(tile.title)}</div>
          <div class="tile-text">${esc(tile.text)}</div>
        </span>
      </a>`).join('')}
    </div>`;
}

async function viewWarehouseSoon(root) {
  const warehouse = WAREHOUSES.find((w) => w.slug === state.arg) || { name: 'Склад' };
  root.innerHTML = `
    <div class="soon-card">
      <span class="tile-icon">${tileIcon('tools')}</span>
      <h2>${esc(warehouse.name)}</h2>
      <p>Раздел в разработке. У этого склада будет своя логика учёта — подключим его следующим этапом.</p>
      <a class="btn btn-primary btn-lg" href="#/home">Перейти на склад снабжения</a>
    </div>`;
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
      ${mode === 'in' ? `<input type="checkbox" class="check pick" data-pick="${row.id}" aria-label="Выбрать">` : ''}
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
    <div class="view-head"><h2>Приёмка и размещение</h2>
      <button class="btn btn-primary" id="r-manual">+ Принять без заявки</button></div>
    <p class="view-hint">Отметьте, что привезли, и сразу положите на полку или в коробку.
      Что не успели разложить — ждёт ниже, в «Лежит в приёмке».</p>
    ${hasPlaces() ? '' : `<p class="view-hint">Полок пока нет — заведите их в разделе <a href="#/scan">«Сканер»</a>,
      тогда принятое можно будет сразу раскладывать.</p>`}

    <div class="group-title group-row">Ждём поставку${data.items.length ? ` · ${data.items.length}` : ''}
      ${data.items.length > 1 ? '<label class="pick-all"><input type="checkbox" class="check" id="r-all"> выбрать все</label>' : ''}</div>
    <div class="bulk-bar" id="r-bar" hidden>
      <span>Выбрано: <b id="r-count">0</b></span>
      <button class="btn btn-primary" id="r-receive">Принять выбранные</button>
    </div>
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
    receive(row, leftToReceive(row), true);
  }));
  el('r-manual').addEventListener('click', manualReceiveForm);

  // несколько позиций разом: приняли — и одним листом наклейки
  const picked = () => [...root.querySelectorAll('[data-pick]:checked')].map((c) => rows[c.dataset.pick]);
  const syncBar = () => {
    const count = picked().length;
    el('r-bar').hidden = count === 0;
    el('r-count').textContent = count;
  };
  root.querySelectorAll('[data-pick]').forEach((c) => c.addEventListener('change', syncBar));
  const all = el('r-all');
  if (all) all.addEventListener('change', () => {
    root.querySelectorAll('[data-pick]').forEach((c) => { c.checked = all.checked; });
    syncBar();
  });
  el('r-receive').addEventListener('click', () => receiveManyForm(picked()));
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

const leftToReceive = (row) => (row.qty_number !== null ? Math.max(row.qty_number - row.received, 0) : 1);

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
  const item = bulkItems(zone).find((i) => i.product_id === (result.item && result.item.product_id));
  const code = result.item && result.item.stock_code;
  if (item && hasPlaces()) {
    placeForm(item, null, null, 'Принято — куда положить?', code ? [code] : []);
  } else if (code) {
    openModal('Принято', `
      <p class="muted" style="margin:0 0 14px">Товар лежит в зоне приёмки.</p>
      <a class="btn btn-primary btn-lg btn-block" href="${labelsUrl([code])}" target="_blank" rel="noopener">Напечатать наклейку</a>`);
  }
}

/** Несколько позиций: по каждой своё количество, 0 — пропустить. */
function receiveManyForm(rows) {
  if (!rows.length || !requireActor()) return;
  openModal(`Приёмка: ${rows.length} ${plural(rows.length, 'позиция', 'позиции', 'позиций')}`, `
    <p class="muted small" style="margin:0 0 12px">Сколько привезли по каждой позиции. Не всё — укажите сколько есть,
      остальное будет ждать. 0 — пропустить позицию.</p>
    <div class="multi-list">${rows.map((row) => `
      <div class="multi-row">
        <div class="multi-main">
          <div class="multi-name">${esc(row.name)}</div>
          <div class="stock-meta">${esc(row.stock_code || '')} · заказано ${row.qty_number !== null ? num(row.qty_number) : '—'}
            ${esc(row.qty_unit || '')}${row.received ? ` · уже принято ${num(row.received)}` : ''}</div>
        </div>
        <label class="multi-qty">
          <input type="number" class="qty-input" data-qty="${row.id}" min="0" step="any" value="${num(leftToReceive(row))}">
          <span class="muted small">${esc(row.qty_unit || 'шт')}</span>
        </label>
      </div>`).join('')}
    </div>
    <button class="btn btn-primary btn-lg btn-block" id="f-ok" style="margin-top:14px">Принять</button>`);
  el('f-ok').addEventListener('click', () => {
    const entries = rows.map((row) => {
      const quantity = Number(el('modal-body').querySelector(`[data-qty="${row.id}"]`).value || 0);
      // если количество в заявке неизвестно — принятое закрывает позицию
      return { row, quantity, close: row.qty_number === null };
    }).filter((entry) => entry.quantity > 0);
    if (!entries.length) { toast('Укажите количество хотя бы по одной позиции'); return; }
    receiveMany(entries);
  });
}

/** Приёмка нескольких позиций с количеством по каждой. */
async function receiveMany(entries) {
  if (!entries.length || !requireActor()) return;
  const results = [];
  for (const { row, quantity, close } of entries) {
    try {
      const result = await post('/api/stock/movement', {
        kind: 'in', item_id: row.id, quantity, close, ...actorPayload(),
      });
      results.push({ row, quantity, result });
    } catch (error) { /* покажем итог ниже */ }
  }
  const notified = results.filter((r) => r.result.author_notified).length;
  const arrived = results.filter((r) => r.result.request_arrived).length;
  const extra = notified ? ` · заказчикам отправлено сообщений: ${notified}` : arrived ? ' · заявки собраны' : '';
  toast(`Принято позиций: ${results.length} из ${entries.length}${extra}`);
  await route();
  if (results.length) await afterReceiveMany(results);
}

async function afterReceiveMany(results) {
  const zone = await api('/api/stock/receiving');
  const codes = [
    ...results.map((r) => r.row.stock_code).filter(Boolean),
    ...results.flatMap((r) => r.result.instances_created || []),
  ];
  const productIds = new Set(results.map((r) => r.result.item && r.result.item.product_id));
  const bulk = bulkItems(zone).filter((i) => productIds.has(i.product_id));
  const instances = zone.instances.filter((i) => codes.includes(i.code));
  const received = {};
  for (const r of results) {
    const id = r.result.item && r.result.item.product_id;
    received[id] = (received[id] || 0) + r.quantity;
  }
  const categoryId = (bulk[0] || instances[0] || {}).category_id;

  openModal(`Принято позиций: ${results.length}`, `
    <div class="pick-list" style="margin-bottom:14px">
      ${results.map((r) => `<div class="pick-line">${esc(r.row.name)} <span class="code-chip">${esc(r.row.stock_code || '')}</span>
        <b style="float:right">${num(r.quantity)} ${esc(r.row.qty_unit || '')}</b></div>`).join('')}
    </div>
    <a class="btn btn-primary btn-lg btn-block" href="${labelsUrl(codes)}" target="_blank" rel="noopener" style="margin-bottom:16px">Напечатать все наклейки одним листом (${codes.length})</a>
    ${hasPlaces() && (bulk.length || instances.length) ? `
      <div class="form-row"><label>Положить всё в одно место (необязательно)</label>
        <select id="f-loc">${locationOptions(categoryId)}</select></div>
      <div class="row-actions">
        <button class="btn btn-lg" id="f-scan">Сканировать полку</button>
        <button class="btn btn-primary btn-lg" id="f-ok">Положить всё</button>
      </div>
      <button class="btn btn-quiet btn-block" id="f-later">Разложу потом</button>` : ''}`);
  if (!el('f-ok')) return;
  el('f-later').addEventListener('click', closeModal);
  el('f-scan').addEventListener('click', async () => {
    const location = await pickLocationByScan();
    if (location) { el('f-loc').value = location.id; toast(`Выбрано: ${location.code}`); }
  });
  el('f-ok').addEventListener('click', async () => {
    const target = Number(el('f-loc').value);
    if (!target) { toast('Выберите место'); return; }
    let placed = 0;
    let failed = 0;
    for (const item of bulk) {
      try {
        // кладём столько, сколько сейчас приняли, но не больше, чем лежит в приёмке
        const quantity = Math.min(item.quantity, received[item.product_id] || item.quantity);
        await post('/api/stock/place', { product_id: item.product_id, quantity, to_location_id: target, ...actorPayload() });
        placed += 1;
      } catch (error) { failed += 1; }
    }
    for (const instance of instances) {
      try {
        await post('/api/stock/place', { instance_id: instance.id, to_location_id: target, ...actorPayload() });
        placed += 1;
      } catch (error) { failed += 1; }
    }
    toast(failed ? `Положено ${placed}, не получилось ${failed}` : 'Всё разложено');
    await route();
  });
}

/** Приём без заявки: товар принесли или передали лично. */
async function manualReceiveForm() {
  if (!requireActor()) return;
  const products = (await api('/api/stock/products')).products;
  const byName = Object.fromEntries(products.map((p) => [p.name.toLowerCase(), p]));
  openModal('Принять без заявки', `
    <div class="form-row"><label>Что принимаем</label>
      <input type="text" id="m-name" list="m-products" placeholder="Название товара" autocomplete="off">
      <datalist id="m-products">${products.map((p) => `<option value="${esc(p.name)}">`).join('')}</datalist></div>
    <div class="inline-row">
      <div class="form-row"><label>Количество</label>
        <input type="number" id="m-qty" class="qty-input" min="0" step="any" value="1"></div>
      <div class="form-row"><label>Единица</label>
        <input type="text" id="m-unit" list="m-units" placeholder="шт">
        <datalist id="m-units">${['шт', 'уп', 'пачка', 'пара', 'рулон', 'кг', 'л', 'компл'].map((u) => `<option value="${u}">`).join('')}</datalist></div>
    </div>
    <div class="form-row"><label>Категория</label>
      <select id="m-cat">${categoryOptions(null)}</select>
      <div class="auto-tag" id="m-cat-hint"></div></div>
    <div class="form-row"><label>От кого или откуда</label>
      <input type="text" id="m-note" placeholder="например: передал Иванов, благотворительная помощь"></div>
    <button class="btn btn-primary btn-lg btn-block" id="m-ok">Принять</button>`);

  let touched = false;
  el('m-cat').addEventListener('change', () => { touched = true; el('m-cat-hint').textContent = ''; });
  let timer = null;
  el('m-name').addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const name = el('m-name').value.trim();
      if (!name) return;
      const known = byName[name.toLowerCase()];
      if (known && known.unit && !el('m-unit').value) el('m-unit').value = known.unit;
      if (touched) return;
      const { category_id: suggested } = await api(`/api/stock/classify?name=${encodeURIComponent(name)}`);
      el('m-cat').value = suggested || '';
      el('m-cat-hint').textContent = suggested ? (known ? 'категория этого товара' : 'определена по названию — можно поменять') : '';
    }, 350);
  });
  el('m-ok').addEventListener('click', async () => {
    const name = el('m-name').value.trim();
    const quantity = Number(el('m-qty').value || 0);
    if (!name) { toast('Введите название'); return; }
    if (quantity <= 0) { toast('Укажите количество'); return; }
    try {
      const result = await post('/api/stock/receive-manual', {
        name, quantity, unit: el('m-unit').value.trim(),
        category_id: el('m-cat').value ? Number(el('m-cat').value) : null,
        note: el('m-note').value.trim(), ...actorPayload(),
      });
      toast('Принято без заявки');
      await route();
      await afterReceive(result);
    } catch (error) {
      toast(explain(error));
    }
  });
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
function placeForm(item, instance = null, fromLocationId = null, title = null, labelCodes = []) {
  if (!requireActor()) return;
  if (!hasPlaces()) { toast('Сначала заведите полки в разделе «Сканер»'); return; }
  const categoryId = item ? item.category_id : instance.category_id;
  openModal(title || (instance ? 'Разместить экземпляр' : 'Разместить'), `
    <div class="stock-name">${esc(item ? item.name : instance.product_name)}
      ${instance ? `<span class="code-chip">${esc(instance.code)}</span>` : ''}</div>
    <div class="stock-meta" style="margin-bottom:14px">${esc(state.catPath[categoryId] || 'без категории')}</div>
    ${labelCodes.length ? `<a class="btn btn-lg btn-block" href="${labelsUrl(labelCodes)}" target="_blank" rel="noopener" style="margin-bottom:14px">Напечатать наклейку</a>` : ''}
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
    <div class="form-row"><label>Или впишите вручную</label><input type="text" id="f-to-other" placeholder="ФИО или отделение"></div>
    <div class="form-row"><label>Примечание</label><input type="text" id="f-note"></div>
    <button class="btn btn-primary btn-lg btn-block" id="f-ok">Выдать</button>`);

  el('f-ok').addEventListener('click', async () => {
    const payload = { ...actorPayload(), ...recipientFrom('f-to', 'f-to-other'), note: el('f-note').value.trim() };
    if (!payload.recipient_name) { toast('Укажите, кому выдаёте'); return; }
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
    <div class="form-row"><label>Или впишите вручную</label><input type="text" id="f-to-other" placeholder="ФИО"></div>
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
    if (!payload.recipient_name) { toast('Укажите, кому выдаёте'); return; }
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
      <button class="btn" id="m-add-lot">+ Место на полке</button>
      <button class="btn btn-primary" id="m-add-shelf">+ Полка</button>
    </div>
    <p class="view-hint">Полка — целиком под раздел (Медицина). На ней коробки для мелочи и места для товара без коробки —
      каждое под свой подраздел (Медицина → Расходники) и со своим QR. При раскладке они предлагаются первыми.</p>
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
  if (['shelf', 'box', 'lot', 'zone'].includes(found.type)) renderLocationCard(box, found.details);
  else if (found.type === 'instance') renderInstanceCard(box, found.details);
  else if (found.type === 'position') renderPositionCard(box, found.details);
  if (scroll) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/** Назначение места по общему списку: «Медицина» у полки, «Медицина → Расходники» у коробки. */
function purposeOf(locationId) {
  const location = state.locations.find((l) => l.id === locationId);
  return location ? location.category_ids.map((id) => state.catPath[id]).filter(Boolean).join(', ') : '';
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
  const kind = KIND_TITLES[loc.kind] || 'Место';
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
            <button class="btn btn-danger" id="s-delete">Удалить</button>
          </div>` : ''}
      </div>
      <div class="purpose">${purpose
        ? `${loc.kind === 'shelf' ? 'Раздел' : 'Подраздел'}: <b>${esc(purpose)}</b>`
        : actual.length ? `По содержимому: ${esc(actual.join(', '))}`
        : loc.kind === 'shelf' ? 'Раздел не задан' : 'Подраздел не задан'}</div>
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
            <div class="scan-item">${b.kind === 'lot' ? 'Место' : 'Коробка'} «${esc(b.name)}» <span class="code-chip">${esc(b.code)}</span>
              ${purposeOf(b.id) ? `<div class="small muted">${esc(purposeOf(b.id))}</div>` : ''}</div>
            <div class="scan-qty muted">${esc(placeCounts(state.locations.find((l) => l.id === b.id)))}</div>
            <button class="btn" data-open="${esc(b.code)}">Открыть</button>
          </div>`).join('')}
        ${empty ? '<p class="muted">Здесь пока ничего нет.</p>' : ''}
      </div>
      ${loc.kind === 'shelf' ? `
        <div class="row-actions" style="margin-top:12px">
          <button class="btn" id="s-add-box">+ Коробка на эту полку</button>
          <button class="btn" id="s-add-lot">+ Место на этой полке</button>
        </div>` : ''}
      ${loc.kind !== 'zone' ? '<button class="btn btn-primary btn-lg btn-block" id="s-put" style="margin-top:14px">Положить сюда из приёмки</button>' : ''}
    </div>`;

  const put = el('s-put');
  if (put) put.addEventListener('click', () => putHereForm(loc));
  const edit = el('s-edit');
  if (edit) edit.addEventListener('click', () => locationForm(loc.kind, loc));
  if (el('s-delete')) el('s-delete').addEventListener('click', () => deleteLocationForm(loc));
  if (el('s-add-box')) el('s-add-box').addEventListener('click', () => locationForm('box', null, loc.id));
  if (el('s-add-lot')) el('s-add-lot').addEventListener('click', () => locationForm('lot', null, loc.id));
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
    <div class="form-row"><label>Или впишите вручную</label><input type="text" id="f-to-other"></div>
    <div class="form-row"><label>Примечание</label><input type="text" id="f-note"></div>
    <button class="btn btn-primary btn-lg btn-block" id="f-ok">Выдать</button>`);
  el('f-ok').addEventListener('click', async () => {
    try {
      const recipient = recipientFrom('f-to', 'f-to-other');
      if (!recipient.recipient_name) { toast('Укажите, кому выдаёте'); return; }
      await post('/api/stock/issue', {
        instance_id: inst.id, note: el('f-note').value.trim(), ...actorPayload(), ...recipient,
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

/** Список полок с их коробками и местами — под сканером. */
function renderPlaces(root) {
  const shelves = state.locations.filter((l) => l.kind === 'shelf');
  const children = state.locations.filter((l) => ON_SHELF.includes(l.kind));
  const row = (l, cls) => `
    <div class="${cls}">
      <input type="checkbox" class="check" data-sel="${l.id}" aria-label="Выбрать ${esc(l.code)}">
      <span class="code-chip">${esc(l.code)}</span>
      <span class="place-name">${l.kind === 'lot' ? '<span class="kind-tag">место</span>' : ''}${esc(l.name)}
        <span class="small muted">${esc(placeCounts(l))}${purposeOf(l.id) ? ` · ${esc(purposeOf(l.id))}` : ''}</span></span>
      <button class="btn" data-open="${esc(l.code)}">Открыть</button>
    </div>`;

  root.innerHTML = `
    <div class="stock-list">
      ${shelves.map((s) => `
        <div class="shelf-card">
          ${row(s, 'shelf-head')}
          ${children.some((c) => c.parent_id === s.id) ? `
            <div class="shelf-boxes">${children.filter((c) => c.parent_id === s.id).map((c) => row(c, 'box-row')).join('')}</div>` : ''}
        </div>`).join('')}
      ${children.some((c) => !c.parent_id) ? `
        <div class="shelf-card">
          <div class="small muted" style="margin-bottom:6px">Коробки не на полке</div>
          ${children.filter((c) => !c.parent_id).map((c) => row(c, 'box-row')).join('')}
        </div>` : ''}
    </div>
    ${shelves.length || children.length ? '' : '<p class="empty">Мест пока нет. Начните с полок: «+ Полка».</p>'}`;

  const selected = () => [...root.querySelectorAll('[data-sel]:checked')].map((c) => c.dataset.sel);
  root.querySelectorAll('[data-sel]').forEach((c) => c.addEventListener('change', () => {
    el('m-print').disabled = !selected().length;
  }));
  el('m-print').addEventListener('click', () => {
    window.open(`/labels?locations=${selected().join(',')}`, '_blank', 'noopener');
  });
  el('m-add-shelf').addEventListener('click', () => locationForm('shelf'));
  el('m-add-box').addEventListener('click', () => locationForm('box'));
  el('m-add-lot').addEventListener('click', () => locationForm('lot'));
  root.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', () => showScanned(b.dataset.open, true)));
}

/** Удаление места: пустое — сразу после подтверждения, с товаром — только после разгрузки. */
function deleteLocationForm(place) {
  const children = state.locations.filter((l) => l.parent_id === place.id);
  const all = [state.locations.find((l) => l.id === place.id) || place, ...children];
  const busy = all.filter((l) => l.products || l.instances);
  const list = (rows) => rows.map((l) => `<span class="code-chip">${esc(l.code)}</span> ${esc(l.name)}`).join(', ');
  if (busy.length) {
    openModal(`Удалить ${place.code} нельзя`, `
      <p style="margin:0 0 10px">Внутри лежит товар: ${list(busy)}.</p>
      <p class="muted" style="margin:0 0 14px">Переложите его в другое место или выдайте — потом место можно будет удалить.</p>
      <button class="btn btn-lg btn-block" id="d-cancel">Понятно</button>`);
    el('d-cancel').addEventListener('click', closeModal);
    return;
  }
  openModal(`Удалить ${place.code}?`, `
    <p style="margin:0 0 10px">${esc(KIND_TITLES[place.kind])} «${esc(place.name)}» пропадёт из списков и сканера,
      но останется в истории операций.</p>
    ${children.length ? `<p style="margin:0 0 10px">Вместе с полкой удалятся: ${list(children)}.</p>` : ''}
    <p class="muted small" style="margin:0 0 14px">Наклейку можно снять: код ${esc(place.code)} больше никому не достанется.</p>
    <div class="row-actions">
      <button class="btn btn-lg" id="d-cancel">Отмена</button>
      <button class="btn btn-danger btn-lg" id="d-ok">Удалить</button>
    </div>`);
  el('d-cancel').addEventListener('click', closeModal);
  el('d-ok').addEventListener('click', async () => {
    try {
      const result = await api(`/api/stock/locations/${place.id}`, { method: 'DELETE' });
      toast(`Удалено: ${result.deleted.join(', ')}`);
    } catch (error) {
      const data = error.data || {};
      toast(data.error === 'not_empty'
        ? 'Внутри появился товар — сначала переложите или выдайте его'
        : 'Не получилось удалить');
      return;
    }
    closeModal();
    await loadLocations();
    state.arg = null;
    if (window.location.hash !== '#/scan') history.replaceState(null, '', '#/scan');
    await route();
  });
}

/** Полка — под раздел; коробка и место на полке — под подраздел раздела своей полки. */
function locationForm(kind, existing = null, presetParent = null) {
  const shelves = state.locations.filter((l) => l.kind === 'shelf');
  const chosen = existing && existing.category_ids.length ? existing.category_ids[0] : null;
  const parentId = existing ? existing.parent_id : presetParent;
  const titles = { shelf: 'Новая полка', box: 'Новая коробка', lot: 'Новое место на полке' };
  const hints = {
    shelf: 'например: Стеллаж 2, полка 3',
    box: 'например: Салфетки для обработки',
    lot: 'например: Кровати, левый край',
  };
  openModal(existing ? `Изменить ${existing.code}` : titles[kind], `
    ${kind === 'lot' && !existing ? '<p class="muted small" style="margin:0 0 12px">Место на полке — участок полки со своим QR для товара без коробки, например под крупный товар.</p>' : ''}
    ${kind !== 'shelf' ? `<div class="form-row"><label>На какой полке</label>
      <select id="f-parent">
        <option value="">${kind === 'box' ? '— не на полке —' : '— выберите полку —'}</option>
        ${shelves.map((s) => `<option value="${s.id}" ${s.id === parentId ? 'selected' : ''}>${esc(s.code)} · ${esc(s.name)}${purposeOf(s.id) ? ` (${esc(purposeOf(s.id))})` : ''}</option>`).join('')}
      </select></div>` : ''}
    <div class="form-row"><label>${kind === 'shelf' ? 'Раздел' : 'Подраздел'}</label>
      <select id="f-cat"></select>
      <div class="auto-tag">${kind === 'shelf'
        ? 'Вся полка под этот раздел; коробки и места на ней получат его подразделы'
        : 'Показаны подразделы раздела выбранной полки'}</div></div>
    <div class="form-row"><label>Название</label>
      <input type="text" id="f-name" value="${esc(existing ? existing.name : '')}" placeholder="${hints[kind]}"></div>
    <button class="btn btn-primary btn-lg btn-block" id="f-ok">${existing ? 'Сохранить' : 'Создать'}</button>`);

  const fillCategories = () => {
    if (kind === 'shelf') {
      el('f-cat').innerHTML = '<option value="">— без раздела —</option>' + state.categories.map((top) =>
        `<option value="${top.id}" ${top.id === chosen ? 'selected' : ''}>${esc(top.name)}</option>`).join('');
      return;
    }
    const shelf = shelves.find((s) => String(s.id) === el('f-parent').value);
    const tops = shelf && shelf.category_ids.length
      ? state.categories.filter((top) => shelf.category_ids.includes(top.id))
      : state.categories;
    const current = el('f-cat').value ? Number(el('f-cat').value) : chosen;
    el('f-cat').innerHTML = '<option value="">— без подраздела —</option>' + tops.map((top) => `
      <optgroup label="${esc(top.name)}">${top.children.map((c) =>
        `<option value="${c.id}" ${c.id === current ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</optgroup>`).join('');
  };
  fillCategories();
  if (kind !== 'shelf') el('f-parent').addEventListener('change', fillCategories);
  // пустое название подставляем из раздела или подраздела — потом можно поправить
  el('f-cat').addEventListener('change', () => {
    const option = el('f-cat').selectedOptions[0];
    if (!el('f-name').value.trim() && el('f-cat').value && option) el('f-name').value = option.textContent;
  });

  el('f-ok').addEventListener('click', async () => {
    const name = el('f-name').value.trim();
    if (!name) { toast('Введите название'); return; }
    const payload = { kind, name, category_ids: el('f-cat').value ? [Number(el('f-cat').value)] : [] };
    if (kind !== 'shelf') {
      payload.parent_id = el('f-parent').value ? Number(el('f-parent').value) : null;
      if (kind === 'lot' && !payload.parent_id) { toast('Выберите полку'); return; }
    }
    let result;
    try {
      result = existing
        ? await post(`/api/stock/locations/${existing.id}`, payload)
        : await post('/api/stock/locations', payload);
    } catch (error) {
      toast(explain(error));
      return;
    }
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

/* ============================================================= дашборд */

const PALETTE = ['#4f7cff', '#22c3e6', '#3ecf8e', '#f5a524', '#a78bfa', '#f26d6d', '#14b8a6', '#eab308', '#ec4899', '#64748b'];
const KIND_LABEL = { in: 'Принято', out: 'Выдано', move: 'Перемещено', adjust: 'Инвентаризация' };

// фильтры дашборда живут, пока открыта страница
const dash = { top: null, sub: null, days: 30, from: null, to: null, data: null };

const isoDay = (date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
const ruDay = (iso) => iso.split('-').reverse().join('.');

function presetPeriod(days) {
  const to = new Date();
  const from = new Date();
  from.setDate(to.getDate() - (days - 1));
  return { from: isoDay(from), to: isoDay(to) };
}

/** Красивый максимум оси: 1, 2, 5, 10, 20, 50… */
function niceMax(value) {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 5, 10].find((m) => m * power >= value);
  return step * power;
}

function barChart(labels, incoming, outgoing, width = 720) {
  const height = 230;
  const pad = { left: 36, right: 8, top: 12, bottom: 26 };
  const max = niceMax(Math.max(...incoming, ...outgoing, 0));
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const slot = plotW / Math.max(labels.length, 1);
  const bar = Math.max(2, Math.min(14, slot * 0.34));
  const y = (value) => pad.top + plotH - (value / max) * plotH;
  const every = Math.ceil(labels.length / Math.max(4, Math.floor(plotW / 56)));  // подписи не налезают
  let svg = '';
  for (let i = 0; i <= 4; i += 1) {
    const value = (max / 4) * i;
    svg += `<line x1="${pad.left}" x2="${width - pad.right}" y1="${y(value)}" y2="${y(value)}" class="grid-line"/>
      <text x="${pad.left - 6}" y="${y(value) + 4}" class="axis" text-anchor="end">${num(value)}</text>`;
  }
  labels.forEach((label, i) => {
    const center = pad.left + slot * i + slot / 2;
    const a = incoming[i] || 0;
    const b = outgoing[i] || 0;
    if (a) svg += `<rect x="${center - bar - 1}" y="${y(a)}" width="${bar}" height="${y(0) - y(a)}" rx="2" fill="var(--chart-in)"><title>${esc(label)}: принято ${num(a)}</title></rect>`;
    if (b) svg += `<rect x="${center + 1}" y="${y(b)}" width="${bar}" height="${y(0) - y(b)}" rx="2" fill="var(--chart-out)"><title>${esc(label)}: выдано ${num(b)}</title></rect>`;
    if (i % every === 0) svg += `<text x="${center}" y="${height - 8}" class="axis" text-anchor="middle">${esc(label)}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Приход и выдача по периодам">${svg}</svg>`;
}

function sparkline(values, color) {
  const width = 140;
  const height = 36;
  const max = Math.max(...values, 0);
  if (!values.length) return '';
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values.map((v, i) => [i * step, height - 3 - (max ? (v / max) * (height - 8) : 0)]);
  const line = points.map(([x, yy], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${yy.toFixed(1)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
    <path d="${line} L${width},${height} L0,${height} Z" fill="${color}" opacity=".12"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/>
  </svg>`;
}

function donut(items, centerLabel) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  if (!total) return '<p class="muted">За период выдач не было.</p>';
  const radius = 52;
  const length = 2 * Math.PI * radius;
  let offset = 0;
  const arcs = items.map((item) => {
    const part = (item.value / total) * length;
    const arc = `<circle r="${radius}" cx="70" cy="70" fill="none" stroke="${item.color}" stroke-width="18"
      stroke-dasharray="${part} ${length - part}" stroke-dashoffset="${-offset}"><title>${esc(item.name)}: ${num(item.value)}</title></circle>`;
    offset += part;
    return arc;
  }).join('');
  return `
    <div class="donut-wrap">
      <svg class="donut" viewBox="0 0 140 140" role="img" aria-label="Структура выдачи">
        <g transform="rotate(-90 70 70)">${arcs}</g>
        <text x="70" y="68" text-anchor="middle" class="donut-num">${num(total)}</text>
        <text x="70" y="86" text-anchor="middle" class="donut-sub">${esc(centerLabel)}</text>
      </svg>
      <ul class="legend">${items.map((item) => `
        <li><i style="background:${item.color}"></i><span>${esc(item.name)}</span>
          <b>${Math.round((item.value / total) * 100)}%</b></li>`).join('')}</ul>
    </div>`;
}

function hbars(rows, valueOf, labelOf, attrs = () => '') {
  const max = Math.max(...rows.map(valueOf), 0) || 1;
  return rows.map((row) => `
    <button class="hbar" ${attrs(row)}>
      <span class="hbar-name">${esc(row.name)}${row.department ? `<small>${esc(row.department)}</small>` : ''}</span>
      <span class="hbar-track"><i style="width:${Math.max(4, (valueOf(row) / max) * 100)}%"></i></span>
      <span class="hbar-val">${labelOf(row)}</span>
    </button>`).join('');
}

function historyRows(rows, withRecipient = true) {
  if (!rows.length) return '<p class="muted">За период операций не было.</p>';
  return `<div class="hist">${rows.map((m) => `
    <div class="hist-row">
      <span class="hist-kind ${esc(m.kind || 'out')}">${KIND_LABEL[m.kind || 'out'] || m.kind} ${num(m.quantity)} ${esc(m.unit || '')}</span>
      <span>${esc(m.name)}<div class="small muted">${esc(m.path || '')}</div></span>
      <span class="muted">${esc(m.from_code || '')}${m.from_code && m.to_code ? ' → ' : ''}${esc(m.to_code || '')}</span>
      <span class="muted">${esc(m.actor_name || '')}${withRecipient && m.recipient_name ? ` → ${esc(m.recipient_name)}` : ''}${m.note ? `<div class="small">${esc(m.note)}</div>` : ''}</span>
      <span class="hist-when">${esc(m.created_at)}</span>
    </div>`).join('')}</div>`;
}

async function viewDashboard(root) {
  if (!dash.from) Object.assign(dash, presetPeriod(dash.days));
  const params = new URLSearchParams({ from: dash.from, to: dash.to });
  if (dash.top) params.set('top', dash.top);
  if (dash.sub) params.set('sub', dash.sub);
  const data = await api(`/api/stock/dashboard?${params}`);
  dash.data = data;
  const top = state.categories.find((c) => c.id === dash.top);
  const sub = top && top.children.find((c) => c.id === dash.sub);
  const t = data.totals;
  const groupTitle = { categories: 'По разделам', subcategories: 'По подкатегориям', products: 'Товары' }[data.level];
  const busy = (g) => g.products || g.issued || g.received;
  const activeGroups = data.groups.filter(busy);
  const emptyGroups = data.groups.filter((g) => !busy(g));
  const issuedGroups = data.groups.filter((g) => g.issued > 0).sort((a, b) => b.issued - a.issued);
  const donutItems = issuedGroups.slice(0, 7).map((g, i) => ({ name: g.name, value: g.issued, color: PALETTE[i] }));
  const rest = issuedGroups.slice(7).reduce((sum, g) => sum + g.issued, 0);
  if (rest) donutItems.push({ name: 'Остальное', value: rest, color: PALETTE[9] });

  root.innerHTML = `
    <div class="dash">
      <div class="dash-head">
        <div>
          <h2>Дашборд склада снабжения</h2>
          <div class="crumbs">
            <button class="link-btn" data-crumb="all">Все разделы</button>
            ${top ? ` › <button class="link-btn" data-crumb="top">${esc(top.name)}</button>` : ''}
            ${sub ? ` › <span>${esc(sub.name)}</span>` : ''}
            <span class="muted"> · ${ruDay(data.period.from)} — ${ruDay(data.period.to)}</span>
          </div>
        </div>
        <button class="btn" id="d-person">Сотрудник: что забирал</button>
      </div>

      <div class="dash-filters">
        <label>Раздел
          <select id="d-top"><option value="">Все разделы</option>
            ${state.categories.map((c) => `<option value="${c.id}" ${c.id === dash.top ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
          </select></label>
        <label>Подкатегория
          <select id="d-sub" ${top ? '' : 'disabled'}><option value="">Все подкатегории</option>
            ${top ? top.children.map((c) => `<option value="${c.id}" ${c.id === dash.sub ? 'selected' : ''}>${esc(c.name)}</option>`).join('') : ''}
          </select></label>
        <div class="seg" role="group" aria-label="Период">
          ${[[7, '7 дней'], [30, '30 дней'], [90, '90 дней'], [365, 'Год']].map(([days, label]) =>
            `<button class="${dash.days === days ? 'on' : ''}" data-days="${days}">${label}</button>`).join('')}
        </div>
        <label>с <input type="date" id="d-from" value="${dash.from}"></label>
        <label>по <input type="date" id="d-to" value="${dash.to}"></label>
      </div>

      <div class="kpi-row">
        <div class="kpi k-blue"><div class="kpi-label">На складе</div><div class="kpi-num">${t.products}</div>
          <div class="kpi-sub">${plural(t.products, 'товар', 'товара', 'товаров')} · ${num(t.units)} ед.</div></div>
        <div class="kpi k-cyan"><div class="kpi-label">Принято за период</div><div class="kpi-num">${num(t.received_units)}</div>
          <div class="kpi-sub">ед. · ${t.received_ops} ${plural(t.received_ops, 'поступление', 'поступления', 'поступлений')}</div></div>
        <div class="kpi k-green"><div class="kpi-label">Выдано за период</div><div class="kpi-num">${num(t.issued_units)}</div>
          <div class="kpi-sub">ед. · ${t.issued_ops} ${plural(t.issued_ops, 'выдача', 'выдачи', 'выдач')} · ${t.recipients} чел.</div></div>
        <div class="kpi k-orange"><div class="kpi-label">Заканчивается</div><div class="kpi-num">${t.low}</div>
          <div class="kpi-sub">ждут размещения: ${t.waiting}</div></div>
      </div>

      <div class="dash-grid">
        <section class="panel">
          <div class="panel-head"><h3>Приход и выдача</h3>
            <span class="legend-inline"><i style="background:var(--chart-in)"></i>принято <i style="background:var(--chart-out)"></i>выдано</span></div>
          <div id="d-chart"></div>
        </section>
        <section class="panel">
          <div class="panel-head"><h3>Кто забирал чаще</h3></div>
          ${data.recipients.length
            ? `<div class="hbars">${hbars(data.recipients.slice(0, 8), (r) => r.issues,
                (r) => `${r.issues} · ${num(r.units)} ед.`, (r) => `data-person="${esc(r.key)}"`)}</div>`
            : '<p class="muted">За период выдач не было.</p>'}
        </section>
      </div>

      <section class="panel">
        <div class="panel-head"><h3>${groupTitle}</h3>
          ${data.level !== 'products' ? '<span class="muted small">нажмите на карточку, чтобы раскрыть</span>' : ''}</div>
        <div class="group-cards">
          ${activeGroups.map((g, i) => {
            const id = g.key.startsWith('c') ? Number(g.key.slice(1)) : null;
            const clickable = id && data.level !== 'products';
            return `
              <${clickable ? 'button' : 'div'} class="gcard ${g.products ? '' : 'is-empty'}" ${clickable ? `data-drill="${id}"` : ''}>
                <div class="gcard-name">${esc(g.name)}${g.low ? `<span class="badge-low">мало: ${g.low}</span>` : ''}</div>
                <div class="gcard-num">${data.level === 'products' ? num(g.on_hand) : g.products}
                  <span>${data.level === 'products' ? 'на складе' : plural(g.products, 'товар', 'товара', 'товаров')}</span></div>
                ${sparkline(g.series, PALETTE[i % PALETTE.length])}
                <div class="gcard-meta">выдано ${num(g.issued)} · принято ${num(g.received)}</div>
              </${clickable ? 'button' : 'div'}>`;
          }).join('') || '<p class="muted">Здесь пока ничего нет.</p>'}
        </div>
        ${emptyGroups.length ? `<div class="empty-groups">Пока пусто:
          ${emptyGroups.map((g) => {
            const id = g.key.startsWith('c') ? Number(g.key.slice(1)) : null;
            return id && data.level !== 'products'
              ? `<button class="link-btn" data-drill="${id}">${esc(g.name)}</button>` : `<span>${esc(g.name)}</span>`;
          }).join(', ')}</div>` : ''}
      </section>

      <div class="dash-grid three">
        <section class="panel">
          <div class="panel-head"><h3>Структура выдачи</h3></div>
          ${donut(donutItems, 'ед. выдано')}
        </section>
        <section class="panel">
          <div class="panel-head"><h3>Полки</h3></div>
          ${data.shelves.length ? `<ul class="plain-list">${data.shelves.map((s) => `
            <li><a href="#/scan/${encodeURIComponent(s.code)}" class="code-chip">${esc(s.code)}</a>
              <span>${esc(s.name)}${s.parent_code ? ` <span class="muted small">на ${esc(s.parent_code)}</span>` : ''}</span>
              <span class="muted small">${s.products ? productsCount(s.products) : 'пусто'}${s.assigned ? ' · назначена' : ''}</span></li>`).join('')}</ul>`
            : `<p class="muted">${dash.top ? 'Под эту категорию полки ещё не назначены.' : 'Полки появятся, когда товар разложат.'}</p>`}
        </section>
        <section class="panel">
          <div class="panel-head"><h3>Заканчивается</h3></div>
          ${data.low_products.length ? `<ul class="plain-list">${data.low_products.map((p) => `
            <li><span>${esc(p.name)}</span><span class="warn-text"><b>${num(p.quantity)}</b> из мин. ${num(p.min_stock)} ${esc(p.unit || '')}</span></li>`).join('')}</ul>`
            : '<p class="muted">Всего хватает. Минимальный остаток задаётся в «Товарах».</p>'}
        </section>
      </div>

      <section class="panel">
        <div class="panel-head"><h3>Операции</h3><span class="muted small">последние ${data.history.length} за период</span></div>
        ${historyRows(data.history)}
      </section>
    </div>`;

  const chartBox = el('d-chart');
  chartBox.innerHTML = barChart(data.labels, data.series_in, data.series_out, Math.max(300, Math.round(chartBox.clientWidth)));

  const reload = () => route();
  el('d-top').addEventListener('change', (e) => { dash.top = e.target.value ? Number(e.target.value) : null; dash.sub = null; reload(); });
  el('d-sub').addEventListener('change', (e) => { dash.sub = e.target.value ? Number(e.target.value) : null; reload(); });
  root.querySelectorAll('[data-days]').forEach((b) => b.addEventListener('click', () => {
    dash.days = Number(b.dataset.days);
    Object.assign(dash, presetPeriod(dash.days));
    reload();
  }));
  const setDates = () => {
    if (!el('d-from').value || !el('d-to').value) return;
    dash.days = null;
    dash.from = el('d-from').value;
    dash.to = el('d-to').value;
    reload();
  };
  el('d-from').addEventListener('change', setDates);
  el('d-to').addEventListener('change', setDates);
  root.querySelectorAll('[data-crumb]').forEach((b) => b.addEventListener('click', () => {
    if (b.dataset.crumb === 'all') dash.top = null;
    dash.sub = null;
    reload();
  }));
  root.querySelectorAll('[data-drill]').forEach((b) => b.addEventListener('click', () => {
    const id = Number(b.dataset.drill);
    if (data.level === 'categories') { dash.top = id; dash.sub = null; } else { dash.sub = id; }
    reload();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }));
  root.querySelectorAll('[data-person]').forEach((b) => b.addEventListener('click', () => openPerson(b.dataset.person)));
  el('d-person').addEventListener('click', () => openPerson(null));
}

/* ------------------------------------------------ карточка сотрудника */

let recipientsCache = null;

function closeDrawer() {
  const drawer = el('drawer');
  if (drawer) drawer.hidden = true;
}
el('drawer-close').addEventListener('click', closeDrawer);
el('drawer').addEventListener('click', (event) => { if (event.target === el('drawer')) closeDrawer(); });

async function openPerson(key) {
  el('drawer').hidden = false;
  el('drawer-title').textContent = 'Что забирал сотрудник';
  el('drawer-body').innerHTML = '<p class="muted">Загружаю…</p>';
  recipientsCache = (await api('/api/stock/recipients')).recipients;
  const groups = {};
  for (const person of recipientsCache) (groups[person.department || 'Без отделения'] ||= []).push(person);
  el('drawer-body').innerHTML = `
    <div class="form-row"><label>Сотрудник</label>
      <select id="p-who"><option value="">— выберите —</option>
        ${Object.entries(groups).map(([name, people]) => `<optgroup label="${esc(name)}">${people.map((p) =>
          `<option value="${esc(p.key)}" ${p.key === key ? 'selected' : ''}>${esc(p.name)}${p.issues ? ` (${p.issues})` : ''}</option>`).join('')}</optgroup>`).join('')}
      </select></div>
    <p class="muted small">Период как на дашборде: ${ruDay(dash.from)} — ${ruDay(dash.to)}</p>
    <div id="p-report"></div>`;
  el('p-who').addEventListener('change', (e) => renderPerson(e.target.value));
  if (key) renderPerson(key);
}

async function renderPerson(key) {
  const box = el('p-report');
  if (!key) { box.innerHTML = ''; return; }
  box.innerHTML = '<p class="muted">Загружаю…</p>';
  const params = new URLSearchParams({ key, from: dash.from, to: dash.to });
  const report = await api(`/api/stock/recipient?${params}`);
  box.innerHTML = `
    <div class="person-head">
      <div class="person-name">${esc(report.name)}</div>
      ${report.department ? `<div class="muted">${esc(report.department)}</div>` : ''}
    </div>
    <div class="mini-kpis">
      <div><b>${report.issues}</b><span>${plural(report.issues, 'выдача', 'выдачи', 'выдач')}</span></div>
      <div><b>${num(report.units)}</b><span>ед. получено</span></div>
    </div>
    ${report.by_category.length ? `
      <h4>По разделам</h4>
      <div class="hbars">${hbars(report.by_category, (r) => r.units, (r) => `${num(r.units)} ед.`)}</div>
      <h4>Чаще всего брал</h4>
      <ul class="plain-list">${report.top_products.map((p) => `
        <li><span>${esc(p.name)}</span><span class="muted small">${p.issues} раз · ${num(p.units)} ${esc(p.unit || '')}</span></li>`).join('')}</ul>
      <h4>История</h4>
      ${historyRows(report.history, false)}` : '<p class="muted">За этот период ничего не получал.</p>'}`;
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
