from bot.handlers import admin, fallback, request, start

#: порядок важен: fallback подключается последним
routers = [start.router, request.router, admin.router, fallback.router]
