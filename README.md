# Matrix LiveKit Bot

Полностью асинхронный сервис на Python, который интегрирует Matrix Bot с LiveKit для записи звонков.

## Возможности

- 🤖 **Matrix Bot** - слушает команды в Matrix комнатах
- 🎥 **LiveKit Integration** - управление записью звонков через LiveKit Egress API
- 💾 **PostgreSQL** - сохранение метаданных записей
- 🔔 **Webhooks** - обработка событий от LiveKit (egress_ended)
- 🏗️ **Clean Architecture** - модульная структура с разделением на слои
- ⚡ **Async/Await** - полностью асинхронный код

## Структура проекта

```
matrix-livekit-bot/
├── bot/                    # Matrix bot модуль
│   ├── config.py          # Конфигурация бота
│   ├── matrix_client.py   # Matrix клиент
│   ├── event_handler.py   # Обработка событий Matrix
│   ├── commands.py        # Обработка команд
│   ├── livekit_controller.py  # Управление LiveKit
│   └── mapper.py          # Маппинг данных
│
├── server/                # FastAPI сервер
│   ├── main.py           # Точка входа сервера
│   ├── db.py             # Настройка БД
│   ├── models/           # SQLAlchemy модели
│   ├── repositories/     # Репозитории (data access)
│   ├── crud/             # CRUD операции
│   └── routes/           # API маршруты
│
├── alembic/              # Миграции БД
│   └── versions/
│
└── config/               # Конфигурационные файлы
```

## Установка

### Требования

- Python 3.10+
- PostgreSQL 15+
- LiveKit сервер с настроенным Egress

### 1. Клонирование и установка зависимостей

```bash
# Создать виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows

# Установить зависимости
pip install -r requirements.txt
```

### 2. Настройка окружения

Создайте файл `.env` в корне проекта со следующим содержимым:

```bash
# Создайте .env файл
touch .env
```

Отредактируйте `.env` и добавьте:

```env
# Matrix Configuration
MATRIX_HOMESERVER=https://matrix.org
MATRIX_USER_ID=@bot:matrix.org
MATRIX_ACCESS_TOKEN=your_access_token_here
MATRIX_DEVICE_ID=DEVICE_ID

# LiveKit Configuration
LIVEKIT_URL=https://your-livekit-server.com
LIVEKIT_API_KEY=your_api_key
LIVEKIT_API_SECRET=your_api_secret

# Database Configuration
DATABASE_URL=postgresql+asyncpg://matrix_bot:matrix_bot_password@localhost:5432/matrix_livekit_bot

# Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
WEBHOOK_SECRET=your_webhook_secret_here
```

### 3. Запуск PostgreSQL

```bash
docker-compose up -d postgres
```

### 4. Применение миграций

```bash
alembic upgrade head
```

### 5. Настройка LiveKit Webhook

Настройте webhook в вашем LiveKit сервере, чтобы отправлять события на:
```
http://your-server:8000/webhook/livekit/egress
```

## Использование

### Запуск Matrix Bot

```bash
python main.py
```

Бот подключится к Matrix и начнет слушать команды в комнатах.

### Запуск API сервера

```bash
python -m server.main
```

Или через uvicorn:

```bash
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

### Команды бота

В Matrix комнате отправьте:

- `/record start [room_name]` - начать запись LiveKit комнаты
- `/record stop [room_name]` - остановить запись
- `/help` - показать справку

Пример:
```
/record start my-room
```

## API Endpoints

### Webhook (LiveKit → Bot)

```
POST /webhook/livekit/egress
```

Принимает события от LiveKit:
- `egress_started` - запись началась
- `egress_updated` - обновление статуса
- `egress_ended` - запись завершена

### Health Check

```
GET /webhook/health
```

## Архитектура

Проект следует принципам Clean Architecture:

1. **Bot Layer** (`bot/`) - бизнес-логика бота
2. **Server Layer** (`server/`) - API сервер и работа с БД
3. **Data Layer** - репозитории и модели
4. **Infrastructure** - конфигурация, миграции

### Поток данных

1. Пользователь отправляет команду в Matrix → `commands.py`
2. Команда обрабатывается → `livekit_controller.py` запускает запись
3. LiveKit отправляет webhook → `routes/webhook_livekit.py`
4. Метаданные сохраняются → `repositories/recordings_repository.py`

## Расширение функциональности

### Добавление MinIO для хранения файлов

1. Добавьте MinIO клиент в `requirements.txt`
2. Создайте сервис для загрузки файлов
3. Обновите webhook handler для загрузки файлов

### Добавление транскрипции

1. Интегрируйте сервис транскрипции (Whisper, AssemblyAI и т.д.)
2. Добавьте обработку после получения файла
3. Сохраните транскрипцию в БД

### Добавление уведомлений в Matrix

1. Расширьте `event_handler.py`
2. Отправляйте уведомления о завершении записи

## Разработка

### Запуск тестов

```bash
# TODO: добавить тесты
pytest
```

### Создание миграций

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
```

### Линтинг

```bash
# TODO: добавить линтеры
black .
ruff check .
```

## Docker

Запуск всех сервисов:

```bash
docker-compose up -d
```

## Лицензия

MIT

## Автор

Matrix LiveKit Bot

