"""Демо-заявки, чтобы посмотреть панель без подключения к MAX.

Запуск:  python -m tools.seed_demo
Удалить: rm data/purchases.db
"""

import asyncio

from db import repo
from db.session import init_db

DEMO = [
    (
        {
            "requester": "Иванова Мария, бухгалтерия",
            "item": "Чайник электрический Bosch TWK 3A011, 1.7 л",
            "quantity": "1 шт",
            "deadline": "В течение недели",
            "purpose": "На кухню в бухгалтерии — старый потёк и перестал выключаться",
            "example_url": "https://www.ozon.ru/product/chaynik-elektricheskiy-bosch-123456/",
            "author_user_id": 1001,
            "author_name": "Мария Иванова",
            "author_username": "m_ivanova",
            "author_chat_id": 1001,
        },
        None,
        None,
    ),
    (
        {
            "requester": "Петров Сергей, склад",
            "item": "Перчатки рабочие х/б с ПВХ-точкой, размер 10",
            "quantity": "20 пар",
            "deadline": "Срочно, сегодня-завтра",
            "purpose": "Заканчиваются на складе, без них не пускаем грузчиков на разгрузку",
            "author_user_id": 1002,
            "author_name": "Сергей Петров",
            "author_chat_id": 1002,
        },
        "in_progress",
        None,
    ),
    (
        {
            "requester": "Сидорова Анна, отдел продаж",
            "item": "Кресло офисное с поясничной поддержкой",
            "quantity": "2 шт",
            "deadline": "В течение месяца",
            "purpose": "Два новых менеджера выходят с 1 ноября, сидеть не на чем",
            "example_url": "https://www.wildberries.ru/catalog/0000000/detail.aspx",
            "author_user_id": 1003,
            "author_name": "Анна Сидорова",
            "author_username": "anna_s",
            "author_chat_id": 1003,
        },
        "clarify",
        "Уточните, нужна ли подставка для ног",
    ),
    (
        {
            "requester": "Козлов Дмитрий, IT",
            "item": "SSD Samsung 870 EVO 1 ТБ",
            "quantity": "3 шт",
            "deadline": "В течение недели",
            "purpose": "Замена дисков на рабочих станциях — текущие заполнены и тормозят",
            "example_url": "https://www.citilink.ru/product/ssd-samsung-870-evo-1tb/",
            "author_user_id": 1004,
            "author_name": "Дмитрий Козлов",
            "author_username": "dkozlov",
            "author_chat_id": 1004,
        },
        "ordered",
        "Заказано у поставщика, ждём счёт",
    ),
    (
        {
            "requester": "Орлова Елена, маркетинг",
            "item": "Кофе в зёрнах Lavazza Crema e Aroma, 1 кг",
            "quantity": "4 упаковки",
            "deadline": "Не срочно",
            "purpose": "Для кофемашины в переговорной, запас заканчивается к концу месяца",
            "author_user_id": 1005,
            "author_name": "Елена Орлова",
            "author_username": "e_orlova",
            "author_chat_id": 1005,
        },
        None,
        None,
    ),
]


async def main() -> None:
    await init_db()
    for data, status, comment in DEMO:
        request = await repo.create_request(data)
        if status:
            await repo.set_status(request.id, status, "demo", comment)
        print(f"  №{request.id}: {status or 'new'} — {request.item[:40]}")
    print(f"Создано демо-заявок: {len(DEMO)}")


if __name__ == "__main__":
    asyncio.run(main())
