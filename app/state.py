"""
app/state.py  —  Phase 1
จัดการ conversation state ของแต่ละ user (in-memory)
"""
from enum import Enum


class State(str, Enum):
    NEW          = "new"           # ยังไม่เคยคุยเลย
    ASK_NAME     = "ask_name"
    ASK_AGE      = "ask_age"
    ASK_GENDER   = "ask_gender"
    ASK_WEIGHT   = "ask_weight"
    ASK_HEIGHT   = "ask_height"
    ASK_ACTIVITY = "ask_activity"
    ASK_DISEASES = "ask_diseases"
    ASK_GOAL     = "ask_goal"
    READY        = "ready"         # profile ครบ พร้อมใช้งาน
    LOGGING_MEAL = "logging_meal"  # กำลังบันทึกการกิน (Phase 2)
    CONFIRM_MEAL = "confirm_meal"


# ── in-memory store ─────────────────────────────────────────────────
# { line_user_id: { "state": State, "profile": {...}, "temp": {...} } }
_sessions: dict[str, dict] = {}


def get_state(uid: str) -> State:
    return _sessions.get(uid, {}).get("state", State.NEW)


def set_state(uid: str, state: State):
    _sessions.setdefault(uid, {})["state"] = state


def get_profile(uid: str) -> dict:
    return _sessions.get(uid, {}).get("profile", {})


def set_profile(uid: str, profile: dict):
    _sessions.setdefault(uid, {})["profile"] = profile


def get_temp(uid: str) -> dict:
    return _sessions.get(uid, {}).get("temp", {})


def set_temp(uid: str, key: str, value):
    _sessions.setdefault(uid, {}).setdefault("temp", {})[key] = value


def clear_temp(uid: str):
    _sessions.setdefault(uid, {})["temp"] = {}


# ── Onboarding questions ─────────────────────────────────────────────
ONBOARD_QUESTIONS = {
    State.ASK_NAME: (
        "สวัสดีครับ ผมคือ NCD Bot\n"
        "ช่วยแนะนำอาหารเพื่อสุขภาพและป้องกัน NCD\n\n"
        "ขอทราบชื่อเล่นได้เลยครับ"
    ),
    State.ASK_AGE: "อายุเท่าไรครับ? (ตัวเลขเท่านั้น เช่น 35)",
    State.ASK_GENDER: "เพศอะไรครับ? พิมพ์  ชาย  หรือ  หญิง",
    State.ASK_WEIGHT: "น้ำหนักปัจจุบันกี่กิโลครับ? (เช่น 65)",
    State.ASK_HEIGHT: "ส่วนสูงกี่เซนติเมตรครับ? (เช่น 170)",
    State.ASK_ACTIVITY: (
        "ระดับกิจกรรมประจำวันครับ พิมพ์ตัวเลข 1-5\n\n"
        "1 = นั่งทำงานทั้งวัน\n"
        "2 = ออกกำลังกายเบาๆ 1-3 วัน/สัปดาห์\n"
        "3 = ออกกำลังกายปานกลาง 3-5 วัน/สัปดาห์\n"
        "4 = ออกกำลังกายหนัก 6-7 วัน/สัปดาห์\n"
        "5 = งานใช้แรงกายหนักมาก"
    ),
    State.ASK_DISEASES: (
        "มีโรคประจำตัวไหมครับ?\n"
        "พิมพ์ชื่อโรคที่มี (คั่นด้วยลูกน้ำ) หรือพิมพ์  ไม่มี\n\n"
        "ที่รองรับ: เบาหวาน, ความดัน, อ้วน, ไต, หัวใจ"
    ),
    State.ASK_GOAL: (
        "เป้าหมายด้านสุขภาพครับ พิมพ์ตัวเลข 1-5\n\n"
        "1 = ลดน้ำหนัก\n"
        "2 = ลดหวาน\n"
        "3 = ลดเค็ม\n"
        "4 = ลดไขมัน\n"
        "5 = สุขภาพดีทั่วไป"
    ),
}

ONBOARD_ORDER = [
    State.ASK_NAME, State.ASK_AGE, State.ASK_GENDER,
    State.ASK_WEIGHT, State.ASK_HEIGHT, State.ASK_ACTIVITY,
    State.ASK_DISEASES, State.ASK_GOAL,
]

