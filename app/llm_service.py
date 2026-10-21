"""
app/llm_service.py
LLM layer ใช้ Typhoon-v2 (SCB Tech) — ภาษาไทยดี, API เหมือน OpenAI
สมัครฟรี: https://opentyphoon.ai
"""
import os
import json
import re
from openai import OpenAI

TYPHOON_API_KEY = os.getenv("TYPHOON_API_KEY", "")
TYPHOON_BASE_URL = "https://api.opentyphoon.ai/v1"
MODEL = "typhoon-v2.5-30b-a3b-instruct"

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client, TYPHOON_API_KEY
    if _client is None:
        # [FIX — DEV_LOG Entry 51] อ่าน key ตอนเรียกใช้จริง ไม่ใช่ตอน import — สคริปต์
        # ที่ import โมดูลนี้ก่อน load_dotenv (เช่น eval/eval_intent.py) เคยได้ key ว่าง
        if not TYPHOON_API_KEY:
            from dotenv import load_dotenv
            load_dotenv(override=True)
            TYPHOON_API_KEY = os.getenv("TYPHOON_API_KEY", "")
        if not TYPHOON_API_KEY:
            raise RuntimeError("TYPHOON_API_KEY is not set in .env")
        # [FIX — DEV_LOG Entry 30] ตั้ง timeout — ค่าเริ่มต้นของ client คือ
        # 600 วินาที ถ้า Typhoon ช้า webhook จะค้างจน reply token ของ LINE
        # หมดอายุ (ใช้ได้ไม่ถึงนาที) ผู้ใช้ไม่ได้คำตอบอะไรเลย ตอนนี้ถ้าเกิน
        # timeout จะ raise แล้วแต่ละฟังก์ชันตกไปใช้ข้อความสำรองของตัวเอง
        _client = OpenAI(api_key=TYPHOON_API_KEY, base_url=TYPHOON_BASE_URL,
                         timeout=LLM_TIMEOUT_S, max_retries=1)
    return _client


LLM_TIMEOUT_S = 15

# [FIX — DEV_LOG Entry 30] กฎความปลอดภัยสำหรับผู้ป่วยไต — ใส่ใน prompt ทุกจุด
# ที่ LLM ให้คำแนะนำอาหาร กัน LLM แนะนำ "กล้วย/ส้มช่วยลดความดัน" ให้คนที่
# เป็นทั้งความดันและไต (ความรู้ทั่วไปของ LLM/DASH ขัดกับข้อจำกัด CKD)
# [Entry 50] รายการผักผลไม้ตามตาราง 10.2 ข้อแนะนำเวชปฏิบัติ CKD 2565 (สมาคมโรคไตฯ)
CKD_SAFETY_RULE = ("ผู้ใช้เป็นโรคไต: ห้ามแนะนำให้กินอาหารโพแทสเซียมสูง ได้แก่ ผลไม้ (กล้วย ฝรั่ง ขนุน "
                   "ทุเรียน ลำไย น้อยหน่า มะม่วง มะขามหวาน แคนตาลูป ลูกเกด น้ำส้มคั้น น้ำมะพร้าว) "
                   "ผัก (ผักบุ้ง คะน้า ผักโขม บรอคโคลี แครอท เห็ด มันฝรั่ง มันเทศ ฟักทอง ข้าวโพด หัวปลี) "
                   "หรือฟอสฟอรัสสูง (นม ชีส ถั่วเมล็ดแห้ง อาหารแปรรูป) แม้ผู้ใช้จะเป็นความดันสูงร่วมด้วยก็ตาม — "
                   "ข้อจำกัดโรคไตสำคัญกว่าเสมอ ถ้าจะแนะนำผลไม้ทดแทนให้เลือกที่โพแทสเซียมต่ำถึงปานกลาง "
                   "เช่น แอปเปิ้ล ชมพู่ สับปะรด แตงโม องุ่นเขียว มังคุด ในปริมาณพอเหมาะ "
                   "และห้ามแนะนำเกลือทดแทน (โลว์โซเดียม) เพราะมักมีโพแทสเซียม")


