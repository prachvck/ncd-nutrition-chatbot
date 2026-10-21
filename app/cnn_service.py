"""
app/cnn_service.py — จุดเสียบโมเดล CNN (THFOOD-100) ของ Kittipong [DEV_LOG Entry 47]

สัญญา (contract) ระหว่าง 2 ฝั่ง:
  - Kittipong ส่งไฟล์โมเดลมาไว้ที่ CNN_MODEL_PATH (.keras / SavedModel) ที่รับ
    ภาพ RGB ขนาด CNN_IMG_SIZE×CNN_IMG_SIZE (ค่า 0-255 หรือ 0-1 ตาม CNN_RESCALE)
    และคืน softmax 100 คลาส เรียงตาม Directory_Name 00..99 ใน cnn_class_labels.csv
  - ฝั่งแชทบอทแปลง index → food_id ด้วย cnn_label_food_mapping.csv (100/100 คลาส)
    แล้วส่งเข้า flow บันทึกการกินเดิม (_handle_log_meal) — ผู้ใช้ต้องกดยืนยันก่อนเสมอ

ถ้ายังไม่มีไฟล์โมเดล → is_ready() = False และแชทบอทตอบว่ายังไม่รองรับรูป
ถ้าโมเดลต้องการ preprocessing อื่น (เช่น EfficientNet preprocess_input) ให้แก้
ที่ _preprocess() จุดเดียว

[DEV_LOG Entry 62] โหมด API (ใช้จริง): Kittipong ส่งโมเดลมาเป็นบริการแยก
`THFOOD100_Chatbot_Inference/thfood100_inference/server.py` (SwinV2-T, PyTorch,
Top-1 92.19% / Top-3 98.05% บน test 13,376 ภาพ) — ตั้ง CNN_API_URL แล้วแชทบอท
POST raw image bytes ไป /api/predict ได้ top-3 {class_id "00".."99", food_class,
probability} → class_id ตรงกับ Directory_Name ใน cnn_label_food_mapping.csv
(ตรวจแล้ว 100/100 ชื่อตรงกัน) — preprocessing ทำฝั่งบริการทั้งหมด
"""
from __future__ import annotations

import io
import os
import csv
import json
import time
import logging
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

CNN_API_URL      = os.getenv("CNN_API_URL", "").strip()     # เช่น http://127.0.0.1:8081/api/predict
# [Entry 62] โหมดหลัก: โหลดโมเดลของ Kittipong เข้ามาในแชทบอทเลย (ไม่ต้องเปิด server แยก)
CNN_PACKAGE_DIR  = os.getenv("CNN_PACKAGE_DIR", "THFOOD100_Chatbot_Inference/thfood100_inference")
CNN_DEVICE       = os.getenv("CNN_DEVICE", "cpu")
_predictor = None
CNN_API_TIMEOUT  = float(os.getenv("CNN_API_TIMEOUT", "60"))
_health_cache    = {"t": 0.0, "ok": False}

CNN_MODEL_PATH   = os.getenv("CNN_MODEL_PATH", "models/cnn_thfood100.keras")
CNN_IMG_SIZE     = int(os.getenv("CNN_IMG_SIZE", "224"))
CNN_RESCALE      = os.getenv("CNN_RESCALE", "1")       # "1" = หาร 255 ก่อนเข้าโมเดล
CNN_MIN_CONF     = float(os.getenv("CNN_MIN_CONFIDENCE", "0.40"))
CNN_MODEL_VERSION = os.getenv("CNN_MODEL_VERSION", os.path.basename(CNN_MODEL_PATH))
MAPPING_CSV      = os.getenv("CNN_MAPPING_CSV", "cnn_label_food_mapping.csv")

_model = None
_labels: list[dict] = []


def _load_mapping():
    global _labels
    if _labels or not os.path.exists(MAPPING_CSV):
        return
    with open(MAPPING_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: int(r["Directory_Name"]))
    _labels = [{
        "label": r["Dish_Name_Thai"], "label_en": r["Dish_Name_English"],
        "food_id": int(r["food_id"]) if (r.get("food_id") or "").strip().isdigit() else None,
        "db_name": r.get("db_food_name_th") or r["Dish_Name_Thai"],
        "exact": r.get("status") == "ตรง",
    } for r in rows]


def _health_url() -> str:
    return CNN_API_URL.rsplit("/api/", 1)[0] + "/api/health"


def _api_healthy(force: bool = False) -> bool:
    """เช็คบริการ CNN (cache 30 วิ — ไม่ยิง health ทุกรูป)"""
    now = time.time()
    if not force and now - _health_cache["t"] < 30:
        return _health_cache["ok"]
    ok = False
    try:
        with urllib.request.urlopen(_health_url(), timeout=3) as r:
            ok = bool(json.load(r).get("ready"))
    except Exception:
        ok = False
    _health_cache.update(t=now, ok=ok)
    return ok


