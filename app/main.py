import json, logging, os, uuid
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import storage
from .express_pay import (
    BASE_URL, EP_IS_TEST,
    create_card_invoice, get_card_invoice_status, get_qr_code_base64,
    run_startup_test,
)
from .qr import base64_to_png, generate_local_qr
from .schemas import (
    CourseCreate, CourseResponse,
    UserCreate, UserResponse,
    PaymentCreate, PaymentInitResponse, PaymentRecord,
    EP_STATUS_MAP,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR     = os.getenv("DATA_DIR", "/data")
COURSES_FILE = os.path.join(DATA_DIR, "courses.json")


def _ensure_courses_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(COURSES_FILE):
        with open(COURSES_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2, ensure_ascii=False)
        logger.info(f"📄 Создан пустой {COURSES_FILE}.")
    else:
        count = len(storage.get_all_courses(only_active=False))
        logger.info(f"📄 Загружено курсов из courses.json: {count}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Запуск FastAPI-ExpressPay...")
    logger.info(f"   Режим: {'🧪 SANDBOX (тест)' if EP_IS_TEST else '💳 PRODUCTION'}")
    _ensure_courses_file()

    logger.info("🔍 Отправляем тестовый счёт в Express-Pay Sandbox...")
    try:
        res    = await run_startup_test()
        status = "pending" if res["ok"] else "error"
        storage.create_payment({
            "tracking_id":         f"startup-{uuid.uuid4().hex[:10]}",
            "ep_invoice_no":       res.get("invoice_no"),
            "ep_card_invoice_no":  res.get("card_invoice_no"),
            "form_url":            res.get("form_url"),
            "amount":              1.00,
            "description":         "Автоматический тест при запуске",
            "customer_email":      "test@dance-school.by",
            "customer_first_name": "Test",
            "customer_last_name":  "Startup",
            "status":              status,
            "is_test":             True,
            "raw_response":        res.get("raw", {}),
        })
        if res["ok"]:
            logger.info(
                f"✅ Тестовый счёт создан. "
                f"InvoiceNo={res['invoice_no']}  "
                f"CardInvoiceNo={res.get('card_invoice_no')}  "
                f"FormUrl={res.get('form_url') or '(sandbox не возвращает)'}"
            )
        else:
            logger.warning(f"⚠️  Тестовый счёт: ошибка — {res.get('error', res.get('raw'))}")
    except Exception as exc:
        logger.error(f"❌ Ошибка startup test: {exc}")

    yield
    logger.info("🛑 FastAPI-ExpressPay остановлен.")


app = FastAPI(
    title="FastAPI-ExpressPay",
    description=(
        "Backend оплаты курсов танцев — Express-Pay · JSON · QR-коды\n\n"
        "Курсы редактируются в `/data/courses.json`. Изменения применяются мгновенно.\n\n"
        "**Sandbox:** FormUrl всегда пустой — это особенность тестового стенда Express-Pay."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ════════════════════════════════════════════════════════
# COURSES
# ════════════════════════════════════════════════════════

@app.get("/active_courses", response_model=List[CourseResponse], tags=["Подписки"])
def list_courses():
    return storage.get_all_courses()

@app.get("/courses/all/list", response_model=List[CourseResponse], tags=["Подписки"])
def list_all_courses():
    return storage.get_all_courses(only_active=False)

@app.get("/courses/{course_id}", response_model=CourseResponse, tags=["Подписки"])
def get_course(course_id: int):
    c = storage.get_course(course_id)
    if not c: raise HTTPException(404, "Курс не найден")
    return c

@app.post("/courses", response_model=CourseResponse, tags=["Подписки"], status_code=201)
def create_course(body: CourseCreate):
    return storage.create_course(body.model_dump())

@app.patch("/courses/{course_id}", response_model=CourseResponse, tags=["Подписки"])
def update_course(course_id: int, body: CourseCreate):
    u = storage.update_course(course_id, body.model_dump())
    if not u: raise HTTPException(404, "Курс не найден")
    return u

@app.delete("/courses/{course_id}", tags=["Подписки"])
def deactivate_course(course_id: int):
    u = storage.update_course(course_id, {"is_active": False})
    if not u: raise HTTPException(404, "Курс не найден")
    return {"detail": "Курс деактивирован"}

@app.post("/courses/{course_id}/activate", tags=["Подписки"])
def activate_course(course_id: int):
    u = storage.update_course(course_id, {"is_active": True})
    if not u: raise HTTPException(404, "Курс не найден")
    return {"detail": "Курс активирован"}


# ════════════════════════════════════════════════════════
# USERS
# ════════════════════════════════════════════════════════

@app.get("/users", response_model=List[UserResponse], tags=["Пользователи"])
def list_users(): return storage.get_all_users()

@app.get("/users/{user_id}", response_model=UserResponse, tags=["Пользователи"])
def get_user(user_id: int):
    u = storage.get_user(user_id)
    if not u: raise HTTPException(404, "Пользователь не найден")
    return u

@app.post("/users", response_model=UserResponse, tags=["Пользователи"], status_code=201)
def create_user(body: UserCreate):
    ex = storage.get_user_by_email(body.email)
    if ex: return ex
    return storage.create_user(body.model_dump())

@app.get("/users/{user_id}/payments", response_model=List[PaymentRecord], tags=["Пользователи"])
def user_payments(user_id: int):
    if not storage.get_user(user_id): raise HTTPException(404, "Пользователь не найден")
    return storage.get_payments_by_user(user_id)


# ════════════════════════════════════════════════════════
# PAYMENTS
# ════════════════════════════════════════════════════════

@app.post("/payments", response_model=PaymentInitResponse, tags=["Платежи"], status_code=201)
async def create_payment(body: PaymentCreate):
    course = storage.get_course(body.course_id)
    if not course: raise HTTPException(404, "Курс не найден")
    if not course.get("is_active", True): raise HTTPException(400, "Курс неактивен")

    user = storage.upsert_user(
        body.customer_email, body.customer_first_name,
        body.customer_last_name, body.customer_phone,
    )

    tracking_id = f"order-{uuid.uuid4().hex}"
    account_no  = tracking_id[:30]

    try:
        ep_resp = await create_card_invoice(
            account_no=account_no,
            amount=course["price"],
            info=f"Оплата курса: {course['name']}",
            return_url=f"{BASE_URL}/payment/success?tid={tracking_id}",
            fail_url=f"{BASE_URL}/payment/fail?tid={tracking_id}",
        )
    except Exception as exc:
        logger.error(f"Express-Pay error: {exc}")
        raise HTTPException(502, f"Ошибка Express-Pay: {exc}")

    # Express-Pay возвращает два номера — сохраняем оба
    invoice_no      = ep_resp.get("InvoiceNo")
    card_invoice_no = ep_resp.get("CardInvoiceNo")
    form_url        = ep_resp.get("FormUrl") or None  # "" → None

    logger.info(
        f"💳 Счёт создан: InvoiceNo={invoice_no} "
        f"CardInvoiceNo={card_invoice_no} "
        f"FormUrl={form_url or '(sandbox не возвращает)'}"
    )

    payment = storage.create_payment({
        "tracking_id":          tracking_id,
        "ep_invoice_no":        invoice_no,
        "ep_card_invoice_no":   card_invoice_no,
        "form_url":             form_url,
        "course_id":            course["id"],
        "course_name":          course["name"],
        "amount":               course["price"],
        "description":          f"Оплата курса: {course['name']}",
        "user_id":              user["id"],
        "customer_email":       body.customer_email,
        "customer_first_name":  body.customer_first_name,
        "customer_last_name":   body.customer_last_name,
        "is_test":              EP_IS_TEST,
        "raw_response":         ep_resp,
        "qr_generated":         True,
    })

    return PaymentInitResponse(
        id=payment["id"],
        tracking_id=tracking_id,
        ep_invoice_no=invoice_no,
        form_url=form_url or "",
        qr_url=f"{BASE_URL}/payments/{tracking_id}/qr",
        status="pending",
        is_test=EP_IS_TEST,
        amount=course["price"],
        course_name=course["name"],
    )


@app.get(
    "/payments/{tracking_id}/qr",
    tags=["Платежи"],
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "QR-код PNG"}},
)
async def get_payment_qr(tracking_id: str):
    """
    QR-код для оплаты:
    - Реальный платёж (form_url есть) → QR ведёт на страницу оплаты Express-Pay
    - Тестовый / Sandbox (form_url пустой) → QR ведёт на /payment/paid
    """
    payment = storage.get_payment_by_tracking(tracking_id)
    if not payment:
        raise HTTPException(404, "Платёж не найден")

    invoice_no = payment.get("ep_invoice_no")
    form_url   = payment.get("form_url") or ""
    amount     = payment.get("amount", 0)
    is_test    = payment.get("is_test", False)
    label      = f"{payment.get('course_name', 'Курс')} — {amount:.2f} BYN"

    png_bytes = None

    # 1. Пробуем получить официальный QR от Express-Pay
    if invoice_no:
        b64 = await get_qr_code_base64(invoice_no)
        if b64:
            try:
                png_bytes = base64_to_png(b64)
            except Exception as e:
                logger.warning(f"QR base64 decode error: {e}")

    # 2. Fallback
    if not png_bytes:
        if form_url:
            qr_target = form_url
        elif is_test:
            # Sandbox не возвращает FormUrl — QR ведёт на страницу "ОПЛАЧЕНО"
            qr_target = f"{BASE_URL}/payment/paid"
            label     = "Тестовый платёж — ОПЛАЧЕНО"
        else:
            raise HTTPException(
                400,
                f"QR недоступен: платёж не имеет URL оплаты. "
                f"Статус: {payment.get('status')}. Создайте новый платёж."
            )
        png_bytes = generate_local_qr(qr_target, label=label)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="qr_{tracking_id[:16]}.png"'},
    )


