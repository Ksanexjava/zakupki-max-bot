'use strict';

const el = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
));

// простые линейные иконки — без эмодзи
const ICONS = {
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7l10-5z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
  out: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>',
  scan: '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M7 12h10"/>',
  tag: '<path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><path d="M7 7h.01"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
};
const icon = (name) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;

const SECTIONS = [
  {
    title: 'Закупки',
    roles: ['admin'],
    tiles: [
      { href: '/zayavki', icon: 'list', title: 'Заявки на закупку', text: 'Все заявки из бота: статусы, комментарии, скриншоты' },
    ],
  },
  {
    title: 'Склад',
    roles: ['admin', 'stock'],
    tiles: [
      { href: '/sklad#/priemka', icon: 'inbox', title: 'Приёмка и размещение', text: 'Отметить, что привезли, разложить по полкам и напечатать QR' },
      { href: '/sklad#/hranenie', icon: 'layers', title: 'Хранение', text: 'Остатки по категориям и подкатегориям' },
      { href: '/sklad#/vydacha', icon: 'out', title: 'Выдача по заявкам', text: 'Отдать заказчику то, что он заказывал' },
      { href: '/sklad#/scan', icon: 'scan', title: 'Сканер и места', text: 'Что лежит в коробке или на полке, полки и коробки' },
      { href: '/sklad#/tovary', icon: 'tag', title: 'Товары и категории', text: 'Справочник и распределение по категориям' },
      { href: '/sklad#/istoriya', icon: 'clock', title: 'История', text: 'Все приходы, перемещения и выдачи' },
    ],
  },
];

function render(role) {
  const visible = SECTIONS.filter((section) => section.roles.includes(role));
  el('sections').innerHTML = visible.map((section) => `
    <section class="home-section">
      <h2>${esc(section.title)}</h2>
      <div class="tiles">
        ${section.tiles.map((tile) => `
          <a class="tile" href="${esc(tile.href)}">
            <span class="tile-icon">${icon(tile.icon)}</span>
            <span>
              <div class="tile-title">${esc(tile.title)}</div>
              <div class="tile-text">${esc(tile.text)}</div>
            </span>
          </a>`).join('')}
      </div>
    </section>`).join('');

  el('portal-nav').innerHTML = [
    role === 'admin' ? '<a href="/zayavki">Заявки</a>' : '',
    '<a href="/sklad#/priemka">Склад</a>',
  ].join('');
}

function showLogin(message) {
  el('app').hidden = true;
  el('login-screen').hidden = false;
  el('login-error').hidden = !message;
  el('login-error').textContent = message || '';
}

function showApp(user, role) {
  el('login-screen').hidden = true;
  el('app').hidden = false;
  el('user-chip').textContent = user;
  render(role);
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
  showApp(data.user, data.role);
});

el('logout-btn').addEventListener('click', async () => {
  await fetch('/api/logout', { method: 'POST' });
  showLogin();
});

(async () => {
  const meta = await fetch('/api/meta').then((r) => r.json()).catch(() => null);
  if (!meta || !meta.user) { showLogin(); return; }
  showApp(meta.user, meta.role);
})();