def _init_package() -> bool:
    """โหลด FoodPredictor จาก inference.py ในแพ็กเกจของ Kittipong (SwinV2-T, PyTorch)"""
    global _predictor, CNN_MODEL_VERSION
    path = os.path.join(CNN_PACKAGE_DIR, "inference.py")
    if not os.path.exists(path):
        return False
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("thfood100_inference", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _predictor = mod.FoodPredictor(device=CNN_DEVICE)
        if not os.getenv("CNN_MODEL_VERSION"):
            CNN_MODEL_VERSION = f"thfood100-swinv2t-ep{_predictor.epoch}"
        log.info(f"CNN: โหลดโมเดล THFOOD-100 (SwinV2-T epoch {_predictor.epoch}, {CNN_DEVICE}) แล้ว")
        return True
    except Exception as e:
        log.warning(f"CNN: โหลดโมเดลจาก {CNN_PACKAGE_DIR} ไม่สำเร็จ: {e}")
        _predictor = None
        return False


def init_cnn():
    global _model, CNN_MODEL_VERSION
    _load_mapping()
    if not CNN_API_URL and _init_package():
        return
    if CNN_API_URL:
        ok = _api_healthy(force=True)
        if not os.getenv("CNN_MODEL_VERSION"):
            CNN_MODEL_VERSION = "thfood100-swinv2t-ep12-api"
        log.info(f"CNN: โหมด API {CNN_API_URL} — "
                 + ("พร้อมใช้งาน" if ok else "ยังเรียกไม่ได้ (เปิด server.py ของโมเดลก่อน; จะลองใหม่อัตโนมัติ)"))
        return
    if not os.path.exists(CNN_MODEL_PATH):
        log.info(f"CNN: ยังไม่มีไฟล์โมเดล ({CNN_MODEL_PATH}) — ปิดฟีเจอร์รูปภาพไว้ก่อน")
        return
    try:
        import tensorflow as tf
        _model = tf.keras.models.load_model(CNN_MODEL_PATH)
        log.info(f"CNN: โหลดโมเดล {CNN_MODEL_PATH} แล้ว ({len(_labels)} labels)")
    except Exception as e:
        log.warning(f"CNN: โหลดโมเดลไม่สำเร็จ: {e}")
        _model = None


def is_ready() -> bool:
    if len(_labels) != 100:
        return False
    if _predictor is not None:
        return True
    if CNN_API_URL:
        return _api_healthy()
    return _model is not None


def _content_type(b: bytes) -> str:
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _predict_api(image_bytes: bytes, top_k: int) -> list[dict]:
    req = urllib.request.Request(CNN_API_URL, data=image_bytes, method="POST",
                                 headers={"Content-Type": _content_type(image_bytes)})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=CNN_API_TIMEOUT) as r:
                res = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:      # บริการกำลังทายรูปอื่น → รอแล้วลองใหม่
                time.sleep(1.0 + attempt)
                continue
            raise
    out = []
    for p in res.get("predictions", [])[:top_k]:
        i = int(p["class_id"])
        out.append({**_labels[i], "index": i, "confidence": float(p["probability"])})
    return out


def _preprocess(image_bytes: bytes):
    import numpy as np
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((CNN_IMG_SIZE, CNN_IMG_SIZE))
    x = np.asarray(img, dtype="float32")
    if CNN_RESCALE == "1":
        x = x / 255.0
    return x[None, ...]


def predict(image_bytes: bytes, top_k: int = 3) -> list[dict]:
    """คืน top-k [{label, food_id, db_name, confidence}] (sync — เรียกผ่าน to_thread)"""
    if _predictor is not None:
        for attempt in range(20):           # รับทีละภาพ (lock ในโมเดล) → รอคิว
            try:
                res = _predictor.predict(image_bytes)
                break
            except BlockingIOError:
                time.sleep(0.5)
        else:
            raise RuntimeError("CNN busy")
        return [{**_labels[int(p["class_id"])], "index": int(p["class_id"]),
                 "confidence": float(p["probability"])} for p in res["predictions"][:top_k]]
    if CNN_API_URL:
        return _predict_api(image_bytes, top_k)
    import numpy as np
    probs = _model.predict(_preprocess(image_bytes), verbose=0)[0]
    idx = np.argsort(probs)[::-1][:top_k]
    return [{**_labels[i], "index": int(i), "confidence": float(probs[i])} for i in idx]