@app.get("/payments", response_model=List[PaymentRecord], tags=["Платежи"])
def list_payments(
    is_test: Optional[bool] = None,
    status:  Optional[str]  = None,
    limit:   int             = 50,
):
    payments = storage.get_all_payments()
    if is_test is not None:
        payments = [p for p in payments if p.get("is_test") == is_test]
    if status:
        payments = [p for p in payments if p.get("status") == status]
    payments.sort(key=lambda p: p["id"], reverse=True)
    return payments[:limit]


@app.get("/payments/{tracking_id}", response_model=PaymentRecord, tags=["Платежи"])
def get_payment(tracking_id: str):
    p = storage.get_payment_by_tracking(tracking_id)
    if not p: raise HTTPException(404, "Платёж не найден")
    return p


@app.post("/payments/{tracking_id}/sync", tags=["Платежи"])
async def sync_payment_status(tracking_id: str):
    """
    Принудительно обновить статус платежа из Express-Pay.
    Использует CardInvoiceNo если InvoiceNo не дал результата.
    """
    payment = storage.get_payment_by_tracking(tracking_id)
    if not payment:
        raise HTTPException(404, "Платёж не найден")

    # Пробуем сначала ep_card_invoice_no, потом ep_invoice_no
    invoice_no = payment.get("ep_card_invoice_no") or payment.get("ep_invoice_no")
    if not invoice_no:
        raise HTTPException(400, "Нет номера счёта для запроса статуса")

    try:
        resp = await get_card_invoice_status(invoice_no)
    except Exception as exc:
        raise HTTPException(502, f"Ошибка Express-Pay: {exc}")

    logger.info(f"🔄 Sync {tracking_id}: raw response = {resp}")

    # Проверяем ошибку от Express-Pay
    error = resp.get("Error", {})
    if error:
        error_code = error.get("MsgCode")
        error_msg  = error.get("Msg", "Неизвестная ошибка")

        if error_code == 5000000:
            storage.update_payment(tracking_id, {"status": "expired"})
            return {
                "tracking_id":    tracking_id,
                "ep_status_code": None,
                "status":         "expired",
                "warning":        f"Счёт удалён в Express-Pay: {error_msg}",
            }

        return {
            "tracking_id":    tracking_id,
            "ep_status_code": None,
            "status":         payment["status"],
            "warning":        f"Express-Pay вернул ошибку: {error_msg}",
            "raw_response":   resp,
        }

    # Проверяем оба возможных поля статуса
    ep_code = resp.get("CardInvoiceStatus")
    if ep_code is None:
        ep_code = resp.get("Status")

    if ep_code is None:
        return {
            "tracking_id":    tracking_id,
            "ep_status_code": None,
            "status":         payment["status"],
            "warning":        "Express-Pay не вернул статус",
            "raw_response":   resp,
        }

    ep_code    = int(ep_code)
    new_status = EP_STATUS_MAP.get(ep_code, f"unknown_{ep_code}")
    storage.update_payment(tracking_id, {"status": new_status, "raw_response": resp})
    return {
        "tracking_id":    tracking_id,
        "ep_status_code": ep_code,
        "status":         new_status,
    }


