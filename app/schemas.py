from typing import List, Optional
from pydantic import BaseModel, EmailStr


class CourseCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: float          # в BYN: 80.00
    duration_weeks: Optional[int] = None


class CourseResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: float
    duration_weeks: Optional[int] = None
    is_active: bool
    created_at: str


class UserCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    phone: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    created_at: str


class PaymentCreate(BaseModel):
    course_id: int
    customer_email: EmailStr
    customer_first_name: str
    customer_last_name: str
    customer_phone: Optional[str] = None


class PaymentInitResponse(BaseModel):
    id: int
    tracking_id: str
    ep_invoice_no: Optional[int] = None
    form_url: Optional[str] = None      # URL страницы оплаты Express-Pay
    qr_url: str                         # GET /payments/{tracking_id}/qr
    status: str
    is_test: bool
    amount: float
    course_name: str


class PaymentRecord(BaseModel):
    id: int
    tracking_id: str
    ep_invoice_no: Optional[int] = None
    course_id: Optional[int] = None
    course_name: Optional[str] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    user_id: Optional[int] = None
    customer_email: Optional[str] = None
    customer_first_name: Optional[str] = None
    customer_last_name: Optional[str] = None
    form_url: Optional[str] = None
    status: str
    is_test: bool
    webhook_received: bool
    qr_generated: bool
    created_at: str
    updated_at: Optional[str] = None


# Статусы счёта по карте Express-Pay
# 0 – зарегистрирован, не оплачен
# 1 – предавторизация
# 2 – полная авторизация (оплачен)
# 3 – авторизация отменена
# 4 – возврат
# 5 – инициирована авторизация через ACS
# 6 – авторизация отклонена
EP_STATUS_MAP = {
    0: "pending",
    1: "preauth",
    2: "successful",
    3: "cancelled",
    4: "refunded",
    5: "in_progress",
    6: "declined",
}
