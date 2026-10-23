"""Разбор списка позиций, присланного одним сообщением."""

import re

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
#: «10 шт», «5 упаковок», «2 пары» в самом конце строки
TRAILING_QTY_RE = re.compile(
    r"[\s,;]+(\d+[\d\s.,]*\s*(?:шт\.?|штук\w*|уп\.?|упак\w*|пачк\w*|короб\w*|кор\.?|"
    r"пар\w*|компл\w*|набор\w*|рул\w*|бут\w*|бан\w*))\s*$",
    re.IGNORECASE,
)
#: количество после тире в конце строки: «Гель для стирки — 10»
DASH_QTY_RE = re.compile(r"\s+[-–—]\s+([^-–—]{1,40})$")
LIST_MARKER_RE = re.compile(r"^(?:[-–—•*]+\s+|\d+\s*[.)]\s*)")

MAX_NAME = 500
MAX_QTY = 100


def parse_items(text: str) -> list[dict[str, str | None]]:
    """Каждая строка — отдельная позиция.

    Из строки вынимаются ссылка и количество, остальное считается названием.
    Разбор намеренно осторожный: если количество не распознано, оно остаётся
    пустым, и бот спросит его отдельно — лучше переспросить, чем угадать.
    """
    items: list[dict[str, str | None]] = []
    for raw_line in text.splitlines():
        line = LIST_MARKER_RE.sub("", raw_line.strip())
        if not line:
            continue

        # ссылку вынимаем первой: иначе она попадёт в количество,
        # если стоит после тире («Гель — 10 шт https://...»)
        link = None
        url = URL_RE.search(line)
        if url:
            link = url.group(0).rstrip(".,;)")
            line = (line[: url.start()] + " " + line[url.end():]).strip()

        quantity = ""
        match = DASH_QTY_RE.search(line)
        if match and re.search(r"\d", match.group(1)):
            quantity = match.group(1).strip()
            line = line[: match.start()].strip()

        if not quantity:
            match = TRAILING_QTY_RE.search(line)
            if match:
                quantity = re.sub(r"\s+", " ", match.group(1)).strip()
                line = line[: match.start()].strip()

        name = re.sub(r"\s{2,}", " ", line).strip(" ,;-–—")
        if not name:
            name = link or ""
        if not name:
            continue

        items.append(
            {
                "name": name[:MAX_NAME],
                "quantity": quantity[:MAX_QTY],
                "link": link,
            }
        )
    return items