# ════════════════════════════════════════════════════════
# WEBHOOK
# ════════════════════════════════════════════════════════

@app.post("/webhook/expresspay", tags=["Webhook"])
async def expresspay_webhook(request: Request):
    try:
        try:
            body = await request.json()
        except Exception:
            form = await request.form()
            body = dict(form)
    except Exception:
        return JSONResponse({"status": "error"}, status_code=400)

    logger.info(f"📩 Webhook: {json.dumps(body, default=str)[:400]}")
    invoice_no = body.get("InvoiceNo") or body.get("invoiceNo")
    ep_status  = body.get("CardInvoiceStatus") or body.get("Status")

    if invoice_no:
        try: invoice_no = int(invoice_no)
        except (ValueError, TypeError): pass
        payment = storage.get_payment_by_invoice(invoice_no)
        if payment:
            ep_code    = int(ep_status) if ep_status is not None else -1
            new_status = EP_STATUS_MAP.get(ep_code, payment["status"])
            storage.update_payment(payment["tracking_id"], {
                "status": new_status, "webhook_received": True, "raw_response": body,
            })
            logger.info(f"✅ InvoiceNo={invoice_no}: статус → {new_status}")
        else:
            logger.warning(f"⚠️  InvoiceNo={invoice_no} не найден")
    return JSONResponse({"status": "ok"})


