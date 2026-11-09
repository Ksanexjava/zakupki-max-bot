"""Разбор количеств и нормализация названий товаров."""

import re

#: «10 шт», «2,5 кг», «20 пар» — число в начале строки
LEADING_NUMBER_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(.*)$", re.DOTALL)
#: единица — первое слово после числа, до запятой или слова «по»
UNIT_RE = re.compile(r"^([^\s,;]+)")

MAX_UNIT = 30


def parse_quantity(text: str | None) -> tuple[float | None, str]:
    """«10 шт» -> (10.0, 'шт'). Если число не распознано — (None, исходный текст).

    Разбор намеренно осторожный: число берётся только из начала строки.
    «2 коробки по 10 шт» даст (2.0, 'коробки') — это честнее, чем пытаться
    перемножить и ошибиться.
    """
    raw = (text or "").strip()
    if not raw:
        return None, ""

    match = LEADING_NUMBER_RE.match(raw)
    if not match:
        return None, raw[:MAX_UNIT]

    number = float(match.group(1).replace(",", "."))
    tail = match.group(2).strip()
    unit_match = UNIT_RE.match(tail)
    unit = unit_match.group(1) if unit_match else ""
    return number, unit[:MAX_UNIT]


def format_quantity(number: float | None, unit: str = "") -> str:
    """1.0 -> «1 шт», 2.5 -> «2.5 кг»."""
    if number is None:
        return unit or "—"
    text = str(int(number)) if float(number).is_integer() else f"{number:g}"
    return f"{text} {unit}".strip()


def normalize_name(name: str) -> str:
    """Ключ для поиска одинаковых товаров в справочнике.

    Приводим регистр, убираем лишние пробелы и знаки по краям, «ё» к «е».
    Специально не выбрасываем объём и вес: «мыло 1 л» и «мыло 5 л» —
    разные товары, и склеивать их нельзя.
    """
    text = (name or "").lower().replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,;:-–—«»\"'")
