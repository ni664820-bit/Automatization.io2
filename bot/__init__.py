"""Сборка диспетчера: порядок роутеров определяет приоритет обработки.

Импорты внутри функции, чтобы `from bot.keyboards import ...` (используется
в сервисах) не тянул за собой все хендлеры и не создавал цикл.
"""


def build_dp(storage=None):
    from aiogram import Dispatcher

    from bot import booking, handlers

    kwargs = {"storage": storage} if storage is not None else {}
    dp = Dispatcher(**kwargs)
    dp.include_router(handlers.menu_router)   # 1. кнопки главного меню
    dp.include_router(handlers.cmd_router)    # 2. /команды клиента и админа
    dp.include_router(booking.router)         # 3. FSM-квиз бронирования
    dp.include_router(handlers.router)        # 4. FAQ, эскалация, fallback
    return dp
