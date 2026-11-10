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
  box: '<path d="M21 8 12 3 3 8v8l9 5 9-5V8z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
  sofa: '<path d="M4 11V8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v3"/><path d="M2 13a2 2 0 0 1 4 0v2h12v-2a2 2 0 0 1 4 0v4H2v-4zM5 17v2M19 17v2"/>',
  pen: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>',
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
    title: 'Склады',
    roles: ['admin', 'stock'],
    tiles: [
      { href: '/sklad', icon: 'box', title: 'Склад снабжения', text: 'Заказы из заявок и всё, что приносят: приёмка, хранение, выдача' },
      { href: '/sklad#/w/mebel', icon: 'sofa', title: 'Мебельный склад', text: 'В разработке', soon: true },
      { href: '/sklad#/w/kanc', icon: 'pen', title: 'Склад канцелярии', text: 'В разработке', soon: true },
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
          <a class="tile${tile.soon ? ' soon' : ''}" href="${esc(tile.href)}">
            <span class="tile-icon">${icon(tile.icon)}</span>
            <span>
              <div class="tile-title">${esc(tile.title)}${tile.soon ? '<span class="soon-badge">скоро</span>' : ''}</div>
              <div class="tile-text">${esc(tile.text)}</div>
            </span>
          </a>`).join('')}
      </div>
    </section>`).join('');

  el('portal-nav').innerHTML = [
    role === 'admin' ? '<a href="/zayavki">Заявки</a>' : '',
    '<a href="/sklad">Склад</a>',
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
