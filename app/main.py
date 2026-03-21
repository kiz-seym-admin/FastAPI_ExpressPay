import json, logging, os, uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from . import storage
from .database import init_db, get_db, User, Payment, calc_expired_at
from .express_pay import (
    BASE_URL, EP_IS_TEST,
    create_card_invoice, get_card_invoice_status,
    get_qr_code_base64, run_startup_test,
)
from .qr import base64_to_png, generate_local_qr
from .schemas import (
    CourseCreate, CourseResponse,
    UserCreate, UserResponse,
    UserWithPayments,
    PaymentCreate, PaymentInitResponse, PaymentRecord,
    EP_STATUS_MAP,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "/data")
COURSES_FILE = os.path.join(DATA_DIR, "courses.json")


def _ensure_courses_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(COURSES_FILE):
        with open(COURSES_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2, ensure_ascii=False)
        logger.info(f"📄 Создан пустой {COURSES_FILE}.")
    else:
        logger.info(f"📄 Загружено курсов: {len(storage.get_all_courses(only_active=False))}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Запуск FastAPI-ExpressPay...")
    logger.info(f"   Режим: {'🧪 SANDBOX' if EP_IS_TEST else '💳 PRODUCTION'}")
    _ensure_courses_file()
    await init_db()
    logger.info("✅ MySQL БД инициализирована.")
    try:
        res = await run_startup_test()
        if res["ok"]:
            logger.info(f"✅ Тестовый счёт: InvoiceNo={res['invoice_no']} FormUrl={res.get('form_url') or '(sandbox)'}")
        else:
            logger.warning(f"⚠️ Тестовый счёт: {res.get('error', res.get('raw'))}")
    except Exception as exc:
        logger.error(f"❌ Startup test: {exc}")
    yield
    logger.info("🛑 Остановлен.")


app = FastAPI(
    title="FastAPI-ExpressPay",
    description="Backend оплаты курсов — Express-Pay · MySQL · QR-коды",
    version="3.0.0",
    lifespan=lifespan,
)


# ════════════════════════════════════════════════════════
# HEALTH
# ════════════════════════════════════════════════════════

@app.get("/health", tags=["Служебные"])
async def health(db: AsyncSession = Depends(get_db)):
    users = (await db.execute(select(User))).scalars().all()
    payments = (await db.execute(select(Payment))).scalars().all()
    return {
        "status": "ok",
        "mode": "sandbox" if EP_IS_TEST else "production",
        "users": len(users),
        "payments": len(payments),
        "courses": len(storage.get_all_courses(only_active=False)),
    }


# ════════════════════════════════════════════════════════
# COURSES (JSON)
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
    if not storage.update_course(course_id, {"is_active": False}):
        raise HTTPException(404, "Курс не найден")
    return {"detail": "Курс деактивирован"}

@app.post("/courses/{course_id}/activate", tags=["Подписки"])
def activate_course(course_id: int):
    if not storage.update_course(course_id, {"is_active": True}):
        raise HTTPException(404, "Курс не найден")
    return {"detail": "Курс активирован"}


# ════════════════════════════════════════════════════════
# USERS (MySQL)
# ════════════════════════════════════════════════════════

@app.get("/users", response_model=List[UserResponse], tags=["Пользователи"])
async def list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User))
    return result.scalars().all()

@app.get("/users/{user_id}", response_model=UserResponse, tags=["Пользователи"])
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user: raise HTTPException(404, "Пользователь не найден")
    return user

@app.post("/users", response_model=UserResponse, tags=["Пользователи"], status_code=201)
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    existing = result.scalar_one_or_none()
    if existing: return existing
    user = User(email=body.email.lower(), first_name=body.first_name,
                last_name=body.last_name, phone=body.phone)
    db.add(user); await db.commit(); await db.refresh(user)
    return user

