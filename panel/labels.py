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
    """Что зашито в QR: сам код или ссылка, если задан STOCK_QR_BASE."""
    base = settings.stock_qr_base
    return f"{base.rstrip('/')}/{code}" if base else code


def render(items: list[dict[str, Any]]) -> str:
    """Собирает страницу наклеек по списку позиций."""
    cells = []
    for item in items:
        code = item.get("stock_code") or ""
        name = (item.get("name") or "")[:70]
        quantity = item.get("quantity") or ""
        request_id = item.get("request_id") or ""
        cells.append(
            f"""
      <div class="label">
        <div class="qr">{qr_svg(qr_payload(code))}</div>
        <div class="text">
          <div class="code">{escape(code)}</div>
          <div class="name">{escape(name)}</div>
          <div class="meta">Заявка №{escape(str(request_id))} · {escape(quantity)}</div>
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
  .code {{ font-size: 4.2mm; font-weight: 700; letter-spacing: 0.2mm; }}
  .name {{
    font-size: 3.1mm;
    line-height: 1.25;
    margin-top: 1mm;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .meta {{ font-size: 2.8mm; color: #555; margin-top: 1mm; }}

  .hint {{ max-width: 200mm; margin: 10mm auto 4mm; font-size: 13px; color: #444; }}
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
    Лист под самоклеящуюся бумагу с сеткой 70×37 мм (24 наклейки, Avery L7160).
    Печатать в масштабе 100%, без «подгонки по размеру страницы».
  </p>
  <div class="sheet">{''.join(cells)}</div>
</body>
</html>"""
