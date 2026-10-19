"""Тесты работают во временной базе — переменные окружения ставим до импорта проекта."""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="zakupki-tests-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP}/test.db"
os.environ["MEDIA_DIR"] = f"{_TMP}/media"
os.environ["ADMIN_USER_IDS"] = "999"
os.environ["ADMIN_CODE"] = "test-code"
os.environ["PANEL_ENABLED"] = "false"
os.environ["PANEL_PUBLIC_URL"] = "https://zakupki.example.ru"
os.environ["DISPLAY_TZ_OFFSET"] = "3"
