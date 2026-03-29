import json, logging, os, uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from .database import init_db, get_db, User, Subscription, Purchase as Payment, calc_expired_at, async_session_maker
from .express_pay import (
    BASE_URL, EP_IS_TEST, create_card_invoice,
    get_card_invoice_status, get_qr_code_base64, run_startup_test,
)
from .qr import base64_to_png, generate_local_qr
from .schemas import (
    CourseCreate, CourseResponse, UserCreate, UserResponse, UserWithPayments,
    PaymentCreate, PaymentInitResponse, PaymentRecord, EP_STATUS_MAP, BLOCKED_MSG,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "/data")
COURSES_FILE = os.path.join(DATA_DIR, "courses.json")


def _ensure_courses_file():
    """Гарантирует наличие каталога и файла courses.json для одноразовой миграции.

    Здесь не используем storage, чтобы не тянуть его на импорт приложения.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(COURSES_FILE):
        with open(COURSES_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2, ensure_ascii=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Запуск FastAPI-ExpressPay...")
    logger.info(f"   Режим: {'🧪 SANDBOX' if EP_IS_TEST else '💳 PRODUCTION'}")
    _ensure_courses_file()
    await init_db()
    # Миграция курсов из JSON в таблицу subscriptions
    try:
        from . import storage as _storage
        from .database import Subscription as _Sub
        async with async_session_maker() as session:
            existing_ids = {s.SubscriptionID for s in (await session.execute(select(_Sub))).scalars().all()}
            courses = _storage.get_all_courses(only_active=False)
            created = 0
            for c in courses:
                if c["id"] in existing_ids:
                    continue
                sub = _Sub(
                    SubscriptionID=c["id"],
                    name=c["name"],
                    description=c.get("description"),
                    price=c["price"],
                    duration=(c.get("duration_weeks") or 0) * 7,
                    status="Active" if c.get("is_active", True) else "Blocked",
                )
                session.add(sub); created += 1
            if created:
                await session.commit()
                logger.info(f"✅ Миграция курсов: добавлено {created} подписок в MySQL")
    except Exception as e:
        logger.error(f"⚠️ Ошибка миграции курсов: {e}")
    # Логируем количество подписок из БД
    try:
        async with async_session_maker() as session:
            total = (await session.execute(select(func.count(Subscription.SubscriptionID)))).scalar_one()
            logger.info(f"📄 Загружено курсов: {total}")
    except Exception as e:
        logger.error(f"⚠️ Не удалось посчитать курсы: {e}")
    try:
        res = await run_startup_test()
        if res["ok"]:
            logger.info(
                f"✅ Express-Pay OK | InvoiceNo={res['invoice_no']} | "
                f"FormUrl={res.get('form_url') or 'sandbox'}"
            )
        else:
            logger.warning(f"⚠️ Тестовый счёт: {res.get('error', res.get('raw'))}")
    except Exception as exc:
        logger.error(f"❌ Startup test: {exc}")
    yield
    logger.info("🛑 Остановлен.")


app = FastAPI(
    title="FastAPI-ExpressPay",
    description="Backend оплаты курсов — Express-Pay · MySQL · QR-коды",
    version="3.2.0",
    lifespan=lifespan,
)


def _sub_to_course_response(sub: Subscription) -> CourseResponse:
    """Преобразует ORM Subscription в схему CourseResponse."""
    duration_weeks = (sub.duration or 0) // 7
    is_active = sub.status == "Active"
    # created_at храним только в БД как server_default NOW(),
    # но в ответе достаточно строки ISO формата
    created_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return CourseResponse(
        id=sub.SubscriptionID,
        name=sub.name,
        description=sub.description,
        price=float(sub.price),
        duration_weeks=duration_weeks,
        is_active=is_active,
        created_at=created_str,
    )


def _check_blocked(user: User) -> None:
    """Бросает 403 если пользователь заблокирован."""
    if user.user_status == "Blocked":
        raise HTTPException(status_code=403, detail=BLOCKED_MSG)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Служебные"])
async def health(db: AsyncSession = Depends(get_db)):
    users = (await db.execute(select(User))).scalars().all()
    # Считаем только реальные платежи (is_test=False)
    payments = (await db.execute(select(Payment).where(Payment.is_test == False))).scalars().all()
    courses = (await db.execute(select(Subscription))).scalars().all()
    return {
        "status": "ok",
        "mode": "sandbox" if EP_IS_TEST else "production",
        "users": len(users),
        "payments": len(payments),
        "courses": len(courses),
    }


# ── Courses (JSON) ────────────────────────────────────────────────────────────

@app.get("/active_courses", response_model=List[CourseResponse], tags=["Подписки"])
async def list_courses(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Subscription).where(Subscription.status == "Active"))
    subs = result.scalars().all()
    return [_sub_to_course_response(s) for s in subs]


@app.get("/courses/all/list", response_model=List[CourseResponse], tags=["Подписки"])
async def list_all_courses(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Subscription))
    subs = result.scalars().all()
    return [_sub_to_course_response(s) for s in subs]


@app.get("/courses/{course_id}", response_model=CourseResponse, tags=["Подписки"])
async def get_course(course_id: int, db: AsyncSession = Depends(get_db)):
    sub = await db.get(Subscription, course_id)
    if not sub:
        raise HTTPException(404, "Курс не найден")
    return _sub_to_course_response(sub)


@app.post("/courses", response_model=CourseResponse, tags=["Подписки"], status_code=201)
async def create_course(body: CourseCreate, db: AsyncSession = Depends(get_db)):
    duration_days = (body.duration_weeks or 0) * 7
    sub = Subscription(
        name=body.name,
        description=body.description,
        price=body.price,
        duration=duration_days,
        status="Active",
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return _sub_to_course_response(sub)


@app.patch("/courses/{course_id}", response_model=CourseResponse, tags=["Подписки"])
async def update_course(course_id: int, body: CourseCreate, db: AsyncSession = Depends(get_db)):
    sub = await db.get(Subscription, course_id)
    if not sub:
        raise HTTPException(404, "Курс не найден")
    sub.name = body.name
    sub.description = body.description
    sub.price = body.price
    sub.duration = (body.duration_weeks or 0) * 7
    await db.commit()
    await db.refresh(sub)
    return _sub_to_course_response(sub)


@app.delete("/courses/{course_id}", tags=["Подписки"])
async def deactivate_course(course_id: int, db: AsyncSession = Depends(get_db)):
    sub = await db.get(Subscription, course_id)
    if not sub:
        raise HTTPException(404, "Курс не найден")
    sub.status = "Blocked"
    await db.commit()
    return {"detail": "Курс деактивирован"}


@app.post("/courses/{course_id}/activate", tags=["Подписки"])
async def activate_course(course_id: int, db: AsyncSession = Depends(get_db)):
    sub = await db.get(Subscription, course_id)
    if not sub:
        raise HTTPException(404, "Курс не найден")
    sub.status = "Active"
    await db.commit()
    return {"detail": "Курс активирован"}


# ── Users (MySQL) ─────────────────────────────────────────────────────────────

@app.get("/users", response_model=List[UserResponse], tags=["Пользователи"])
async def list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User))
    return result.scalars().all()

@app.get("/users/{user_id}", response_model=UserResponse, tags=["Пользователи"])
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return user

@app.post("/users", response_model=UserResponse, tags=["Пользователи"], status_code=201)
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    existing = result.scalar_one_or_none()
    if existing:
        _check_blocked(existing)
        return existing
    user = User(
        email=body.email.lower(),
        first_name=body.first_name,
        last_name=body.last_name,
        phone=body.phone,
    )
    db.add(user); await db.commit(); await db.refresh(user)
    return user

@app.get("/users/{user_id}/payments", response_model=UserWithPayments, tags=["Пользователи"])
async def user_payments(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    _check_blocked(user)
    return user


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.post("/admin/users/{user_id}/block", tags=["Администраторы"])
async def block_user(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    user.user_status = "Blocked"
    await db.commit()
    return {"detail": f"Пользователь {user.email} заблокирован"}

@app.post("/admin/users/{user_id}/unblock", tags=["Администраторы"])
async def unblock_user(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    user.user_status = "Active"
    await db.commit()
    return {"detail": f"Пользователь {user.email} разблокирован"}

@app.post("/admin/users/{user_id}/request-delete", tags=["Администраторы"])
async def request_delete_user(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    user.user_status = "Blocked"
    await db.commit()
    return {"detail": f"Пользователь {user.email} помечен на удаление."}

@app.post("/admin/users/{user_id}/confirm-delete", tags=["Администраторы"])
async def confirm_delete_user(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    if user.user_status != "Blocked":
        raise HTTPException(400, "Сначала заблокируйте пользователя через /block")
    email = user.email
    await db.delete(user)
    await db.commit()
    return {"detail": f"Пользователь {email} и все его данные удалены"}

@app.get("/admin/users/pending-delete", response_model=List[UserResponse], tags=["Администраторы"])
async def list_pending_delete(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.user_status == "Blocked"))
    return result.scalars().all()

@app.post("/users/{user_id}/delete-request", tags=["Пользователи"])
async def request_account_delete(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    user.user_status = "Blocked"
    await db.commit()
    return {"detail": "Ваш аккаунт заблокирован и отправлен на удаление."}


# ── Payments (MySQL + ExpressPay) ─────────────────────────────────────────────

@app.post("/payments", response_model=PaymentInitResponse, tags=["Платежи"], status_code=201)
async def create_payment(body: PaymentCreate, db: AsyncSession = Depends(get_db)):
    course = await db.get(Subscription, body.course_id)
    if not course:
        raise HTTPException(404, "Курс не найден")
    if course.status != "Active":
        raise HTTPException(400, "Курс неактивен")
    result = await db.execute(select(User).where(User.email == body.customer_email.lower()))
    user = result.scalar_one_or_none()
    if user:
        _check_blocked(user)
    else:
        user = User(
            email=body.customer_email.lower(),
            first_name=body.customer_first_name,
            last_name=body.customer_last_name,
            phone=body.customer_phone,
        )
        db.add(user); await db.flush()
    tracking_id = f"order-{uuid.uuid4().hex}"
    try:
        ep_resp = await create_card_invoice(
            account_no=tracking_id[:30],
            amount=course.price,
            info=f"Оплата курса: {course.name}",
            return_url=f"{BASE_URL}/payment/success?tid={tracking_id}",
            fail_url=f"{BASE_URL}/payment/fail?tid={tracking_id}",
        )
    except Exception as exc:
        logger.error(f"Express-Pay error: {exc}")
        raise HTTPException(502, f"Ошибка Express-Pay: {exc}")
    invoice_no = ep_resp.get("InvoiceNo")
    form_url = ep_resp.get("FormUrl") or None
    logger.info(f"💳 InvoiceNo={invoice_no} FormUrl={form_url or '(sandbox)'}")
    payment = Payment(
        order_num=str(invoice_no or tracking_id),
        user_id=user.UserID,
        subscription_id=course.SubscriptionID,
        url=form_url,
        status="pending",
        is_test=False,
        expired_at=calc_expired_at(course.duration),
    )
    db.add(payment); await db.commit(); await db.refresh(payment)
    return PaymentInitResponse(
        PaymentID=payment.PurchaseID,
        OrderNum=payment.order_num,
        FormURL=form_url or "",
        qr_url=f"{BASE_URL}/payments/{payment.order_num}/qr",
        Status="pending",
        is_test=EP_IS_TEST,
        amount=float(course.price),
        course_name=course.name,
    )

@app.get("/payments/{order_num}/qr", tags=["Платежи"], response_class=Response,
         responses={200: {"content": {"image/png": {}}}})
async def get_payment_qr(order_num: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Payment).where(Payment.order_num == order_num))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(404, "Платёж не найден")
    form_url = payment.url or ""
    label = f"Подписка #{payment.subscription_id}"
    png_bytes = None
    try:
        b64 = await get_qr_code_base64(int(payment.order_num))
        if b64:
            png_bytes = base64_to_png(b64)
    except Exception:
        pass
    if not png_bytes:
        qr_target = form_url if form_url else f"{BASE_URL}/payment/paid"
        if not form_url:
            label = "Тестовый платёж — ОПЛАЧЕНО"
        png_bytes = generate_local_qr(qr_target, label=label)
    return Response(
        content=png_bytes, media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="qr_{order_num[:16]}.png"'},
    )

@app.get("/payments", response_model=List[PaymentRecord], tags=["Платежи"])
async def list_payments(
    status: Optional[str] = None,
    include_test: bool = False,   # по умолчанию тестовые скрыты
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    q = select(Payment)
    if not include_test:
        q = q.where(Payment.is_test == False)
    if status:
        q = q.where(Payment.status == status)
    q = q.order_by(Payment.PurchaseID.desc()).limit(limit)
    return (await db.execute(q)).scalars().all()

@app.get("/payments/{order_num}", response_model=PaymentRecord, tags=["Платежи"])
async def get_payment(order_num: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Payment).where(Payment.order_num == order_num))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(404, "Платёж не найден")
    return payment

@app.post("/payments/{order_num}/sync", tags=["Платежи"])
async def sync_payment_status(order_num: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Payment).where(Payment.order_num == order_num))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(404, "Платёж не найден")
    try:
        resp = await get_card_invoice_status(int(order_num))
    except ValueError:
        raise HTTPException(400, "OrderNum не является числом InvoiceNo")
    except Exception as exc:
        raise HTTPException(502, f"Ошибка Express-Pay: {exc}")
    error = resp.get("Error", {})
    if error:
        msg = error.get("Msg", "Неизвестная ошибка")
        if error.get("MsgCode") == 5000000:
            payment.status = "expired"; await db.commit()
            return {"OrderNum": order_num, "Status": "expired", "warning": msg}
        return {"OrderNum": order_num, "Status": payment.status, "warning": msg}
    ep_code = resp.get("CardInvoiceStatus") or resp.get("Status")
    if ep_code is None:
        return {"OrderNum": order_num, "Status": payment.status, "warning": "EP не вернул статус"}
    payment.status = EP_STATUS_MAP.get(int(ep_code), f"unknown_{ep_code}")
    await db.commit()
    return {"OrderNum": order_num, "ep_code": int(ep_code), "Status": payment.status}


# ── Webhook ───────────────────────────────────────────────────────────────────

@app.post("/webhook/expresspay", tags=["Webhook"])
async def expresspay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        try:
            body = await request.json()
        except Exception:
            form = await request.form(); body = dict(form)
    except Exception:
        return JSONResponse({"status": "error"}, status_code=400)
    logger.info(f"📩 Webhook: {json.dumps(body, default=str)[:400]}")
    invoice_no = body.get("InvoiceNo") or body.get("invoiceNo")
    ep_status = body.get("CardInvoiceStatus") or body.get("Status")
    if invoice_no:
        result = await db.execute(select(Payment).where(Payment.order_num == str(invoice_no)))
        payment = result.scalar_one_or_none()
        if payment:
            ep_code = int(ep_status) if ep_status is not None else -1
            payment.status = EP_STATUS_MAP.get(ep_code, payment.status)
            await db.commit()
            logger.info(f"✅ InvoiceNo={invoice_no} → {payment.status}")
        else:
            logger.warning(f"⚠️ InvoiceNo={invoice_no} не найден")
    return JSONResponse({"status": "ok"})


# ── Страницы результата ───────────────────────────────────────────────────────

def _page(title, msg, color, extra=""):
    return HTMLResponse(f"""<!DOCTYPE html><html><head><title>{title}</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px">
<h1 style="color:{color}">{msg}</h1>{extra}</body></html>""")

@app.get("/payment/success", response_class=HTMLResponse, tags=["Служебные"])
async def payment_success():
    return _page("Оплачено", "✅ Оплата прошла успешно!", "green")

@app.get("/payment/fail", response_class=HTMLResponse, tags=["Служебные"])
async def payment_fail():
    return _page("Ошибка", "❌ Оплата не прошла", "red")

@app.get("/payment/paid", response_class=HTMLResponse, tags=["Служебные"])
async def payment_paid():
    return _page("Тест", "💳 Тестовый платёж — ОПЛАЧЕНО", "blue")
