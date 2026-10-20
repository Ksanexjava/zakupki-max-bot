# Разворачивание на сервере

Пошагово: от чистого Ubuntu до работающего бота с панелью по HTTPS.
Проект живёт в приватном репозитории, поэтому начинаем с доступа к нему.

**Что понадобится:** сервер с Ubuntu 22.04+ и доступом по SSH, домен
(желательно — без него панель будет работать по голому HTTP), токен бота.

> **Важно про расположение сервера.** MAX — российский сервис. Если сервер
> стоит за пределами РФ, подключение к `platform-api2.max.ru` может не
> проходить. Проверяется за минуту командой из раздела «Проверка» — сделайте
> это до того, как настраивать домен и сертификаты.

---

## 0. Главное правило: один бот — один процесс

Long polling отдаёт каждое событие **только одному** получателю. Если бот
останется запущен на вашем Mac и одновременно поднимется на сервере, заявки
начнут теряться: часть уйдёт туда, часть сюда.

Поэтому перед запуском на сервере остановите локальный процесс (Ctrl+C
в терминале с `run.sh`) — или заведите для сервера отдельного бота у @MasterBot
и свой `.env`.

---

## 1. Как положить проект на сервер

Три способа, от самого простого.

### Способ 1. Скопировать папку с Mac (ничего настраивать не нужно)

Выполняется **на Mac**, в своём терминале:

```bash
# создать папку на сервере
ssh ПОЛЬЗОВАТЕЛЬ@АДРЕС_СЕРВЕРА 'sudo mkdir -p /opt/zakupki && sudo chown $USER /opt/zakupki'

# скопировать проект (вместе с .env — настройки сразу приедут)
rsync -av --exclude '.venv' --exclude '.git' --exclude 'data' --exclude '__pycache__' \
  "/Users/mac/Documents/Бот для закупок/" ПОЛЬЗОВАТЕЛЬ@АДРЕС_СЕРВЕРА:/opt/zakupki/
```

Папка `data` намеренно не копируется: на сервере база заведётся своя, чистая.
Обновлять потом — той же командой `rsync`.

### Способ 2. Временно открыть репозиторий

Сделать репозиторий публичным, склонировать на сервере и закрыть обратно:

```bash
# на Mac
gh repo edit Ksanexjava/zakupki-max-bot --visibility public --accept-visibility-change-consequences

# на сервере
sudo mkdir -p /opt/zakupki && sudo chown $USER /opt/zakupki
git clone https://github.com/Ksanexjava/zakupki-max-bot.git /opt/zakupki

# снова на Mac
gh repo edit Ksanexjava/zakupki-max-bot --visibility private --accept-visibility-change-consequences
```

Секретов в репозитории нет (`.env` и `data` туда не попадают), так что за
несколько минут открытости вы рискуете только самим кодом. Минус: после
закрытия `git pull` на сервере перестанет работать — для обновлений
понадобится способ 1 или 3.

### Способ 3. Авторизовать сервер в GitHub (если хотите обновляться через `git pull`)

На сервере:

```bash
sudo apt install -y gh    # либо: https://github.com/cli/cli#installation
gh auth login             # выбрать GitHub.com → HTTPS → Login with a web browser
```

Команда покажет короткий код, его надо ввести в браузере на любом устройстве.
Файлы ключей создавать не нужно. После этого:

```bash
sudo mkdir -p /opt/zakupki && sudo chown $USER /opt/zakupki
gh repo clone Ksanexjava/zakupki-max-bot /opt/zakupki
```

Дальше обновления — обычный `git pull`.

<details>
<summary>Способ 4. Deploy key (для тех, кому привычнее ssh-ключи)</summary>



Создаём на сервере ключ только для чтения этого репозитория:

```bash
ssh-keygen -t ed25519 -C "zakupki-server" -f ~/.ssh/zakupki -N ""
cat ~/.ssh/zakupki.pub
```

Вывод добавляем как deploy key. Проще всего **со своего Mac** (gh уже настроен):

```bash
gh repo deploy-key add ~/путь/к/zakupki.pub --repo Ksanexjava/zakupki-max-bot --title "prod-server"
```

либо вручную: GitHub → репозиторий → Settings → Deploy keys → Add deploy key
(галочку «Allow write access» не ставим).

Настраиваем на сервере ssh и клонируем:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github-zakupki
  HostName github.com
  User git
  IdentityFile ~/.ssh/zakupki
  IdentitiesOnly yes
EOF

sudo mkdir -p /opt/zakupki && sudo chown "$USER" /opt/zakupki
git clone git@github-zakupki:Ksanexjava/zakupki-max-bot.git /opt/zakupki
cd /opt/zakupki
```

</details>

---

## 2. Настройки

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # для SECRET_KEY
nano .env
chmod 600 .env
```

Минимум, что надо заполнить:

```
MAX_BOT_TOKEN=токен от @MasterBot
ADMIN_CODE=секретное слово для команды /admin
PANEL_USERS="mike:пароль"
SECRET_KEY=то, что выдала команда выше
DISPLAY_TZ_OFFSET=3
```

Если уже знаете домен, сразу добавьте:

```
PANEL_PUBLIC_URL=https://zakupki.ваш-домен.ру
PANEL_SECURE_COOKIE=true
```

---

## 3. Запуск: Docker или systemd

### Вариант A. Docker (проще)