# [DEV_LOG Entry 52] eval_rag พบ LLM แนะนำ "มะม่วงน้ำดอกไม้ (น้ำตาลต่ำ)" ให้ผู้ป่วยเบาหวาน —
# ผลไม้หวานจัดตรงกับรายการน้ำตาลอิสระที่ระบบใช้กรองเมนู (scripts/compute_sugar_risk.py)
DM_SAFETY_RULE = ("ผู้ใช้เป็นเบาหวาน: กินผลไม้สดได้มื้อละ 1 ส่วน แต่ห้ามแนะนำผลไม้หวานจัดว่าเป็นผลไม้น้ำตาลต่ำ "
                  "(มะม่วงสุก ทุเรียน ลำไย ลิ้นจี่ องุ่น ขนุนสุก กล้วยหอม น้อยหน่า) และน้ำผลไม้ "
                  "ถ้าจะยกตัวอย่างผลไม้ที่เหมาะ ให้ใช้ ฝรั่ง แอปเปิ้ล ชมพู่ ส้ม สาลี่ แก้วมังกร "
                  "(ถ้าเป็นโรคไตร่วม ให้ยึดรายการผลไม้ของโรคไตก่อนเสมอ)")


def _ckd_rule(diseases) -> str:
    """กฎความปลอดภัยตามโรคที่ใส่ใน prompt (ชื่อเดิมคงไว้ — ตอนนี้รวมเบาหวานด้วย)"""
    ds = diseases or []
    out = ""
    if "ckd" in ds:
        out += f"\n{CKD_SAFETY_RULE}"
    if "diabetes" in ds:
        out += f"\n{DM_SAFETY_RULE}"
    return out


def _chat(system: str, user: str, max_tokens: int = None, temperature: float = 0.4) -> str:
    """helper: เรียก LLM แล้วคืน string"""
    # [FIX — DEV_LOG Entry 34] ทดสอบจริงบอทลงท้ายปน "ครับ"/"ค่ะ" — ข้อความ
    # สำเร็จรูปของบอททั้งหมดใช้ "ครับ" จึงบังคับให้ LLM ใช้แบบเดียวกัน
    # (ไม่ใส่ใน prompt ที่ต้องตอบเป็น JSON)
    if "JSON" not in system:
        system = system + "\nลงท้ายประโยคด้วย 'ครับ' เสมอ ห้ามใช้ 'ค่ะ' หรือ 'คะ'"
    params = dict(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=temperature,
    )
    if max_tokens:
        params["max_tokens"] = max_tokens
    resp = _get_client().chat.completions.create(**params)
    text = resp.choices[0].message.content.strip()
    # [Entry 52] Typhoon หลุดตัวอักษรจีนกลางประโยคบางครั้ง (เจอ "适量" ใน eval_rag) — ตัดทิ้ง
    return re.sub(r"[\u3400-\u4dbf\u4e00-\u9fff]+", "", text)


# ════════════════════════════════════════════════════════════════════
# Intent Classifier (LLM-based) — แทนที่ keyword matching ล้วนๆ ใน
# app/state.py เพราะ keyword matching เข้าใจแค่ประโยคที่เคยเห็นมาก่อน
# (เช่น "เบาหวานกินทุเรียนได้มั้ย" มีคำว่า "กิน" ถูกเข้าใจผิดเป็น log_meal
# ทั้งที่เป็นคำถาม) — ดู DEV_LOG.md entry ที่เกี่ยวข้อง
# ════════════════════════════════════════════════════════════════════

INTENT_LABELS_TH = {
    "recommend":    "ขอแนะนำเมนูอาหาร",
    "log_meal":     "บันทึกว่ากินอะไรไปแล้ว (อดีต/ยืนยันแล้ว)",
    "ask_calorie":  "ถามข้อมูลโภชนาการ หรือถามว่าอาหารนี้เหมาะสมไหม",
    "summary":      "ขอสรุปสิ่งที่กินไปวันนี้",
    "edit_profile": "แก้ไขข้อมูลโปรไฟล์สุขภาพ",
    "help":         "ขอความช่วยเหลือ/วิธีใช้งาน",
}

