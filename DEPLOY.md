# Деплой booking-bot

Два проверенных варианта: **VPS + Docker** (рекомендуется, работает 24/7
даже если офисный компьютер выключен) и **Windows-автозапуск** (если сервер —
ПК в офисе).

---

## 0. Чек-лист перед любым деплоем

- [ ] Создан файл `.env` (из `.env.example`), заполнены:
      `BOT_TOKEN`, `ADMIN_CHAT_ID`, `ADMIN_USER_IDS`, `TZ` (например `Europe/Moscow`)
- [ ] Токен проверен: `curl https://api.telegram.org/botТОКЕН/getMe` → `"ok":true`
- [ ] У администратора есть уведомления: написать боту `/id`, сверить с `.env`
- [ ] Демо-данные (`DEMO_UNITS`, `DEMO_FAQ` в `db.py`) заменены на ваш фонд и ваш FAQ
- [ ] `OBJECT_NAME` в `.env` — название вашего объекта

---

## Вариант A. VPS + Docker (рекомендуется)

**Сервер:** любой VPS 1 vCPU / 1 ГБ / Ubuntu 22.04–24.04.
Из RU-провайдеров: Timeweb Cloud, Selectel, VK Cloud, Reg.ru.

### A1. Подготовка сервера (один раз, SSH)

```bash
# Ubuntu: установка Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # затем перелогиниться
```

### A2. Загрузка проекта

```bash
# с локальной машины (Windows, PowerShell):
scp -r "C:\Users\wowa0\Desktop\рутина\booking-bot" user@IP_СЕРВЕРА:~/booking-bot
# (или git push в репозиторий и git clone на сервере)
```

На сервере:

```bash
cd ~/booking-bot
cp .env.example .env && nano .env    # заполнить токены
docker compose up -d --build
docker compose logs -f bot           # CTRL+C — просто отвязаться, бот продолжит работать
```

Проверка: `docker compose ps` (status `healthy`), в Telegram бот отвечает на `/start`.

### A3. Обновление кода

```bash
cd ~/booking-bot
# залить новый код (scp/git pull), затем:
docker compose up -d --build
```

Диалоги и заявки не теряются: БД лежит в `./data` (volume).

### A4. Автозапуск

`restart: unless-stopped` в `docker-compose.yml` уже поднимает бота после
ребута сервера и после падения — дополнительно ничего настраивать не нужно.

---

## Вариант B. Windows (ПК/сервер в офисе)

### B1. Первый запуск

```bat
cd /d C:\Users\wowa0\Desktop\рутина\booking-bot
.venv\Scripts\python app.py
```

### B2. Автозагрузка при входе в систему

```bat
schtasks /create /tn "booking-bot" /tr "\"C:\Users\wowa0\Desktop\рутина\booking-bot\start.bat\"" /sc onlogon
```

`start.bat` сам перезапускает бота с паузой 10 сек, если он упал.
Включите в Windows «никогда не спать» (Питание → параметры) — иначе
компьютер «уснет» вместе с ботом.

### B3. Проверка health-endpoint (опционально)

```bat
curl http://localhost:8080/health
```
Должен вернуть `{"status":"ok"}`.

---

## Вариант C. Render.com (облако, без своего сервера)

Ошибка `can't open file '.../main.py'` означает, что Render использует
стартовую команду по умолчанию (`python main.py`). Наша точка входа —
`app.py`, её нужно указать явно (файл `Procfile` в проекте делает это
автоматически).

### C1. Создание сервиса

1. Render Dashboard → **New** → **Worker** (рекомендуется для бота)
   или **Web Service** (если хотите health-страницу).
2. Подключите репозиторий с проектом.
3. **Root Directory** — папка проекта, если репозиторий содержит и его, и
   другие файлы (например `booking-bot`). Если репозиторий — только проект,
   оставьте пустым.
4. **Build Command:** `pip install -r requirements.txt`
5. **Start Command:** `python app.py`
   (с `Procfile` в проекте Render подставит её сам — поле можно оставить пустым)

### C2. Переменные окружения (Environment → Add Environment Variable)

Перенесите из `.env` (значения — свои):

```
BOT_TOKEN=...
ADMIN_CHAT_ID=...
ADMIN_USER_IDS=...
TZ=Europe/Moscow
HEALTH_PORT=10000        # для Web Service; для Worker — 0
DB_PATH=/data/bot.db     # только если подключили Disk (см. C3)
```

`LOG_FILE` на Render оставьте пустым — логи идут в stdout и видны
в «Logs» сервиса.

### C3. Диск для БД (обязательно, иначе данные исчезнут)

Файловая система Render стирается при каждом деплое/перезапуске —
`data/bot.db` (гости, заявки, FSM-состояния) пропадёт. Решение — **Disk**:

1. Service → **Disks** → **Add Disk**: имя `botdata`, размер 1 GB,
   Mount Path `/data`.
2. В переменных окружения: `DB_PATH=/data/bot.db`.

Альтернатива «по-взрослому»: подключить managed PostgreSQL Render
и перенести запросы на `psycopg` (схема в `db.py` совместима).

### C4. Важно про тарифы

- **Free plan** выключает сервисы после простоя и не даёт диски —
  для боевого бота нужен **Starter** (~$7/мес) + платный Disk.
- Web Service на Free засыпает после 15 минут без запросов; периодический
  пинг UptimeRobot не спасает бота от сна воркера — для бота берите Worker.

### C5. Проверка

- Вкладка **Logs**: строки `Бот запускается...` и `Start polling` без ошибок.
- В Telegram: `/start` → бот отвечает.
- Web Service: откроется `{"status":"ok"}` (корень и `/health`).

---

## Мониторинг

| Что | Как |
|---|---|
| Бот жив | **UptimeRobot** (бесплатно) → монитор `http://IP:8080/health`, алерт при таймауте |
| Логи | Docker: `docker compose logs -f bot`; Windows: `LOG_FILE=data/bot.log` в `.env` (ротация 5 МБ × 3) |
| Бизнес-метрики | в Telegram боту: `/metrics` (доля автоответов, конверсия, очередь) |
| Очередь заявок | `/bookings` — не подтверждённые заявки видны сразу |

## Бэкапы

Бизнес-данные — в `data/bot.db` (гости, брони, история, FSM-состояния).

**Linux (cron, раз в сутки):**
```bash
crontab -e
0 4 * * * cp ~/booking-bot/data/bot.db /backup/bot-$(date +\%F).db
```

**Windows (Планировщик задач):**
```bat
robocopy "C:\Users\wowa0\Desktop\рутина\booking-bot\data" "D:\backup\booking-bot" /R:1 /W:1
```

Храните копии минимум за 14 дней (заявки и напоминания живут дольше недели).

## Частые команды

```bash
docker compose up -d          # поднять
docker compose stop           # остановить
docker compose restart        # перезапустить
docker compose logs -f bot    # смотреть лог
docker compose exec bot python -c "print(1)"  # проверить окружение внутри
```

## Что НЕ нужно делать на проде

- Не хранить `.env` в git (уже в `.gitignore`) и не отправлять токен в чаты.
- Не запускать две копии бота одновременно (Telegram отдаёт апдейты одной
  инстанции — вторая будет «голодать»).
- Не держать `data/bot.db` на месте без бэкапа — это клиентская база.