@app.get("/users/{user_id}/payments", response_model=UserWithPayments, tags=["Пользователи"])
async def user_payments(user_id: int, db: AsyncSession = Depends(get_db)):
    """Все когда-либо совершённые покупки пользователя (через FK UserID)."""
    user = await db.get(User, user_id)
    if not user: raise HTTPException(404, "Пользователь не найден")
    return user


# ════════════════════════════════════════════════════════
# PAYMENTS (MySQL + ExpressPay)
# ════════════════════════════════════════════════════════

@app.post("/payments", response_model=PaymentInitResponse, tags=["Платежи"], status_code=201)
async def create_payment(body: PaymentCreate, db: AsyncSession = Depends(get_db)):
    course = storage.get_course(body.course_id)
    if not course: raise HTTPException(404, "Курс не найден")
    if not course.get("is_active", True): raise HTTPException(400, "Курс неактивен")

    # upsert пользователя
    result = await db.execute(select(User).where(User.email == body.customer_email.lower()))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email=body.customer_email.lower(), first_name=body.customer_first_name,
                    last_name=body.customer_last_name, phone=body.customer_phone)
        db.add(user); await db.flush()

    tracking_id = f"order-{uuid.uuid4().hex}"

    try:
        ep_resp = await create_card_invoice(
            account_no=tracking_id[:30],
            amount=course["price"],
            info=f"Оплата курса: {course['name']}",
            return_url=f"{BASE_URL}/payment/success?tid={tracking_id}",
            fail_url=f"{BASE_URL}/payment/fail?tid={tracking_id}",
        )
    except Exception as exc:
        logger.error(f"Express-Pay error: {exc}")
        raise HTTPException(502, f"Ошибка Express-Pay: {exc}")

    # Данные из ответа Express-Pay
    invoice_no    = ep_resp.get("InvoiceNo")       # OrderNum
    form_url      = ep_resp.get("FormUrl") or None  # URL оплаты
    duration_weeks = course.get("duration_weeks")

    logger.info(f"💳 InvoiceNo={invoice_no} FormUrl={form_url or '(sandbox)'}")

    payment = Payment(
        OrderNum=str(invoice_no or tracking_id),
        UserID=user.UserID,
        SubscriptionID=body.course_id,
        FormURL=form_url,
        Status="pending",
        expired_at=calc_expired_at(duration_weeks),
    )
    db.add(payment); await db.commit(); await db.refresh(payment)

    return PaymentInitResponse(
        PaymentID=payment.PaymentID,
        OrderNum=payment.OrderNum,
        FormURL=form_url or "",
        qr_url=f"{BASE_URL}/payments/{payment.OrderNum}/qr",
        Status="pending",
        is_test=EP_IS_TEST,
        amount=course["price"],
        course_name=course["name"],
    )


@app.get("/payments/{order_num}/qr", tags=["Платежи"], response_class=Response,
         responses={200: {"content": {"image/png": {}}}})
async def get_payment_qr(order_num: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Payment).where(Payment.OrderNum == order_num))
    payment = result.scalar_one_or_none()
    if not payment: raise HTTPException(404, "Платёж не найден")

    form_url = payment.FormURL or ""
    label = f"Подписка #{payment.SubscriptionID} — {payment.Status}"
    png_bytes = None

    try:
        invoice_int = int(payment.OrderNum)
        b64 = await get_qr_code_base64(invoice_int)
        if b64: png_bytes = base64_to_png(b64)
    except Exception: pass

    if not png_bytes:
        qr_target = form_url if form_url else f"{BASE_URL}/payment/paid"
        if not form_url: label = "Тестовый платёж — ОПЛАЧЕНО"
        png_bytes = generate_local_qr(qr_target, label=label)

    return Response(content=png_bytes, media_type="image/png",
                    headers={"Content-Disposition": f'attachment; filename="qr_{order_num[:16]}.png"'})


