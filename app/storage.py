"""
JSON-хранилище только для courses.json.
Users и Payments хранятся в MySQL (см. database.py).
"""
import json, os, threading
from datetime import datetime

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
