# Мятный Планер

Рандомный планер питания по настроению с расчётом БЖУ, автоматическим списком покупок,
учётом цен и прогнозированием расходов. FastAPI + SQLite + Jinja2 + Alpine.js.
Пастельно-розовый дизайн.

## Основные возможности

- **Рандомный планер меню на месяц** с учётом настроения (уютное/бодрящее/лёгкое/сытное/острое/сладкое/праздничное)
- **5 приёмов пищи в день:** завтрак, обед, полдник, ужин, поздник. Порции настраиваются отдельно на каждый
- **Десерты** — системная база + возможность добавить свои, раскидываются по неделям автоматически
- **Расчёт БЖУ** всех блюд на основе ингредиентов, фильтр по целевой калорийности
- **Исключения продуктов** — аллергии и нелюбимые ингредиенты, планер их учитывает
- **Автоматический список покупок** — разбит по неделям и на весь месяц, с чекбоксами
- **Учёт цен** — вводятся по факту покупки, сохраняются в истории
- **Прогноз стоимости** будущего плана на основе истории цен
- **Разграничение прав:** админ/пользователь, с возможностью самостоятельной регистрации
- **Admin-панель:** управление пользователями, ролями, ингредиентами, рецептами, аудит-лог

## Безопасность

Реализовано сразу:

- Пароли: `bcrypt` cost=12
- JWT access (15 мин) + refresh (7 дней) в httpOnly + Secure + SameSite=Strict cookies
- CSRF токены на всех формах через `fastapi-csrf-protect`
- Rate limiting (`slowapi`): 5/мин на `/login`, 3/мин на `/register`
- Блокировка аккаунта на 15 мин после 10 неудачных попыток входа
- SQL-инъекции невозможны: только SQLAlchemy ORM с параметризованными запросами
- XSS защита: Jinja2 autoescape + `Content-Security-Policy` заголовок
- Clickjacking защита: `X-Frame-Options: DENY`
- HSTS, X-Content-Type-Options, Referrer-Policy
- Валидация всего ввода через Pydantic схемы
- Аудит-лог: попытки входа, смены ролей, изменения админ-состояния
- Owner-check на всех пользовательских ресурсах (защита от IDOR)
- Секреты только через переменные окружения, никаких хардкод-ключей
- SQLite в режиме WAL + включённые foreign keys

## Локальный запуск

```bash
# 1. Клонируй репо и зайди в папку
cd planner

# 2. (рекомендуется) venv
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

# 3. Установи зависимости
pip install -r requirements.txt

# 4. Скопируй .env.example в .env и задай секреты
cp .env.example .env
# Сгенерируй SECRET_KEY и CSRF_SECRET_KEY:
python -c "import secrets; print(secrets.token_urlsafe(64))"
# и вставь эти значения в .env

# 5. Загрузи стартовые данные (95 рецептов + 111 ингредиентов)
python -m scripts.seed

# 6. Запуск
uvicorn app.main:app --reload
```

Открой http://localhost:8000.
Первый пользователь, зарегистрировавшийся с email из `INITIAL_ADMIN_EMAIL`, получит роль администратора автоматически.

## Деплой на Render.com

### Вариант 1 — автодеплой через render.yaml (рекомендую)

1. Залей проект в GitHub.
2. В Render.com → New → Blueprint → подключи свой репозиторий.
3. Render прочитает `render.yaml` и создаст:
   - **Web Service** (pastel-planner) на Python
   - **Persistent Disk** на 1 GB, монтируется в `/var/data` — туда пишется SQLite
   - Автоматически сгенерированные `SECRET_KEY` и `CSRF_SECRET_KEY`