GOAL_MAP = {
    "1": "ลดน้ำหนัก", "2": "ลดหวาน", "3": "ลดเค็ม",
    "4": "ลดไขมัน",  "5": "สุขภาพดีทั่วไป",
}
GENDER_MAP = {
    "ชาย": "male", "หญิง": "female",
    "male": "male", "female": "female",
}
DISEASE_MAP = {
    "เบาหวาน":          "diabetes",
    "ความดัน":          "hypertension",
    "ความดันโลหิตสูง":  "hypertension",
    "อ้วน":             "obesity",
    "ไต":               "ckd",
    "โรคไต":            "ckd",
    "หัวใจ":            "heart",
    "โรคหัวใจ":         "heart",
}


def parse_diseases(text: str) -> list[str]:
    if any(w in text for w in ["ไม่มี", "ไม่", "-", "none"]):
        return []
    return [en for th, en in DISEASE_MAP.items() if th in text]


# ── Intent classifier ────────────────────────────────────────────────
RECOMMEND_KW = [
    "แนะนำ", "เมนู", "กินอะไรดี", "อยากกิน", "recommend",
    "อาหาร", "ควรกินอะไร", "มีอะไรกิน", "หิว", "อยากทาน",
]

LOG_KW = [
    "กิน", "ทาน", "รับประทาน", "บันทึก", "เพิ่ง",
    "เมื่อกี้", "ตะกี้", "มื้อเช้า", "มื้อเที่ยง", "มื้อเย็น",
    "ของว่าง", "ได้กิน", "เพิ่งกิน", "เพิ่งทาน","__eat__"
]

CALORIE_KW = [
    "กี่แคล", "กี่กิโลแคล", "แคลอรี่", "แคล",
    "คาร์บ", "ไขมัน", "โปรตีน", "โซเดียม", "น้ำตาล",
    "สารอาหาร", "กี่แคลอรี่", "เท่าไร", "สูงไหม", "เยอะไหม",
    "ดีไหม", "เหมาะไหม", "ควรกินไหม", "มีประโยชน์",
    "อ้วนไหม", "หวานไหม", "เค็มไหม", "มันไหม",
    "ข้อมูลโภชนาการ", "nutrition", "calories",
]

SUMMARY_KW = [
    "สรุป", "วันนี้กินไป", "กินไปแล้ว", "รวม",
    "กินไปเท่าไร", "แคลวันนี้", "สรุปวัน", "ดูประวัติ",
    "กินอะไรไปบ้าง", "วันนี้กินอะไร",
]

PROFILE_KW = [
    "แก้ไข", "เปลี่ยนข้อมูล", "อัปเดตโปรไฟล์", "โปรไฟล์",
    "ข้อมูลส่วนตัว", "น้ำหนักฉัน", "อัปเดต", "แก้ข้อมูล",
    "เปลี่ยนน้ำหนัก", "อัปเดตน้ำหนัก",
]

HELP_KW = [
    "help", "ช่วย", "คำสั่ง", "ทำอะไรได้",
    "ใช้งานยังไง", "วิธีใช้", "มีอะไรบ้าง", "สอนหน่อย",
]


def classify_intent(text: str) -> str:
    t = text.lower()
    if any(k in t for k in CALORIE_KW):   return "ask_calorie"
    if any(k in t for k in SUMMARY_KW):   return "summary"
    if any(k in t for k in LOG_KW):       return "log_meal"
    if any(k in t for k in RECOMMEND_KW): return "recommend"
    if any(k in t for k in PROFILE_KW):   return "edit_profile"
    if any(k in t for k in HELP_KW):      return "help"
    return "unknown"

def get_session_history(uid: str) -> list:
    return _sessions.get(uid, {}).get("session_history", [])

def add_session_history(uid: str, food_names: list):
    hist = _sessions.setdefault(uid, {}).setdefault("session_history", [])
    hist.extend(food_names)
    _sessions[uid]["session_history"] = hist[-9:]

def clear_session_history(uid: str):
    if uid in _sessions:
        _sessions[uid]["session_history"] = []