CLASSIFY_INTENT_SYSTEM = """คุณคือระบบจำแนกเจตนาข้อความสำหรับแชทบอทแนะนำอาหารผู้ป่วย NCD
วิเคราะห์ข้อความของผู้ใช้แล้วตอบเป็น JSON เท่านั้น ห้ามมีคำอธิบายเพิ่มเติม

รูปแบบ JSON:
{
  "intent": "<intent ที่มั่นใจที่สุด>",
  "confidence": <ตัวเลข 0.0-1.0>,
  "candidates": ["<intent ที่เป็นไปได้ 2-4 อัน เรียงจากน่าจะเป็นมากสุด>"]
}

ตัวเลือก intent มีดังนี้:
- recommend: ขอแนะนำเมนูอาหาร เช่น "แนะนำเมนู", "วันนี้กินอะไรดี", "หิว"
- log_meal: บอกว่ากินอะไรไปแล้วจริงๆ (เป็นการยืนยัน ไม่ใช่คำถาม) เช่น "กินข้าวผัดหมูมื้อเที่ยง", "เพิ่งทานส้มตำไป"
- ask_calorie: ถามคำถามเกี่ยวกับอาหาร (มักลงท้ายด้วย ไหม มั้ย หรือเปล่า เท่าไร) เช่น "ทุเรียนกินได้มั้ย", "ข้าวผัดหมูกี่แคล", "เบาหวานกินทุเรียนได้ไหม"
- summary: ขอสรุปสิ่งที่กินไปวันนี้ เช่น "สรุปวันนี้", "วันนี้กินไปเท่าไรแล้ว"
- edit_profile: ขอแก้ไขข้อมูลส่วนตัว เช่น "แก้ไขโปรไฟล์", "เปลี่ยนน้ำหนัก"
- help: ขอวิธีใช้งานระบบ เช่น "ช่วยด้วย", "ใช้งานยังไง"
- unknown: ไม่เข้าใจข้อความเลย ไม่เข้าเงื่อนไขไหนเลย

กฎสำคัญที่สุด: **ประโยคที่มีลักษณะเป็นคำถาม (ลงท้ายด้วย ไหม/มั้ย/หรือเปล่า/เหรอ หรือถามปริมาณ/ความเหมาะสม)
ให้จัดเป็น ask_calorie เสมอ แม้จะมีคำว่า "กิน"/"ทาน" อยู่ในประโยคก็ตาม** เพราะผู้ใช้กำลังถาม
ไม่ใช่กำลังยืนยันว่ากินไปแล้ว — เช่น "เบาหวานกินทุเรียนได้มั้ย" ต้องเป็น ask_calorie ไม่ใช่ log_meal

ถ้ามั่นใจสูง (>0.8) ให้ candidates มีแค่ 1 ตัวซ้ำกับ intent ก็ได้
ถ้าไม่มั่นใจ (ประโยคกำกวม/สั้นเกินไป/ตีความได้หลายแบบ) ให้ confidence ต่ำ และใส่ candidates หลายตัว"""


def classify_intent_llm(text: str) -> dict:
    """
    จำแนกเจตนาด้วย LLM แทน keyword matching เพื่อให้เข้าใจประโยคที่ไม่เคย
    เห็นมาก่อนได้ (generalize) ไม่ใช่แค่จับคำที่ลงทะเบียนไว้

    คืน dict: {"intent": str, "confidence": float, "candidates": list[str]}
    ถ้า LLM เรียกไม่สำเร็จ (เช่น API key ผิด/เน็ตล่ม) คืน confidence=0.0
    เพื่อให้ผู้เรียกไป fallback ไปใช้ keyword classifier แทน (graceful degradation)
    """
    try:
        raw = _chat(CLASSIFY_INTENT_SYSTEM, text, max_tokens=256, temperature=0.1)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
            intent = result.get("intent", "unknown")
            if intent not in INTENT_LABELS_TH and intent != "unknown":
                intent = "unknown"
            candidates = [c for c in result.get("candidates", []) if c in INTENT_LABELS_TH]
            return {
                "intent": intent,
                "confidence": float(result.get("confidence", 0.0)),
                "candidates": candidates,
            }
    except Exception as e:
        print(f"[Intent classify error] {e}")
    return {"intent": "unknown", "confidence": 0.0, "candidates": []}


# ════════════════════════════════════════════════════════════════════
# Feature 2 — LLM Parser: แปลงข้อความบันทึกกินเป็น structured data
# ════════════════════════════════════════════════════════════════════