@app.get("/payments", response_model=List[PaymentRecord], tags=["Платежи"])
async def list_payments(
    status: Optional[str] = None, limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    q = select(Payment)
    if status: q = q.where(Payment.Status == status)
    q = q.order_by(Payment.PaymentID.desc()).limit(limit)
    return (await db.execute(q)).scalars().all()


@app.get("/payments/{order_num}", response_model=PaymentRecord, tags=["Платежи"])
async def get_payment(order_num: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Payment).where(Payment.OrderNum == order_num))
    payment = result.scalar_one_or_none()
    if not payment: raise HTTPException(404, "Платёж не найден")
    return payment


@app.post("/payments/{order_num}/sync", tags=["Платежи"])
async def sync_payment_status(order_num: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Payment).where(Payment.OrderNum == order_num))
    payment = result.scalar_one_or_none()
    if not payment: raise HTTPException(404, "Платёж не найден")

    try:
        invoice_int = int(order_num)
    except ValueError:
        raise HTTPException(400, "OrderNum не является числом InvoiceNo — sync невозможен")

    try:
        resp = await get_card_invoice_status(invoice_int)
    except Exception as exc:
        raise HTTPException(502, f"Ошибка Express-Pay: {exc}")

    error = resp.get("Error", {})
    if error:
        msg = error.get("Msg", "Неизвестная ошибка")
        if error.get("MsgCode") == 5000000:
            payment.Status = "expired"; await db.commit()
            return {"OrderNum": order_num, "Status": "expired", "warning": msg}
        return {"OrderNum": order_num, "Status": payment.Status, "warning": msg}

    ep_code = resp.get("CardInvoiceStatus") or resp.get("Status")
    if ep_code is None:
        return {"OrderNum": order_num, "Status": payment.Status, "warning": "EP не вернул статус"}

    new_status = EP_STATUS_MAP.get(int(ep_code), f"unknown_{ep_code}")
    payment.Status = new_status
    payment.updated_at = datetime.now()
    await db.commit()
    return {"OrderNum": order_num, "ep_code": int(ep_code), "Status": new_status}


# ════════════════════════════════════════════════════════
# WEBHOOK
# ════════════════════════════════════════════════════════

@app.post("/webhook/expresspay", tags=["Webhook"])
async def expresspay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        try: body = await request.json()
        except Exception:
            form = await request.form(); body = dict(form)
    except Exception:
        return JSONResponse({"status": "error"}, status_code=400)

    logger.info(f"📩 Webhook: {json.dumps(body, default=str)[:400]}")

    invoice_no = body.get("InvoiceNo") or body.get("invoiceNo")
    ep_status  = body.get("CardInvoiceStatus") or body.get("Status")

    if invoice_no:
        result = await db.execute(select(Payment).where(Payment.OrderNum == str(invoice_no)))
        payment = result.scalar_one_or_none()
        if payment:
            ep_code = int(ep_status) if ep_status is not None else -1
            payment.Status = EP_STATUS_MAP.get(ep_code, payment.Status)
            await db.commit()
            logger.info(f"✅ InvoiceNo={invoice_no} → {payment.Status}")
        else:
            logger.warning(f"⚠️ InvoiceNo={invoice_no} не найден")

    return JSONResponse({"status": "ok"})


# ════════════════════════════════════════════════════════
# СТРАНИЦЫ РЕЗУЛЬТАТА
# ════════════════════════════════════════════════════════

def _page(title, msg, color, extra=""):
    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px">
<h1 style="color:{color}">{msg}</h1>{extra}</body></html>""")

@app.get("/payment/success", response_class=HTMLResponse, tags=["Страницы"])
def payment_success(): return _page("Оплата", "✅ Оплата прошла успешно!", "green")

@app.get("/payment/fail", response_class=HTMLResponse, tags=["Страницы"])
def payment_fail(): return _page("Ошибка", "❌ Оплата не выполнена", "red")

@app.get("/payment/paid", response_class=HTMLResponse, tags=["Страницы"])
def payment_paid(): return _page("Тест", "✅ Тестовый платёж — ОПЛАЧЕНО", "green",
                                  "<p style='color:gray'>Sandbox</p>")
