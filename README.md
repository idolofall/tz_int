# Generation service

Сервис принимает заказ на генерацию, списывает токены, отдаёт задачу провайдеру и при отказе идёт к следующей ноге. Если ноги кончились — возвращает токены. Каждое движение денег происходит ровно один раз.

Инварианты живут в Postgres, не в памяти процесса: сервис стартует в 4 воркерах.

## Проверка за две минуты

Нужны Docker и Python 3.11+.

```bash
docker compose up --build -d
```

Подожди, пока `http://localhost:8000/health` ответит `{"status":"ok"}`. Поднимаются PostgreSQL, сервис на `:8000` (4 воркера) и провайдеры `alpha` (`:8001`), `beta` (`:8002`). Миграции накатываются при старте `app`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

`pytest` сам стек не поднимает. Интеграционные тесты бьют в уже запущенный compose. Юнит-тесты правил ног ходят без Docker.

Обязательные сценарии из задания:

| Тест | Что доказывает |
|---|---|
| `test_twenty_identical_payment_webhooks_credit_once` | 20 одинаковых оплат → одна строка журнала, баланс `+N` один раз |
| `test_ten_concurrent_last_leg_failures_refund_once` | 10 одновременных `failed` на последней ноге → один возврат |
| `test_first_leg_failure_completes_on_second` | отказ первой ноги, успех второй, в истории две попытки |
| `test_late_completed_after_watchdog_does_not_pay_and_deliver` | поздний `completed` после сторожа: нет и файла, и второго возврата |

Последний тест ждёт `PROVIDER_TIMEOUT` (60 секунд), прогон около минуты.

Смотреть деньги: `GET /users/{id}/balance` — `balance` равен сумме `journal`.

## Миграции

Схема и стартовый каталог моделей — в Alembic.

```bash
alembic upgrade head
alembic revision -m "add_something"
# правите alembic/versions/..., затем снова upgrade head
```

В Docker: `docker compose exec app alembic upgrade head`.

| Модель        | Цена | Ноги                                      |
|---------------|------|-------------------------------------------|
| `image-fast`  | 2    | alpha ≤4 референса → beta ≤10             |
| `video-long`  | 25   | beta ≤2 → alpha ≤1, `skip_on_moderation`  |

## API

- `POST /generate` — `{user_id, model_slug, prompt, ref_images}` → `{task_id}`. Нет подходящей ноги — 400 до списания. Нет токенов — 402. Уже 3 активные задачи — 429.
- `POST /webhooks/providers/{name}` — результат провайдера, `X-Signature` = HMAC-SHA256 сырого тела.
- `POST /webhooks/payments` — `{payment_id, user_id, tokens, status}`, та же подпись. Учитывается `completed` / `success` / `paid`.
- `GET /tasks/{id}` — статус, текущая нога, история попыток.
- `GET /users/{id}/balance` — сумма журнала и последние строки.

Пользователь создаётся первой операцией. Регистрации нет. Секрет подписи: `WEBHOOK_SECRET` (в compose — `dev-webhook-secret`).

Фейковые провайдеры: `POST /tasks` → `202 {"external_id"}`. Для тестов: `POST /__test__/behavior` на `:8001` / `:8002` (`fail_rate`, `sync_error`, `double_webhook`, `no_webhook`, `late_completed`). Это тестовый контур, не продуктовый API.

Локально без полного compose: поднять postgres, `cp .env.example .env`, `alembic upgrade head`, `uvicorn generation.main:app --reload --app-dir src`.

## Почему «ровно один раз»

Журнал — единственный источник баланса. У строки уникальность `(kind, reference_id)`:

- оплата: `kind=payment`, `reference_id=payment_id`
- списание: `kind=debit`, `reference_id=task_id`
- возврат: `kind=refund`, `reference_id=task_id`

Вставка: `INSERT ... ON CONFLICT DO NOTHING`. Двадцать одинаковых оплат или десять `failed` на последней ноге дают одну строку.

Возврат равен модулю исходного списания этой задачи, не текущей цене в каталоге.

Попытка закрывается CAS: `UPDATE task_attempts SET status=... WHERE id=? AND status='sent'`. Победитель один. Дубль вебхука и опоздавший сторож в журнал не пишут.

Сторож в каждом из 4 процессов берёт просроченные `sent` через `FOR UPDATE SKIP LOCKED`. Состояние после рестарта — только строки Postgres.

## Падение процесса посреди вебхука

Одно событие — одна транзакция: CAS попытки, журнал, статус задачи, при необходимости следующая попытка.

- Упал до `COMMIT` — в базе ничего нет. Повтор вебхука проходит заново.
- Упал после `COMMIT`, до вызова следующей ноги — попытка уже `sent` с `timeout_at`. Сторож или повтор продолжат маршрут.
- Упал после вставки возврата — `(refund, task_id)` вторую строку не даст.

Баланс всегда равен сумме журнала.

## Правило 6: поздний `completed`

Если сторож уже закрыл попытку и на последней ноге вернул токены, поздний `completed` игнорируется. Задача остаётся `failed`, `result_url` не ставится, второй возврат не пишется.

Почему не «принять файл и отменить возврат»:

1. Иначе пользователь получает и результат, и токены.
2. Сторно возврата — ещё одно денежное событие и снова гонки.
3. CAS уже решил, кто успел первым. Поздний успех провайдера не переигрывает таймаут.

Цена: редкий файл после таймаута отбрасывается. Для этого контура это правильнее дыры в деньгах. Отдать файл без повторного списания — отдельный продуктный сценарий, его нельзя смешивать с возвратом.

## Архитектура

```
src/generation/
  domain/          правила ног и ошибки, без IO
  application/     журнал, workflow, сторож
  infrastructure/  Postgres, HMAC, HTTP-клиент провайдеров
  api/             FastAPI
src/providers/     alpha и beta, один код, разный PROVIDER_NAME
```

Стек: Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, PostgreSQL 16. Линтер: `ruff`.

## Что не входит

Регистрация, UI, настоящее хранилище файлов, настоящие деньги. Результат генерации — строка-ссылка.
