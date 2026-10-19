# Разворачивание на сервере (Ubuntu/Debian)

Два варианта: **Docker** (проще) или **systemd** (без докера).
В обоих случаях наружу смотрит nginx с HTTPS, а приложение слушает только localhost.

---

## Вариант A. Docker

```bash
# 1. Залить проект на сервер
ssh root@СЕРВЕР
mkdir -p /opt/zakupki && cd /opt/zakupki
# скопируйте сюда файлы проекта (rsync/scp/git clone)

# 2. Настроить
cp .env.example .env
nano .env        # MAX_BOT_TOKEN, PANEL_USERS, SECRET_KEY, ADMIN_CODE,
                 # PANEL_PUBLIC_URL=https://zakupki.ваш-домен.ру
                 # PANEL_SECURE_COOKIE=true

# 3. Запустить
docker compose up -d --build

# 4. Логи
docker compose logs -f
```

Контейнер слушает `127.0.0.1:8080`, база и фотографии лежат в `./data` на хосте.
Обновление после изменений: `docker compose up -d --build`.

Если хотите, чтобы незаполненные анкеты переживали перезапуск, раскомментируйте
в `compose.yaml` сервис `redis` и строку `REDIS_URL`.

---

## Вариант B. systemd

```bash
# 1. Пользователь и каталог
sudo adduser --system --group --home /opt/zakupki zakupki
cd /opt/zakupki
# скопируйте сюда файлы проекта

# 2. Окружение (нужен Python 3.10+)
sudo -u zakupki python3 -m venv .venv
sudo -u zakupki .venv/bin/pip install -r requirements.txt

# 3. Настройки
sudo -u zakupki cp .env.example .env
sudo -u zakupki nano .env
sudo chmod 600 .env

# 4. Сервис
sudo cp deploy/zakupki.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zakupki
sudo systemctl status zakupki
journalctl -u zakupki -f      # логи
```

---

## nginx + HTTPS

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/zakupki
sudo nano /etc/nginx/sites-available/zakupki     # заменить zakupki.example.ru на свой домен
sudo ln -s /etc/nginx/sites-available/zakupki /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# сертификат Let's Encrypt
sudo certbot --nginx -d zakupki.ваш-домен.ру
```

После появления HTTPS обязательно в `.env`:

```
PANEL_PUBLIC_URL=https://zakupki.ваш-домен.ру
PANEL_SECURE_COOKIE=true
```

и перезапустить (`docker compose up -d` или `systemctl restart zakupki`).

> Без домена панель тоже работает — по `http://IP-сервера:8080`,
> но тогда в `.env` нужно `PANEL_HOST=0.0.0.0`, а пароли пойдут по открытому HTTP.
> Для постоянной работы лучше домен и сертификат.

---

## Как дать доступ второму человеку

1. В `.env` допишите его в `PANEL_USERS` через запятую:
   `PANEL_USERS="mike:пароль1,ivan:пароль2"`
2. Перезапустите сервис.
3. Дайте ему адрес панели, логин и пароль.

В истории каждой заявки видно, кто и когда менял статус, — имена берутся из логинов.

Чтобы он ещё и получал уведомления о новых заявках в MAX, пусть напишет боту
`/admin ВАШ_ADMIN_CODE`.

---

## Бэкап

Все данные — в папке `data`: файл базы `purchases.db` и фотографии в `media/`.

```bash
# ежедневный бэкап в /var/backups (положить в cron)
0 3 * * * tar czf /var/backups/zakupki-$(date +\%F).tgz -C /opt/zakupki data
```

Восстановление: распаковать `data` обратно и перезапустить сервис.

---

## Обновление и обслуживание

| Задача | Команда |
|---|---|
| Логи (docker) | `docker compose logs -f` |
| Логи (systemd) | `journalctl -u zakupki -f` |
| Перезапуск | `docker compose restart` / `sudo systemctl restart zakupki` |
| Проверка живости | `curl -s localhost:8080/healthz` |
| Тесты перед обновлением | `.venv/bin/python -m pytest tests -q` |
| Сменить пароль панели | поправить `PANEL_USERS` в `.env` и перезапустить |
