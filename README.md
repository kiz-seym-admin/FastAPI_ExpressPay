# FastAPI-ExpressPay

> FastAPI · Express-Pay (express-pay.by) · MySQL · QR-коды · Docker Compose

---

## Возможности

| Функция | Описание |
|---------|----------|
| **Интернет-эквайринг** | Выставление счёта по карте через Express-Pay API |
| **QR-код** | Запрашивает QR у Express-Pay, fallback — генерация локально |
| **MySQL БД** | Users, Subscriptions, Purchases, Promocodes, Dealers, Commissions |
| **Webhook** | Принимает уведомления Express-Pay, обновляет статус платежей |
| **Sync статуса** | `POST /payments/{id}/sync` — принудительный опрос статуса |
| **Sandbox** | Официальный тестовый стенд Express-Pay с готовым токеном |

---

## Быстрый старт

```bash
docker compose up --build
```

**Swagger UI:** http://localhost:8000/docs

---

## Структура БД

| Таблица | Описание |
|---------|----------|
| `users` | Пользователи: email, промокод, телефон, имя, статус, пароль, dealer |
| `subscriptions` | Подписки: название, описание, цена, длительность, статус |
| `purchases` | Покупки: заказ Express-Pay, пользователь/дилер, комиссия, URL, даты |
| `promocodes` | Промокоды: название, статус, процент комиссии |
| `dealers` | Дилеры: ссылка на user, процент, накопленная сумма |
| `commissions` | Справочник процентов комиссии |

---

## Sandbox Express-Pay

| Параметр | Значение |
|----------|----------|
| Sandbox URL | `https://sandbox-api.express-pay.by` |
| Токен | `a75b74cbcfe446509e8ee874f421bd64` |
| Флаг | `EP_IS_TEST=true` в `.env` |