PARSE_SYSTEM = """คุณคือระบบแปลงข้อความบันทึกอาหารเป็น JSON
ตอบเป็น JSON เท่านั้น ห้ามมีคำอธิบายเพิ่มเติม

รูปแบบ JSON ที่ต้องการ:
{
  "food_name_th": "ชื่ออาหารภาษาไทย",
  "meal_type": "breakfast|lunch|dinner|snack|unknown",
  "portion": "small|normal|large",
  "confidence": 0.0-1.0
}

กฎ:
- meal_type: เช้า/ตื่นนอน = breakfast, เที่ยง/กลางวัน = lunch, เย็น/ค่ำ/มื้อเย็น = dinner, ของว่าง/ขนม = snack
- portion: จานเล็ก/นิดหน่อย = small, ปกติ = normal, จานใหญ่/เยอะ/สองจาน = large
- ถ้าไม่แน่ใจ portion ให้ใช้ normal
- ถ้าข้อความไม่ได้บอกมื้อชัดเจน (ไม่มีคำว่า เช้า/เที่ยง/กลางวัน/เย็น/ค่ำ/ของว่าง) ให้ meal_type = unknown ห้ามเดาเอง
- ถ้ามีหลายเมนูในข้อความ ให้ food_name_th เป็นเมนูหลักเมนูแรก
- food_name_th ใช้ชื่อเมนูหลักแบบสั้นที่คนทั่วไปเรียก ไม่ต้องใส่เครื่องเคียง (เช่น "กะเพราไก่ไข่ดาว" → "ข้าวกะเพราไก่")
- food_name_th ให้เป็นชื่ออาหารที่คนไทยใช้ทั่วไป"""


def parse_meal_text(user_text: str) -> dict:
    """
    รับข้อความจาก user เช่น "กินข้าวผัดหมูมื้อเที่ยง จานใหญ่"
    คืน dict: food_name_th, meal_type, portion, confidence
    """
    try:
        raw = _chat(PARSE_SYSTEM, user_text, max_tokens=512, temperature=0.1)
        # ดึง JSON ออกมา (บางครั้ง LLM ใส่ markdown code block)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"[LLM parse error] {e}")
    # fallback
    return {
        "food_name_th": user_text[:50],
        "meal_type": "unknown",
        "portion": "normal",
        "confidence": 0.3,
    }


def confirm_meal_message(food_name_th: str, meal_type: str,
                          energy_kcal: float, today_total_kcal: float,
                          daily_limit_kcal: float, user_name: str = "",
                          over_note: str = "") -> str:
    """
    Feature 2 — สร้างข้อความยืนยันการบันทึก เชิงบริบท
    เช่น "บันทึกแล้วนะครับ ข้าวผัดหมูมื้อเที่ยง ~700 kcal วันนี้กินไปแล้ว..."
    """
    meal_th = {"breakfast": "มื้อเช้า", "lunch": "มื้อเที่ยง",
               "dinner": "มื้อเย็น", "snack": "ของว่าง"}.get(meal_type, "")
    remaining = daily_limit_kcal - today_total_kcal
    pct = int(today_total_kcal / daily_limit_kcal * 100) if daily_limit_kcal else 0

    system = """คุณคือผู้ช่วยโภชนาการที่พูดภาษาไทยเป็นธรรมชาติ สั้น กระชับ เป็นกันเอง
ตอบเป็นข้อความเดียว ไม่เกิน 3 ประโยค ห้ามใช้ bullet points"""

    prompt = f"""บันทึกอาหาร:
- ชื่ออาหาร: {food_name_th} {meal_th}
- พลังงานอาหารนี้: {energy_kcal:.0f} kcal
- รวมวันนี้: {today_total_kcal:.0f} kcal จากเป้า {daily_limit_kcal:.0f} kcal ({pct}%)
- คงเหลือ: {remaining:.0f} kcal

สร้างข้อความยืนยันการบันทึกที่เป็นธรรมชาติ บอกยอดสะสม และให้กำลังใจถ้าทำได้ดี หรือเตือนอ่อนๆ ถ้าใกล้เกิน"""
    # [Entry 76] ทดสอบจริง: LLM ชม "ทำได้ดีมาก" ทั้งที่โซเดียมเกินเป้าแล้ว (ข้อความเตือนตามมาติดกัน)
    if over_note:
        prompt += f"\n\nหมายเหตุ: วันนี้ {over_note} เกินเป้าแล้ว ห้ามชมว่าทำได้ดี ให้พูดสั้นๆ ว่าระบบจะบอกรายละเอียดต่อ"

    try:
        return _chat(system, prompt, max_tokens=512)
    except Exception:
        return (f"บันทึก{food_name_th}{meal_th}แล้วนะครับ ({energy_kcal:.0f} kcal) "
                f"วันนี้รวม {today_total_kcal:.0f}/{daily_limit_kcal:.0f} kcal")


