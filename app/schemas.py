from typing import List, Optional
from pydantic import BaseModel, EmailStr
from datetime import datetime


class CourseCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
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
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None


class UserResponse(BaseModel):
    UserID: int
    email: str
    promocode: Optional[str] = None
    phone_num: Optional[str] = None
    name: Optional[str] = None
    user_status: str
    dealer: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PaymentCreate(BaseModel):
    course_id: int
    customer_email: EmailStr
    customer_first_name: Optional[str] = None
    customer_last_name: Optional[str] = None
    customer_phone: Optional[str] = None


class PaymentInitResponse(BaseModel):
    PaymentID: int
    OrderNum: str
    FormURL: Optional[str] = None
    qr_url: str
    Status: str
    is_test: bool
    amount: float
    course_name: str


class PaymentRecord(BaseModel):
    PurchaseID: int
    order_num: Optional[str] = None
    user_id: Optional[int] = None
    subscription_id: Optional[int] = None
    url: Optional[str] = None
    status: str
    is_test: bool          # <- поле для маркировки тестовых платежей
    created_at: datetime
    expired_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserWithPayments(BaseModel):
    UserID: int
    email: str
    promocode: Optional[str] = None
    phone_num: Optional[str] = None
    name: Optional[str] = None
    user_status: str
    dealer: str
    payments: List[PaymentRecord] = []

    model_config = {"from_attributes": True}


EP_STATUS_MAP = {
    0: "pending", 1: "preauth", 2: "successful",
    3: "cancelled", 4: "refunded", 5: "in_progress", 6: "declined",
}

BLOCKED_MSG = "Ваш аккаунт заблокирован, попробуйте позже или обратитесь к администратору"