4. В дашборде Render вручную задай `INITIAL_ADMIN_EMAIL` — это email, который при регистрации сразу получит админскую роль.
5. Render запустит:
   - Build: `pip install -r requirements.txt && python -m scripts.seed`
   - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers ...`
6. Жди здоровья на `/healthz` — и сервис в бою.

### Вариант 2 — ручной Web Service

1. New → Web Service → подключи репо.
2. Runtime: Python 3.12
3. Build Command: `pip install -r requirements.txt && python -m scripts.seed`
4. Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'`
5. Health Check Path: `/healthz`
6. Добавь Persistent Disk: mount `/var/data`, size 1 GB
7. Env vars:
   - `DEBUG=false`
   - `COOKIE_SECURE=true`
   - `DATABASE_URL=sqlite:////var/data/planner.db` (четыре слеша!)
   - `SECRET_KEY=<сгенерируй>`
   - `CSRF_SECRET_KEY=<сгенерируй>`
   - `INITIAL_ADMIN_EMAIL=<твой email>`

### Важно про деплой

- **Persistent disk обязателен**, иначе SQLite сбросится при перезапуске. На Render это платная опция (~$1/мес за 1 GB), но это дешевле PostgreSQL ($7/мес).
- **Бэкапы**: делай через `sqlite3 /var/data/planner.db ".backup /var/data/backup.db"` по крону, или Render Cron Job на ежедневный дамп в S3/Dropbox.
- **Масштабирование**: SQLite на одном инстансе. Если нагрузка вырастет — переходи на PostgreSQL (в `app/database.py` код уже готов).

## Структура проекта

```
planner/
├── app/
│   ├── main.py              # FastAPI, регистрация роутов, middleware
│   ├── config.py            # Настройки через env
│   ├── database.py          # SQLAlchemy + SQLite с WAL
│   ├── models.py            # 10 моделей БД
│   ├── schemas.py           # Pydantic валидация
│   ├── auth.py              # bcrypt, JWT, роли, audit
│   ├── security.py          # CSP, HSTS, CSRF
│   ├── ratelimit.py         # slowapi
│   ├── routes/              # auth, planner, shopping, desserts, exclusions, prices, admin
│   ├── services/            # nutrition.py, menu_generator.py, shopping_list.py
│   ├── parsers/             # (заглушка под парсеры для расширения базы)
│   ├── templates/           # Jinja2 + пастельно-розовая тема
│   └── static/css/main.css  # дизайн-система
├── data/
│   ├── seed_ingredients.json          # 111 ингредиентов
│   ├── seed_recipes_breakfast.json    # 20 завтраков
│   ├── seed_recipes_lunch.json        # 25 обедов
│   ├── seed_recipes_dinner.json       # 20 ужинов
│   └── seed_recipes_snacks_desserts.json  # 30 перекусов+десертов
├── scripts/
│   └── seed.py              # загрузка стартовых данных
├── requirements.txt
├── render.yaml              # конфиг Render.com
├── .env.example
└── README.md
```

## Дополнение базы до 500+ рецептов

В seed сейчас 95 рецептов с выверенным БЖУ. Чтобы расширить:

### Способ 1 — ручное добавление через админку
`/admin/recipes` → форма добавления рецепта. Появляется сразу для всех пользователей.

### Способ 2 — массовый импорт через JSON
Формат такой же, как в `data/seed_recipes_*.json`. Добавь свой файл в `data/`, добавь путь в `scripts/seed.py` → `RECIPE_FILES`, запусти `python -m scripts.seed`. Seed идемпотентен — дубликаты не создаёт.

### Способ 3 — парсеры
Каркас в `app/parsers/` готов, адаптеры (povarenok.ru, eda.ru) не написаны — это отдельный проект из-за защиты от ботов и кривого БЖУ на исходниках. Когда напишешь — можно запускать как админ-скрипт на том же сервере.

## Стек

- **Бекенд:** Python 3.12, FastAPI, SQLAlchemy 2.0, SQLite (WAL)
- **Фронт:** Jinja2, Alpine.js 3.x, нативный CSS (без сборщиков)
- **Auth:** bcrypt, python-jose (JWT), httpOnly cookies
- **Защита:** fastapi-csrf-protect, slowapi, кастомный middleware для CSP/HSTS
- **Валидация:** Pydantic 2.9
- **Шрифты:** Cormorant Garamond (display) + DM Sans (body) через Google Fonts
- **Деплой:** Render.com Web Service + Persistent Disk

## Лицензия

Твой проект — делай что хочешь.