# ════════════════════════════════════════════════════════════════════
# Feature 3 — LLM Responder: ตอบคำถามแคล เชิงบริบท
# ════════════════════════════════════════════════════════════════════

def _format_suitability(suitability: dict | None) -> str:
    """
    [FIX — DEV_LOG Entry 18] แปลงผลจาก NCDModel.evaluate_food_limits() เป็น
    ข้อความให้ LLM ใช้อ้างอิง — ทำให้คำตอบตรงนี้อ้างอิงเกณฑ์ตัวเลขเดียวกับ
    ตอน "แนะนำเมนู" (_hard_filter) แทนที่จะให้ LLM เดาเองว่าเกินหรือไม่เกิน
    """
    if not suitability:
        return ""
    lines = []
    if suitability.get("exceeds"):
        lines.append("ผลเช็คเกณฑ์ (คำนวณจริง ไม่ใช่การเดา) — เกินเพดานต่อมื้อดังนี้:")
        for item in suitability["exceeds"]:
            note = f" ({item['note']})" if item.get("note") else ""
            # [FIX — DEV_LOG Entry 22] value=None = ไม่มีข้อมูล (fail-safe CKD)
            # เดิมแสดงเป็น "None mg" ทำให้ LLM สับสน
            # [FIX — DEV_LOG Entry 34] ระบุ "ต่อมื้อ" ทุกบรรทัด — ทดสอบจริง LLM
            # อ่านเพดานต่อมื้อ (เช่นโซเดียม 500mg) แล้วพูดว่า "500mg ต่อวัน"
            if item.get("value") is None and item.get("limit") is None:
                # [Entry 46] เกณฑ์แบบไม่มีตัวเลข (เช่น กลุ่มไขมันอิ่มตัวสูงสำหรับโรคหัวใจ)
                lines.append(f"- {item.get('note', item['nutrient'])}")
                continue
            if item.get("value") is None:
                lines.append(
                    f"- {item['nutrient']}: ไม่มีข้อมูล "
                    f"(เพดานต่อมื้อ {item['limit']}{item['unit']}){note}"
                )
                continue
            lines.append(
                f"- {item['nutrient']}: {item['value']}{item['unit']} ต่อหนึ่งที่ "
                f"> เพดานต่อมื้อ {item['limit']}{item['unit']}{note}"
            )
    else:
        lines.append("ผลเช็คเกณฑ์ (คำนวณจริง): อยู่ในเกณฑ์ต่อมื้อที่กำหนดไว้ทุกตัว ไม่มีตัวไหนเกิน")
    if suitability.get("sugar_risk") is not None:
        lines.append(f"ระดับความเสี่ยงน้ำตาล/คาร์บของจานนี้ (สเกล 1-5, ยิ่งมากยิ่งไม่เหมาะกับเบาหวาน): {suitability['sugar_risk']}/5")
    return "\n".join(lines)