```bash
# если докера ещё нет
curl -fsSL https://get.docker.com | sudo sh

# папка под базу и картинки; uid 1000 — пользователь внутри контейнера
mkdir -p data && sudo chown -R 1000:1000 data

sudo docker compose up -d --build
sudo docker compose logs -f
```

Если домена пока нет и панель нужна по IP, добавьте в `.env` строку
`PANEL_BIND=0.0.0.0` — тогда порт 8080 будет открыт наружу.

Контейнер слушает `127.0.0.1:8080`, база и картинки лежат в `./data` на хосте.

Чтобы незаполненные анкеты переживали перезапуск, раскомментируйте в
`compose.yaml` сервис `redis` и строку `REDIS_URL`.

### Вариант B. systemd (без докера)

```bash
sudo apt update && sudo apt install -y python3-venv
sudo adduser --system --group --home /opt/zakupki zakupki
sudo chown -R zakupki:zakupki /opt/zakupki

sudo -u zakupki python3 -m venv /opt/zakupki/.venv
sudo -u zakupki /opt/zakupki/.venv/bin/pip install -r /opt/zakupki/requirements.txt

sudo cp deploy/zakupki.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zakupki
systemctl status zakupki
journalctl -u zakupki -f
```

Нужен Python 3.10 или новее — библиотека `maxapi` на 3.9 не ставится.

---

## 4. Проверка

```bash
# панель отвечает
curl -s localhost:8080/healthz

# связь с MAX: токен, /me, пробное сообщение
cd /opt/zakupki && .venv/bin/python -m tools.check_bot ВАШ_USER_ID
#   в докере:  sudo docker compose exec bot python -m tools.check_bot ВАШ_USER_ID
```

`ВАШ_USER_ID` подскажет сам бот по команде `/id`. Если шаг 2 (`GET /me`)
не проходит — до MAX с этого сервера не достучаться, и дальше идти смысла нет.

Затем в MAX: `/admin ВАШ_ADMIN_CODE` — чтобы уведомления о заявках приходили вам.

---

## 5. Домен и HTTPS

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/zakupki
sudo nano /etc/nginx/sites-available/zakupki      # заменить zakupki.example.ru на свой домен
sudo ln -s /etc/nginx/sites-available/zakupki /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d zakupki.ваш-домен.ру
```

A-запись домена должна указывать на IP сервера — иначе certbot не выдаст сертификат.

После появления HTTPS в `.env`:

```
PANEL_PUBLIC_URL=https://zakupki.ваш-домен.ру
PANEL_SECURE_COOKIE=true
```

и перезапустить: `sudo docker compose up -d` либо `sudo systemctl restart zakupki`.

Если фаервол включён:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Порт 8080 наружу открывать не нужно: приложение слушает только localhost,
снаружи его показывает nginx.

> Без домена панель доступна по `http://IP-сервера:8080`, но тогда в `.env`
> нужно `PANEL_HOST=0.0.0.0`, а логин с паролем пойдут по открытому HTTP.
> Так можно проверить работу, но не стоит оставлять надолго.

---

## 6. Обновление

Если клонировали через git (способы 2–4):

```bash
cd /opt/zakupki
git pull

# Docker
sudo docker compose up -d --build

# systemd
sudo -u zakupki .venv/bin/pip install -r requirements.txt
sudo -u zakupki .venv/bin/python -m pytest tests -q
sudo systemctl restart zakupki
```

Если копировали папкой — повторите ту же команду `rsync` с Mac, а потом
перезапустите сервис на сервере.

`.env` и папка `data` в репозитории не лежат — ни `git pull`, ни `rsync`
(с указанными исключениями) их не затирают.

---

## 7. Бэкап

Все данные — в папке `data`: база `purchases.db`, фотографии и скриншоты в `media/`.

```bash
# ежедневно в 3:00, хранить 14 копий (crontab -e)
0 3 * * * tar czf /var/backups/zakupki-$(date +\%F).tgz -C /opt/zakupki data && find /var/backups -name 'zakupki-*.tgz' -mtime +14 -delete
```

Восстановление: распаковать `data` обратно и перезапустить сервис.

---

## 8. Обслуживание

| Задача | Команда |
|---|---|
| Логи (Docker) | `sudo docker compose logs -f` |
| Логи (systemd) | `journalctl -u zakupki -f` |
| Перезапуск | `sudo docker compose restart` / `sudo systemctl restart zakupki` |
| Живость панели | `curl -s localhost:8080/healthz` |
| Связь с MAX | `.venv/bin/python -m tools.check_bot` |
| Тесты | `.venv/bin/python -m pytest tests -q` |
| Второй человек в панели | дописать в `PANEL_USERS` через запятую и перезапустить |

### Если что-то не работает

| Симптом | Причина и что делать |
|---|---|
| `Связь с MAX потеряна` в логах | Сервер не достучался до API. Проверьте `tools.check_bot`, при необходимости задайте `MAX_API_BASE` |
| Бот молчит, заявки не доходят | Где-то ещё запущен второй процесс с тем же токеном |
| В панель не пускает | Пустой или неверный `PANEL_USERS`; после правки нужен перезапуск |
| Разлогинивает после перезапуска | Не задан `SECRET_KEY` — он генерируется заново при каждом старте |
| Уведомления автору не уходят | Смотрите текст ошибки в тосте панели и в логах |
