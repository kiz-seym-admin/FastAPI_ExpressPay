# FastAPI-ExpressPay fixed

Исправленная версия проекта с унифицированными именами полей, защитой от падений в `POST /payments`, синхронизацией курсов из `courses.json` в MySQL и миграциями старых snake/camel колонок.

## Что исправлено

- Приведены к одному стилю поля Pydantic, ORM и endpoint-ов: `course_id`, `customer_email`, `order_num`, `user_id`, `subscription_id`, `is_test`.
- В `POST /payments` добавлены проверки ответа Express-Pay и нормальное сообщение 502 вместо 500.
- Исправлена миграция курсов: теперь существующие записи в `subscriptions` обновляются, а не только добавляются.
- Добавлены миграции переименования старых колонок в `users` и `purchases`.
- Убраны типовые причины `ResponseValidationError` из-за несовпадения response model.

## Запуск

```bash
docker compose up --build
```

## Тест payload

```json
{
  "course_id": 2,
  "customer_email": "igor.k@joblio.co"
}
```
