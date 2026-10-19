#!/usr/bin/env bash
# Локальный запуск: venv, зависимости, бот + панель.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3.12}"
command -v "$PYTHON" >/dev/null 2>&1 || PYTHON=python3

if [ ! -d .venv ]; then
  echo "→ создаю виртуальное окружение ($("$PYTHON" -V))"
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "→ создан .env — заполните MAX_BOT_TOKEN и PANEL_USERS, затем запустите снова"
  exit 1
fi

exec python -m bot.main "$@"
