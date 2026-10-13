"""HTTP /health — для мониторинга (UptimeRobot) и Docker healthcheck.

Отдаёт 200 OK, пока процесс жив; падение бота → мониторинг шлёт алерт.
"""
import logging

from aiohttp import web

log = logging.getLogger("health")


async def run_health_server(port: int) -> None:
    async def ok(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_get("/health", ok)
    app.router.add_get("/", ok)  # Render по умолчанию проверяет корень сайта
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Health-check включён: http://0.0.0.0:%s/health", port)
