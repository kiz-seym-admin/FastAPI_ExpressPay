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
    first_name: str
    last_name: str
    phone: Optional[str] = None


class UserResponse(BaseModel):
    UserID: int
    email: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaymentCreate(BaseModel):
    course_id: int
    customer_email: EmailStr
    customer_first_name: str
    customer_last_name: str
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
    PaymentID: int
    OrderNum: str
    UserID: int
    SubscriptionID: int
    FormURL: Optional[str] = None
    Status: str
    created_at: datetime
    expired_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserWithPayments(BaseModel):
    UserID: int
    email: str
    first_name: str
    last_name: str
    payments: List[PaymentRecord] = []

    model_config = {"from_attributes": True}


# Статусы счёта Express-Pay
EP_STATUS_MAP = {
    0: "pending",
    1: "preauth",
    2: "successful",
    3: "cancelled",
    4: "refunded",
    5: "in_progress",
    6: "declined",
}
