"""
app/meal_warnings.py — คำเตือนตามโรคตอนบันทึกอาหาร (พิมพ์ / กดการ์ด / ส่งรูป) [DEV_LOG Entry 63]

ก่อนหน้านี้การบันทึกอาหารบอกแค่ kcal ทั้งที่ถ้าผู้ใช้ "ถามแคล" เมนูเดียวกัน ระบบจะบอกว่า
ไม่เหมาะกับโรค (evaluate_food_limits) → ไม่สอดคล้องกัน โดยเฉพาะบันทึกจากรูป (CNN)

ใช้กฎตัวเลขล้วน (ไม่เรียก LLM) และเกณฑ์ชุดเดียวกับส่วนอื่นของระบบ:
  1) ตอนถามยืนยัน: เทียบจาน (คูณขนาดจานแล้ว) กับเพดานต่อมื้อ → evaluate_food_limits
     ตัวเดียวกับ "แนะนำอาหาร" (_hard_filter) และ "ถามแคล"
  2) หลังกดยืนยัน: ยอดรวมวันนี้ "เพิ่งเกิน" เป้ารายวันเพราะมื้อนี้ → เกณฑ์เดียวกับหน้า
     Dashboard (app/dashboard.status_of) ตัวเลขทั้งระบบจะได้ตรงกัน
ไม่ห้ามบันทึก — ผู้ใช้กินไปแล้ว ระบบมีหน้าที่บอกให้รู้และแนะนำมื้อถัดไป
"""
from __future__ import annotations

from app import dashboard

PORTION_MUL = {"small": 0.75, "normal": 1.0, "large": 1.35}

_SCALE_KEYS = ("energy_kcal", "carb_available_g", "protein_g", "fat_g", "sodium_mg",
               "potassium_mg", "phosphorus_mg", "calcium_mg", "magnesium_mg",
               "potassium_mg_ckd_conservative", "phosphorus_mg_ckd_conservative")

NUT_TH = {"energy_kcal": "พลังงาน", "carb_available_g": "คาร์โบไฮเดรต", "protein_g": "โปรตีน",
          "fat_g": "ไขมัน", "sodium_mg": "โซเดียม", "potassium_mg": "โพแทสเซียม",
          "phosphorus_mg": "ฟอสฟอรัส", "saturated_fat": "ไขมันอิ่มตัว", "sugar_risk": "น้ำตาล"}

# คำแนะนำสั้นๆ สำหรับ "มื้อถัดไป" เมื่อจานนี้เกินเพดานต่อมื้อ
MEAL_TIP = {
    "energy_kcal": "มื้อถัดไปเลือกจานเล็กหรือเมนูต้ม/นึ่ง",
    "carb_available_g": "มื้อถัดไปลดข้าว/เส้นลง เพิ่มผักแทน",
    "fat_g": "มื้อถัดไปเลี่ยงของทอดและกะทิ",
    "sodium_mg": "มื้อถัดไปเลี่ยงน้ำซุป น้ำจิ้ม และไม่เติมเครื่องปรุงเพิ่ม",
    "potassium_mg": "มื้อถัดไปเลี่ยงผลไม้/ผักโพแทสเซียมสูง (กล้วย ฝรั่ง ผักใบเขียวเข้ม)",
    "phosphorus_mg": "มื้อถัดไปเลี่ยงนม ถั่ว และอาหารแปรรูป",
    "protein_g": "มื้อถัดไปลดปริมาณเนื้อสัตว์ลง",
    "saturated_fat": "มื้อถัดไปเลือกต้ม/นึ่ง/ย่าง เลี่ยงของทอด กะทิ และหนังสัตว์",
    "sugar_risk": "เลี่ยงของหวาน/เครื่องดื่มหวานในวันนี้ ดื่มน้ำเปล่าแทน",
}


def scale_food(fd: dict, portion: str) -> dict:
    """ค่าของจาน × ขนาดจาน (ค่าในระบบเก็บเป็นขนาดปกติ save_food_log คูณตอนบันทึก)"""
    mul = PORTION_MUL.get(portion or "normal", 1.0)
    out = dict(fd)
    for k in _SCALE_KEYS:
        if isinstance(out.get(k), (int, float)):
            out[k] = out[k] * mul
    return out


def _fmt(v: float, unit: str) -> str:
    return f"{v:,.0f} {unit}".strip()