def extract_food_keyword(text: str) -> str:
    """ตัดคำถาม/คำโรคออกจากข้อความ เหลือชื่ออาหาร ("ข้าวผัดกี่แคล" → "ข้าวผัด")
    [Entry 49] ย้ายมาจาก main._handle_ask_calorie ให้ eval/eval_rag.py ใช้ตัวเดียวกัน"""
    kw = text
    # [FIX — DEV_LOG Entry 29] ตัดคำยาวก่อนคำสั้นเสมอ — เดิมตัด "กี่แคล" ก่อน
    # "กี่แคลอรี่" ทำให้ "ข้าวผัดกี่แคลอรี่" เหลือ "ข้าวผัดอรี่" แล้วค้นไม่เจอ
    for k in sorted(["กี่แคล","กี่กิโลแคล","แคลอรี่","กี่แคลอรี่","กี่กิโลแคลอรี่","ได้ไหม","ได้มั้ย","มั้ย","ไหม",
          "สารอาหาร","nutrition","calories","ข้อมูลโภชนาการ",
          "สูงไหม","เยอะไหม","ดีไหม","เหมาะไหม","ควรกินไหม",
          "มีประโยชน์","อ้วนไหม","หวานไหม","เค็มไหม","มันไหม","อร่อยไหม","อร่อย",
          "ไขมันสูงไหม","โซเดียมสูงไหม","น้ำตาลสูงไหม",
          "แคลสูงไหม","คาร์บสูงไหม","โปรตีนสูงไหม",
          "ไขมัน","โซเดียม","น้ำตาล","คาร์บ","แคล","โปรตีน",
          "คนเป็นเบาหวาน","เบาหวาน","ความดันสูง","ความดัน","โรคไต","โรคหัวใจ",
          "ไม่เกิน","เกิน","กินได้","ทานได้","กิน","ทาน","เท่าไหร่","เท่าไร","มีกี่","ครับ","ค่ะ","คะ",
          "แดก","มั๊ย"],
          key=len, reverse=True):
        kw = kw.replace(k,"").strip()
    # [Entry 68] คำลงท้ายภาษาพูด (จากทดสอบจริง "ส้มตำกินได้มั้ยอ่ะ" เคยเหลือ "ส้มตำอ่ะ")
    # ตัดเฉพาะท้ายคำ — "อะ" อยู่กลาง "อะไร" ได้ ห้ามตัดทุกที่
    for _ in range(2):
        for suf in ("หน่อย", "เหรอ", "หรอ", "บ้าง", "อ่ะ", "ป่ะ", "จ้า", "จ้ะ", "น้า", "อะ", "ปะ", "นะ"):
            if kw.endswith(suf) and len(kw) > len(suf) + 1:
                kw = kw[:-len(suf)].strip()
    # "ส้มตำมีกี่แคลอรี่" → ตัดแล้วเหลือ "ส้มตำมี" — ตัด "มี" เฉพาะท้ายคำ
    # (ห้ามตัดทุกที่ เพราะ "หมี่" มี "มี" อยู่ข้างใน)
    # [Entry 66] ยกเว้น "หมี" ("เยลลี่หมี" เคยเหลือ "เยลลี่ห")
    if kw.endswith("มี") and not kw.endswith("หมี"):
        kw = kw[:-2].strip()
    # [Entry 49] "เป็นโรคไตกินกล้วยได้ไหม" → เหลือ "เป็นกล้วย" — ตัดคำนำหน้าที่บอกโรค
    for pre in ("ผู้ป่วย", "คนเป็น", "เป็น", "คนที่", "และ", "กับ"):
        if kw.startswith(pre):
            kw = kw[len(pre):].strip()
    if kw.startswith("ไต") and not kw.startswith("ไตปลา") and len(kw) > 2:   # "เป็นไตกินนม"
        kw = kw[2:].strip()
    return kw.strip()


# [DEV_LOG Entry 51] คำกว้างๆ ที่ไม่ใช่ชื่อเมนู — eval_rag เจอ "เบาหวานกินผลไม้ได้ไหม"
# ไปค้นเจอ "ผลไม้ดอง" แล้ว LLM ตอบเรื่องผลไม้ดอง ถ้าเหลือแค่คำกลุ่มนี้ให้ตอบแบบความรู้ทั่วไป
GENERIC_FOOD_TERMS = {
    "ผลไม้", "ผัก", "อาหาร", "ข้าว", "แป้ง", "ของหวาน", "ขนม", "เนื้อสัตว์", "เนื้อแดง", "ปลา",
    "ถั่ว", "นม", "เครื่องดื่ม", "น้ำหวาน", "ของทอด", "อาหารแปรรูป", "เกลือ", "น้ำตาล",
    "ไขมัน", "โปรตีน", "คาร์บ", "โซเดียม", "อะไร", "อะไรบ้าง", "อาหารอะไร", "",
}


def is_generic_food_term(kw: str) -> bool:
    return (kw or "").strip() in GENERIC_FOOD_TERMS or len((kw or "").strip()) < 2
