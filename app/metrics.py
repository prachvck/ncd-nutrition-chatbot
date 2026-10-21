"""
app/metrics.py — เก็บข้อมูลวัดผลต่อข้อความ (เวลาตอบ, intent, LLM/RAG) [DEV_LOG Entry 44]

ใช้ contextvars ให้ handler ไหนก็ได้ใส่ข้อมูลของ "ข้อความที่กำลังประมวลผล" ได้
โดยไม่ต้องส่งตัวแปรผ่านทุกฟังก์ชัน — webhook เป็นคนเปิด/ปิดแล้วบันทึกลง
interaction_logs (ดู db/database.py) — วิเคราะห์ผลด้วย eval/latency_report.py
"""
import time
import contextvars
from contextlib import contextmanager

_current: contextvars.ContextVar[dict | None] = contextvars.ContextVar("metrics", default=None)


def start(**fields) -> dict:
    d = {"t0": time.perf_counter(), "llm_ms": 0.0, **fields}
    _current.set(d)
    return d


def mark(**fields) -> None:
    d = _current.get()
    if d is not None:
        for k, v in fields.items():
            # route / fallback แรกที่ถูกตั้งคือค่าหลัก ไม่ให้ handler ย่อยทับ
            if k in ("route", "fallback") and d.get(k):
                continue
            d[k] = v


def add_llm_ms(ms: float) -> None:
    d = _current.get()
    if d is not None:
        d["llm_ms"] = d.get("llm_ms", 0.0) + ms


@contextmanager
def llm_timer():
    t = time.perf_counter()
    try:
        yield
    finally:
        add_llm_ms((time.perf_counter() - t) * 1000)


def finish() -> dict | None:
    d = _current.get()
    if d is None:
        return None
    d["server_ms"] = round((time.perf_counter() - d.pop("t0")) * 1000, 1)
    _current.set(None)
    return d