def relevant_keys(diseases) -> set:
    """เตือนเฉพาะสารอาหารที่สำคัญกับโรคของผู้ใช้ (dashboard.CRITICAL) — ไม่เตือนพลังงาน/ไขมัน/
    โซเดียมต่อมื้อให้คนไม่มีโรค (อาหารไทยเกือบทุกจานเกิน จะกลายเป็นเตือนทุกมื้อจนผู้ใช้ไม่อ่าน)
    ยอดรวมรายวันยังเตือนทุกคนผ่าน daily_crossed_warnings"""
    keys = {"sugar_risk", "saturated_fat"}
    for d in diseases or []:
        keys |= dashboard.CRITICAL.get(d, set())
    return keys


def format_meal_warnings(evaluation: dict | None, diseases=None, max_lines: int = 3) -> str:
    """แปลงผล evaluate_food_limits เป็นข้อความต่อท้ายคำถามยืนยัน ("" = ไม่มีอะไรต้องเตือน)"""
    if not evaluation or evaluation.get("ok", True):
        return ""
    keep = relevant_keys(diseases)
    seen, lines, tips = {}, [], []
    # คาร์บอาจถูกเช็ค 2 รอบ (เพดานต่อมื้อทั่วไป + เพดานเบาหวาน) → เก็บอันที่มี note
    for e in evaluation.get("exceeds", []):
        k = e.get("nutrient")
        if k not in keep:
            continue
        if k not in seen or (e.get("note") and not seen[k].get("note")):
            seen[k] = e
    order = ["sugar_risk", "potassium_mg", "phosphorus_mg", "sodium_mg", "protein_g",
             "carb_available_g", "saturated_fat", "fat_g", "energy_kcal"]
    if not seen:
        return ""
    for k in sorted(seen, key=lambda x: order.index(x) if x in order else 99)[:max_lines]:
        e = seen[k]
        name = NUT_TH.get(k, k)
        if e.get("value") is not None and e.get("limit") and k != "sugar_risk":
            line = f"• {name} {_fmt(e['value'], e['unit'])} (เพดานต่อมื้อ {_fmt(e['limit'], e['unit'])})"
            if e.get("note"):
                line += f" — {e['note']}"
        elif e.get("value") is None and k in ("sodium_mg", "potassium_mg", "phosphorus_mg"):
            # fail-safe "ไม่มีข้อมูลจริง" — ตอนบันทึกบอกแบบนุ่มกว่าตอนกรองเมนู
            line = f"• ไม่มีข้อมูล{name}ของเมนูนี้ในระบบ ควรระวังสำหรับโรคของคุณ"
        else:
            line = f"• {e.get('note') or name + 'เกินเกณฑ์'}"
        lines.append(line)
        if MEAL_TIP.get(k) and len(tips) < 2:
            tips.append(MEAL_TIP[k])
    msg = "⚠️ ข้อควรระวังสำหรับโรคของคุณ:\n" + "\n".join(lines)
    msg += "\nบันทึกได้ตามปกติครับ"
    if tips:
        msg += " แนะนำ: " + " / ".join(tips)
    return msg


def daily_crossed_warnings(today: dict, meal: dict, daily_limit: dict, diseases) -> str:
    """หลังบันทึก: สารอาหารที่ "เพิ่งเกิน" เป้ารายวันเพราะมื้อนี้ (ไม่เตือนซ้ำทุกมื้อ)"""
    ds = set(diseases or [])
    mul = PORTION_MUL.get(meal.get("portion", "normal"), 1.0)
    hits = []
    for key, tkey, name, unit in dashboard.nutrient_keys(ds):
        target = dashboard._f(daily_limit.get(key))
        if target <= 0:
            continue
        now = dashboard._f(today.get(tkey))
        before = now - dashboard._f(meal.get(key)) * mul
        if (dashboard.status_of(key, now, target, ds) == "high"
                and dashboard.status_of(key, before, target, ds) != "high"):
            hits.append((key, name, unit, now, target))
    if not hits:
        return ""
    lines = [f"• {n} {_fmt(v, u)} / เป้า {_fmt(t, u)}" for _, n, u, v, t in hits]
    advice = [dashboard.ADVICE[(k, "high")] for k, *_ in hits if (k, "high") in dashboard.ADVICE][:2]
    why = [dashboard.WHY[(k, d)] for k, *_ in hits for d in ds if (k, d) in dashboard.WHY][:1]
    msg = "📊 วันนี้เกินเป้าแล้ว:\n" + "\n".join(lines)
    if why:
        msg += f"\nℹ️ {why[0]}"
    if advice:
        msg += "\n👉 มื้อที่เหลือ: " + " ".join(advice)
    return msg
