"""
JSON-хранилище данных.
Три файла в DATA_DIR (/data):
  courses.json   — подписки/курсы
  users.json     — пользователи
  payments.json  — все платежи (включая тестовые)
"""
import json, os, threading
from datetime import datetime, timezone
from typing import Optional

DATA_DIR = os.getenv("DATA_DIR", "/data")
_lock = threading.RLock()


def _path(f): return os.path.join(DATA_DIR, f)
def _now(): return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
def _next_id(items): return max((i.get("id", 0) for i in items), default=0) + 1


def _read(filename: str) -> list:
    p = _path(filename)
    if not os.path.exists(p): return []
    with open(p, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except json.JSONDecodeError: return []


def _write(filename: str, data: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_path(filename), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


# ── COURSES ───────────────────────────────────────────────────────────────────
def get_all_courses(only_active=True):
    with _lock:
        d = _read("courses.json")
        return [c for c in d if c.get("is_active", True)] if only_active else d

def get_course(course_id: int):
    with _lock:
        return next((c for c in _read("courses.json") if c["id"] == course_id), None)

def create_course(data: dict):
    with _lock:
        courses = _read("courses.json")
        c = {"id": _next_id(courses), "is_active": True, "created_at": _now(), **data}
        courses.append(c); _write("courses.json", courses); return c

def update_course(course_id: int, updates: dict):
    with _lock:
        courses = _read("courses.json")
        for c in courses:
            if c["id"] == course_id:
                c.update(updates); _write("courses.json", courses); return c
        return None


# ── USERS ─────────────────────────────────────────────────────────────────────
def get_all_users():
    with _lock: return _read("users.json")

def get_user(user_id: int):
    with _lock: return next((u for u in _read("users.json") if u["id"] == user_id), None)

def get_user_by_email(email: str):
    with _lock:
        return next((u for u in _read("users.json") if u["email"].lower() == email.lower()), None)

def create_user(data: dict):
    with _lock:
        users = _read("users.json")
        u = {"id": _next_id(users), "created_at": _now(), **data}
        users.append(u); _write("users.json", users); return u

def upsert_user(email: str, first_name: str, last_name: str, phone: Optional[str] = None):
    ex = get_user_by_email(email)
    if ex: return ex
    return create_user({"email": email.lower(), "first_name": first_name,
                        "last_name": last_name, "phone": phone})


# ── PAYMENTS ──────────────────────────────────────────────────────────────────
def get_all_payments():
    with _lock: return _read("payments.json")

def get_payment_by_tracking(tracking_id: str):
    with _lock:
        return next((p for p in _read("payments.json") if p.get("tracking_id") == tracking_id), None)

def get_payment_by_invoice(invoice_no: int):
    with _lock:
        return next((p for p in _read("payments.json") if p.get("ep_invoice_no") == invoice_no), None)

def get_payments_by_user(user_id: int):
    with _lock: return [p for p in _read("payments.json") if p.get("user_id") == user_id]

def create_payment(data: dict):
    with _lock:
        payments = _read("payments.json")
        p = {"id": _next_id(payments), "status": "pending",
             "webhook_received": False, "qr_generated": False,
             "created_at": _now(), "updated_at": None, **data}
        payments.append(p); _write("payments.json", payments); return p

def update_payment(tracking_id: str, updates: dict):
    with _lock:
        payments = _read("payments.json")
        for p in payments:
            if p.get("tracking_id") == tracking_id:
                p.update({**updates, "updated_at": _now()})
                _write("payments.json", payments); return p
        return None
