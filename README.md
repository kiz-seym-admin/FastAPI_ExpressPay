# FastAPI-ExpressPay

> FastAPI · Express-Pay (express-pay.by) · JSON · QR-коды · Docker Compose

---

## Возможности

| Функция | Описание |
|---------|----------|
| **Интернет-эквайринг** | Выставление счёта по карте через Express-Pay API |
| **ЕРИП** | API также поддерживает выставление счетов ЕРИП |
| **QR-код** | Запрашивает QR у Express-Pay, fallback — генерация локально |
| **JSON-хранилище** | Все данные в `/data/*.json` (courses, users, payments) |
| **Webhook** | Принимает уведомления Express-Pay, обновляет payments.json |
| **Sync статуса** | `POST /payments/{id}/sync` — принудительный опрос статуса |
| **Sandbox** | Официальный тестовый стенд Express-Pay с готовым токеном |

---

## Быстрый старт

```bash
unzip FastAPI-ExpressPay.zip
cd FastAPI-ExpressPay
docker compose up --build
```

При запуске автоматически:
1. Создаётся JSON-хранилище в Docker volume (`/data/`)
2. Добавляются 5 тестовых курсов в `courses.json`
3. **Отправляется тестовый счёт** в Express-Pay Sandbox → результат в `payments.json`

**Swagger UI:** http://localhost:8000/docs

---

## Sandbox Express-Pay

У Express-Pay есть **официальный тестовый стенд** с готовым токеном:

| Параметр | Значение |
|----------|----------|
| Sandbox URL | `https://sandbox-api.express-pay.by` |
| Токен | `a75b74cbcfe446509e8ee874f421bd64` |
| Флаг | `EP_IS_TEST=true` в `.env` |

Источник: https://express-pay.by/docs/api/v1#sandbox

---

## Flow оплаты

```
Клиент          FastAPI-ExpressPay       Express-Pay
  │                    │                      │
  │─ POST /payments ──►│                      │
  │                    │─ POST /cardinvoices ─►│
  │                    │◄─ {InvoiceNo, FormUrl}│
  │◄─ {form_url,       │                      │
  │    qr_url} ────────│                      │
  │                    │                      │
  │─ GET /payments/    │                      │
  │  {id}/qr ─────────►│─ GET /qrcode/ ───────►│
  │◄── PNG QR ──────────│◄── base64 ────────────│
  │                    │                      │
  │─ redirect form_url ──────────────────────►│
  │        (страница ввода карты Express-Pay) │
  │◄── redirect /payment/success ─────────────│
  │                    │◄─ POST /webhook ──────│
  │              (payments.json обновлён)      │
```

---

## API Endpoints

### Подписки
| Метод | URL | Описание |
|-------|-----|----------|
| `GET` | `/courses` | Список активных курсов |
| `POST` | `/courses` | Создать курс (`price` в BYN, напр. `80.00`) |
| `PATCH` | `/courses/{id}` | Обновить |
| `DELETE` | `/courses/{id}` | Деактивировать |

### Пользователи
| Метод | URL | Описание |
|-------|-----|----------|
| `GET` | `/users` | Список |
| `POST` | `/users` | Создать/найти по email |
| `GET` | `/users/{id}/payments` | Платежи пользователя |

### Платежи
| Метод | URL | Описание |
|-------|-----|----------|
| `POST` | `/payments` | Инициировать оплату → `form_url` + `qr_url` |
| `GET` | `/payments` | Все платежи (фильтры: `is_test`, `status`) |
| `GET` | `/payments/{tid}` | Платёж по tracking_id |
| `GET` | `/payments/{tid}/qr` | **QR-код PNG** |
| `POST` | `/payments/{tid}/sync` | Обновить статус из Express-Pay |

### Служебные
| Метод | URL | Описание |
|-------|-----|----------|
| `POST` | `/webhook/expresspay` | Webhook уведомления |
| `GET` | `/health` | Статус + статистика |

---

## Статусы платежей Express-Pay

| Код | Статус в системе | Значение |
|-----|-----------------|----------|
| 0 | `pending` | Зарегистрирован, не оплачен |
| 2 | `successful` | Оплачен ✅ |
| 3 | `cancelled` | Отменён |
| 4 | `refunded` | Возврат |
| 6 | `declined` | Отклонён банком |

---

## Настройка webhook в кабинете Express-Pay

1. Войдите в https://client.express-pay.by
2. Настройки → Услуги → API → **URL уведомлений**
3. Установите: `https://your-domain.com/webhook/expresspay`

При локальной разработке используйте ngrok:
```bash
ngrok http 8000
# HTTPS-адрес → BASE_URL в .env и URL уведомлений в кабинете
```

---

## Продакшн

1. Зарегистрируйтесь на https://express-pay.by/join
2. Получите токен и секретное слово в личном кабинете
3. Обновите `.env`:
```env
EP_TOKEN=ваш_токен
EP_SECRET_WORD=ваше_секретное_слово
EP_IS_TEST=false
BASE_URL=https://your-domain.com
```

---

## Структура проекта

```
FastAPI-ExpressPay/
├── app/
│   ├── __init__.py
│   ├── main.py           ← роуты, lifespan, startup-тест
│   ├── storage.py        ← JSON-хранилище
│   ├── express_pay.py    ← интеграция с Express-Pay API
│   ├── qr.py             ← QR (Express-Pay base64 + локальный fallback)
│   └── schemas.py        ← Pydantic-схемы, маппинг статусов
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```