# ════════════════════════════════════════════════════════
# СТРАНИЦЫ РЕЗУЛЬТАТА
# ════════════════════════════════════════════════════════

def _page(title, msg, color, extra_html=""):
    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{title}</title></head>
<body style="font-family:sans-serif;text-align:center;padding:40px;background:#f5f5f5">
<div style="max-width:520px;margin:auto;background:#fff;padding:40px;
            border-radius:14px;box-shadow:0 2px 20px #0001">
<h1 style="color:{color}">{title}</h1>
<p style="font-size:18px;color:#444">{msg}</p>
{extra_html}
<br><a href="/docs" style="color:#1976d2">Перейти к API →</a>
</div></body></html>""")


# Картинка "ОПЛАЧЕНО" — загружается из файла если существует, иначе заглушка
_PAID_IMG_PATH = os.path.join(os.path.dirname(__file__), "paid.jpg")
if os.path.exists(_PAID_IMG_PATH):
    import base64 as _b64
    with open(_PAID_IMG_PATH, "rb") as _f:
        _PAID_IMG_B64 = _b64.b64encode(_f.read()).decode()
else:
    _PAID_IMG_B64 = ""


@app.get("/payment/paid", tags=["Результат"], response_class=HTMLResponse)
def payment_paid():
    """Страница ОПЛАЧЕНО — QR тестовых платежей ведёт сюда."""
    img_tag = (
        f'<img src="data:image/jpeg;base64,{_PAID_IMG_B64}" ' +
        'style="max-width:100%;border-radius:10px;margin:16px 0">' 
        if _PAID_IMG_B64 else ""
    )
    return _page("Оплачено ✅", "Платёж успешно проведён!", "#2e7d32", extra_html=img_tag)


@app.get("/payment/success", tags=["Результат"], response_class=HTMLResponse)
def p_success(tid: Optional[str] = None):
    if tid: storage.update_payment(tid, {"status": "successful"})
    return _page("Оплата прошла ✅", "Спасибо! Курс успешно оплачен.", "#2e7d32")

@app.get("/payment/fail", tags=["Результат"], response_class=HTMLResponse)
def p_fail(tid: Optional[str] = None):
    if tid: storage.update_payment(tid, {"status": "declined"})
    return _page("Ошибка оплаты ❌", "Платёж не прошёл. Попробуйте ещё раз.", "#c62828")

@app.get("/payment/cancel", tags=["Результат"], response_class=HTMLResponse)
def p_cancel():
    return _page("Платёж отменён", "Вы отменили оплату.", "#555")


# ════════════════════════════════════════════════════════
# HEALTH
# ════════════════════════════════════════════════════════

@app.get("/health", tags=["Система"])
def health():
    courses  = storage.get_all_courses(only_active=False)
    users    = storage.get_all_users()
    payments = storage.get_all_payments()
    return {
        "status":         "ok",
        "mode":           "sandbox" if EP_IS_TEST else "production",
        "storage":        "json",
        "courses_file":   COURSES_FILE,
        "courses":        len(courses),
        "active_courses": len([c for c in courses if c.get("is_active", True)]),
        "users":          len(users),
        "payments":       len(payments),
        "test_payments":  sum(1 for p in payments if p.get("is_test")),
    }