def answer_calorie_question(food_results: list[dict], user_profile: dict,
                             user_question: str, rag_context: str = "",
                             suitability: dict | None = None, match_note: str = "") -> str:
    """
    match_note  : [Entry 66] ไม่พบเมนูที่ถามตรงตัว ใช้เมนูใกล้เคียงแทน — บอก LLM ห้ามเรียกข้อมูลนี้
                  ด้วยชื่อที่ผู้ใช้ถาม (เคยเกิด: "ไข่เจียวใส่เยลลี่หมี" ได้ค่าของไข่เจียวธรรมดาแต่ตอบเหมือนเป็นจานนั้น)
    Feature 3 — รับข้อมูลอาหารจาก DB + profile user → LLM สร้างคำตอบ
    food_results: list ของ dict ที่ได้จาก NCDModel.search_food()
    rag_context : เอกสารอ้างอิงที่ดึงมาจาก rag_service.query_rag() (ถ้ามี)
                  ใช้ลด hallucination — ให้ LLM ตอบโดยอิงเอกสารจริงแทนการเดา
    suitability : ผลจาก NCDModel.evaluate_food_limits() (ถ้ามี) — เกณฑ์ตัวเลข
                  ชุดเดียวกับที่ _hard_filter ใช้กรองตอน "แนะนำเมนู" ใส่ไว้
                  กันคำตอบตรงนี้ขัดแย้งกับตอนแนะนำเมนู (ดู DEV_LOG Entry 18)
    """
    if not food_results:
        system = """คุณคือนักโภชนาการที่พูดภาษาไทยเป็นธรรมชาติ เป็นกันเอง
    ตอบ 2-3 ประโยคจากความรู้ทั่วไปด้านโภชนาการ ระบุด้วยว่าเหมาะกับโรคของผู้ใช้ไหม
    ถ้ามี "เอกสารอ้างอิง" ให้อิงคำตอบจากเอกสารนั้นเป็นหลัก ห้ามพูดว่า "จากเอกสาร" หรือ "ตามข้อมูลอ้างอิง" — พูดตรงๆ เป็นธรรมชาติ"""
        diseases = user_profile.get("diseases", [])
        prompt = (
            f"คำถาม: {user_question}\n"
            f"โรคของผู้ใช้: {', '.join(diseases) if diseases else 'ไม่มี'}"
            f"{_ckd_rule(diseases)}"
        )
        if rag_context:
            prompt += f"\n\nเอกสารอ้างอิง:\n{rag_context}"
        try:
            return _chat(system, prompt)
        except Exception:
            return "ขออภัยครับ ไม่พบข้อมูลอาหารนี้ในฐานข้อมูล ลองพิมพ์ชื่ออาหารอื่นได้เลยครับ"

    food = food_results[0]
    diseases = user_profile.get("diseases", [])
    goal     = user_profile.get("goal", "")
    gender   = "คุณ"

    # สร้าง context จากข้อมูลจริง
    food_info = (
        f"ชื่อ: {food['food_name_th']}\n"
        f"พลังงาน: {food['energy_kcal']:.0f} kcal ต่อหนึ่งมื้อ ({food['_serving_g']}g)\n"
        f"คาร์บ: {food['carb_available_g']:.1f}g | โปรตีน: {food['protein_g']:.1f}g | "
        f"ไขมัน: {food['fat_g']:.1f}g | โซเดียม: {food['sodium_mg']:.0f}mg"
    )
    profile_info = (
        f"โรคประจำตัว: {', '.join(diseases) if diseases else 'ไม่มี'}\n"
        f"เป้าหมาย: {goal if goal else 'ทั่วไป'}\n"
        f"แคลต่อมื้อ: {user_profile.get('meal_limit_kcal', 600):.0f} kcal"
        f"{_ckd_rule(diseases)}"
    )

    system = """คุณคือนักโภชนาการที่พูดภาษาไทยเป็นธรรมชาติ เป็นกันเอง
ตอบ 3-4 ประโยค บอกแคลและสารอาหารสำคัญ บอกว่าเหมาะกับโรคไหม และให้คำแนะนำเพิ่มเติม
ห้ามพูดว่า "ตามข้อมูลที่ได้รับ" หรือ "จากข้อมูล" หรือ "จากเอกสารอ้างอิง" — พูดตรงๆ เป็นธรรมชาติ
ถ้ามี "เอกสารอ้างอิง" ให้ใช้เป็นหลักฐานประกอบคำแนะนำ อย่าขัดแย้งกับเอกสารนั้น
ถ้ามี "ผลเช็คเกณฑ์" ให้ยึดตามนั้นเป็นหลักเสมอเวลาบอกว่ากินได้ไหม/เหมาะไหม
ห้ามตอบขัดแย้งกับผลเช็คเกณฑ์นี้เด็ดขาด (เช่น ถ้าบอกว่าเกินเพดาน ห้ามตอบว่ากินได้สบายๆ)
แต่ยังพูดเป็นธรรมชาติได้ ไม่ต้องพูดคำว่า "ผลเช็คเกณฑ์" ตรงๆ กับผู้ใช้"""

    prompt = f"""คำถามผู้ใช้: {user_question}

ข้อมูลอาหาร:
{food_info}

โปรไฟล์ผู้ใช้:
{profile_info}"""

    suitability_text = _format_suitability(suitability)
    if suitability_text:
        prompt += f"\n\n{suitability_text}"

    if match_note:
        prompt += (f"\n\nสำคัญ: {match_note}\n"
                   f"ให้เรียกเมนูด้วยชื่อ \"{food['food_name_th']}\" เท่านั้น ห้ามพูดเหมือนตัวเลขนี้เป็นของเมนูที่ผู้ใช้ถาม "
                   f"ถ้าเมนูที่ผู้ใช้ถามมีส่วนผสมเพิ่ม (เช่น ของหวาน ซอส ของทอด) ให้บอกว่าค่าจริงน่าจะสูงกว่านี้ "
                   f"และถ้าเป็นการผสมที่ไม่ใช่เมนูทั่วไป ให้บอกตรงๆ อย่างสุภาพ")

    if rag_context:
        prompt += f"\n\nเอกสารอ้างอิง (แนวทางโภชนาการที่เกี่ยวข้อง):\n{rag_context}"

    prompt += "\n\nตอบคำถามโดยบอกแคล และให้คำแนะนำที่เหมาะกับโรคและเป้าหมายของผู้ใช้"

    try:
        return _chat(system, prompt, max_tokens=512)
    except Exception:
        return (
            f"{food['food_name_th']} {food['energy_kcal']:.0f} kcal ต่อมื้อ "
            f"(คาร์บ {food['carb_available_g']:.0f}g ไขมัน {food['fat_g']:.0f}g "
            f"โซเดียม {food['sodium_mg']:.0f}mg) ครับ"
        )


