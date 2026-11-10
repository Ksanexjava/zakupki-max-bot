"""Лист наклеек А4 со складскими кодами и QR.

Сетка 3×8 — это стандартные самоклеящиеся листы 70×37 мм (Avery L7160
и его аналоги). Печатать как есть, масштаб 100%.
"""

from html import escape
from typing import Any

import segno

from config import settings

LABELS_PER_PAGE = 24


def qr_svg(data: str) -> str:
    """QR как встроенный SVG. Размер задаётся стилями — печать выходит чёткой
    при любом масштабе, растр бы замылился."""
    code = segno.make(data, error="m")
    return code.svg_inline(omitsize=True, border=0, dark="#000")


def qr_payload(code: str) -> str:
    """Что зашито в QR.

    Если известен адрес панели — ссылка вида …/s/SH-01: её откроет обычная
    камера телефона, без всяких приложений. Иначе просто код.
    """
    base = settings.stock_qr_base or (
        f"{settings.panel_public_url}/s" if settings.panel_public_url else ""
    )
    return f"{base.rstrip('/')}/{code}" if base else code


def position_label(item: dict[str, Any], path: str = "") -> dict[str, str]:
    """Наклейка на товар из заявки: что это и к какой категории относится."""
    return {
        "code": item.get("stock_code") or "",
        "title": (item.get("name") or "")[:90],
        "meta": path,
        "kind": "item",
    }


def location_label(location: dict[str, Any], categories: dict[int, str],
                   locations: dict[int, dict[str, Any]]) -> dict[str, str]:
    kind = {"shelf": "Полка", "box": "Коробка", "zone": "Зона"}.get(location["kind"], "")
    purpose = ", ".join(categories[c] for c in location.get("category_ids", []) if c in categories)
    parent = locations.get(location.get("parent_id"))
    where = f"{kind} на {parent['code']}" if parent is not None else kind
    return {
        "code": location["code"],
        "title": location["name"][:90],
        "meta": " · ".join(part for part in (where, purpose) if part)[:100],
        "kind": location["kind"],
    }


def instance_label(instance: dict[str, Any], path: str = "") -> dict[str, str]:
    return {
        "code": instance["code"],
        "title": (instance.get("product_name") or "")[:90],
        "meta": path,
        "kind": "instance",
    }


def render(labels: list[dict[str, str]]) -> str:
    """Собирает страницу наклеек. Каждая наклейка: код, заголовок, подпись."""
    cells = []
    for label in labels:
        code = label.get("code") or ""
        big = " big" if label.get("kind") in {"shelf", "box"} else ""
        cells.append(
            f"""
      <div class="label{big}">
        <div class="qr">{qr_svg(qr_payload(code))}</div>
        <div class="text">
          <div class="name">{escape(label.get("title") or "")}</div>
          <div class="meta">{escape(label.get("meta") or "")}</div>
          <div class="code">{escape(code)}</div>
        </div>
      </div>"""
        )
    # добиваем страницу пустыми ячейками, чтобы сетка не разъезжала
    while len(cells) % 3:
        cells.append('<div class="label empty"></div>')

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Наклейки на товар</title>
<style>
  @page {{ size: A4 portrait; margin: 8mm 5mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    color: #111;
    background: #e9ebee;
  }}
  .sheet {{
    width: 200mm;
    margin: 0 auto;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0;
  }}
  .label {{
    height: 37mm;
    padding: 2.5mm;
    display: flex;
    align-items: center;
    gap: 2.5mm;
    overflow: hidden;
  }}
  .label.empty {{ visibility: hidden; }}
  .qr {{ flex: none; line-height: 0; }}
  .qr svg {{ display: block; width: 21mm; height: 21mm; }}
  .text {{ min-width: 0; }}
  .name {{
    font-size: 3.5mm;
    font-weight: 700;
    line-height: 1.2;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .meta {{
    font-size: 2.7mm; color: #444; margin-top: 1mm; line-height: 1.2;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }}
  .code {{ font-size: 2.9mm; font-family: Menlo, Consolas, monospace; margin-top: 1.2mm; letter-spacing: 0.2mm; }}
  .label.big .name {{ font-size: 4.2mm; }}
  .label.big .code {{ font-size: 3.4mm; font-weight: 700; }}

  .hint {{ max-width: 200mm; margin: 10mm auto 4mm; font-size: 13px; color: #444; }}
  .hint button {{ font: inherit; padding: 6px 14px; margin-right: 10px; cursor: pointer; }}
  @media screen {{
    .sheet {{ background: #fff; padding: 8mm 5mm; box-shadow: 0 4px 24px rgba(0,0,0,.15); }}
  }}
  @media print {{
    .hint {{ display: none; }}
    body {{ background: #fff; }}
    .sheet {{ box-shadow: none; padding: 0; }}
  }}
</style>
</head>
<body>
  <p class="hint">
    <button onclick="window.print()">Напечатать</button>
    Самоклейка 70×37 мм, 24 наклейки на листе. Масштаб 100%, без подгонки по размеру.
  </p>
  <div class="sheet">{''.join(cells)}</div>
</body>
</html>"""