# ════════════════════════════════════════════════════════════════════
# Feature 1 — LLM ทักทาย/อธิบายเมนูที่แนะนำ (optional enhancement)
# ════════════════════════════════════════════════════════════════════

def explain_recommendation(meals: list[dict], user_profile: dict) -> str:
    """สร้างคำอธิบายเมนูพร้อมเหตุผลตามโรค"""
    diseases = user_profile.get("diseases", [])
    names    = [m["food_name_th"] for m in meals[:3]]

    disease_names = {
        "diabetes": "เบาหวาน", "hypertension": "ความดัน",
        "heart": "โรคหัวใจ", "ckd": "โรคไต", "obesity": "โรคอ้วน",
    }
    diseases_th = [disease_names.get(d, d) for d in diseases]

    # [Entry 76] ทดสอบจริง: LLM เตือนว่าเมนูที่ระบบเพิ่งแนะนำ "อาจมีน้ำมันและเกลือสูง ควรเลี่ยง" —
    # เมนูทุกจานผ่านเกณฑ์ความปลอดภัยของโรคแล้ว ห้ามพูดขัดแย้งกับการแนะนำ
    system = """คุณคือผู้ช่วยโภชนาการที่พูดภาษาไทยเป็นกันเอง
ตอบ 2 ประโยค: ประโยคแรกบอกหลักการกินสั้นๆ ที่เหมาะกับโรคของผู้ใช้ (ถ้าไม่มีโรค ให้บอกหลักการกินทั่วไป)
ประโยคที่สองบอกว่าเมนูที่เลือกมาเหมาะอย่างไร
เมนูทั้งหมดผ่านเกณฑ์ความปลอดภัยตามโรคของผู้ใช้แล้ว ห้ามบอกให้หลีกเลี่ยงหรือเตือนว่าเมนูในรายการนี้ไม่เหมาะ
ห้ามใช้ bullet points"""

    prompt = (
        f"เมนูแนะนำวันนี้: {', '.join(names)}\n"
        f"โรคประจำตัว: {', '.join(diseases_th) if diseases_th else 'ไม่มี'}"
        f"{_ckd_rule(diseases)}"
    )
    try:
        return _chat(system, prompt)
    except Exception:
        return "เมนูแนะนำวันนี้เลือกมาให้เหมาะกับคุณแล้วนะครับ"
