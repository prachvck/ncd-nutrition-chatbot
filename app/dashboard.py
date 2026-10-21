"""
app/dashboard.py — ข้อมูล + การวิเคราะห์สำหรับหน้า "สรุปการกิน" (LIFF) [DEV_LOG Entry 61]

หน้าเว็บ: profile/templates/dashboard.html (เปิดจาก LIFF: https://liff.line.me/<LIFF_ID>/dashboard)
API:      GET /api/dashboard?uid=... (ยืนยันตัวตนด้วย LINE access token เหมือนฟอร์มโปรไฟล์)

แสดงย้อนหลัง 10 วัน (รายวัน) + วิเคราะห์ 7 วันล่าสุดเทียบเป้าหมายและโรคประจำตัว
การวิเคราะห์เป็นกฎตายตัว (ไม่ใช้ LLM) ใช้เกณฑ์ชุดเดียวกับที่ระบบใช้แนะนำเมนู ซึ่งอ้างอิงแนวทาง
เวชปฏิบัติไทย (เบาหวาน 2566, ความดัน 2567, โรคไต 2565/2561) — ตัวเลขเหมือนกันทุกครั้ง ตรวจย้อนได้
"""
from __future__ import annotations

import datetime as dt

SHOW_DAYS = 10
WEEK = 7

NUTRIENTS = [
    # key ใน daily_limit, key ในสรุปรายวัน, ชื่อไทย, หน่วย
    ("energy_kcal", "total_energy_kcal", "พลังงาน", "kcal"),
    ("carb_available_g", "total_carb_g", "คาร์โบไฮเดรต", "g"),
    ("protein_g", "total_protein_g", "โปรตีน", "g"),
    ("fat_g", "total_fat_g", "ไขมัน", "g"),
    ("sodium_mg", "total_sodium_mg", "โซเดียม", "mg"),
    ("potassium_mg", "total_potassium_mg", "โพแทสเซียม", "mg"),
    ("phosphorus_mg", "total_phosphorus_mg", "ฟอสฟอรัส", "mg"),
]
DISEASE_TH = {"diabetes": "เบาหวาน", "hypertension": "ความดันโลหิตสูง", "ckd": "โรคไต",
              "heart": "โรคหัวใจ", "obesity": "โรคอ้วน"}
MEAL_TH = {"breakfast": "มื้อเช้า", "lunch": "มื้อเที่ยง", "dinner": "มื้อเย็น",
           "snack": "ของว่าง", "unknown": "ไม่ระบุมื้อ"}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def nutrient_keys(diseases) -> list[tuple]:
    """โพแทสเซียม/ฟอสฟอรัสแสดงเฉพาะผู้ป่วยไต (คนทั่วไป/ความดันไม่ต้องจำกัด)"""
    ds = set(diseases or [])
    return [n for n in NUTRIENTS if n[0] not in ("potassium_mg", "phosphorus_mg") or "ckd" in ds]


# ── เกณฑ์ ขาด / พอดี / เกิน (สัดส่วนของเป้าต่อวัน) ─────────────────────────
def _bounds(key: str, ds: set) -> tuple[float | None, float]:
    """(ต่ำกว่านี้ = ขาด, สูงกว่านี้ = เกิน) — None = ไม่มีเกณฑ์ขาด (ยิ่งน้อยยิ่งดี)"""
    if key == "energy_kcal":
        return 0.85, 1.10
    if key == "carb_available_g":
        return (None if "diabetes" in ds else 0.70), 1.10
    if key == "protein_g":
        return (None if "ckd" in ds else 0.80), (1.10 if "ckd" in ds else 1.50)
    if key == "fat_g":
        return None, 1.10
    return None, 1.00                     # โซเดียม / โพแทสเซียม / ฟอสฟอรัส = เพดาน


def status_of(key: str, value: float, target: float, ds: set) -> str:
    if target <= 0:
        return "ok"
    lo, hi = _bounds(key, ds)
    r = value / target
    if r > hi:
        return "high"
    if lo is not None and r < lo:
        return "low"
    return "ok"


ADVICE = {
    ("energy_kcal", "low"): "กินน้อยกว่าเป้า อาจทำให้อ่อนเพลียหรือกล้ามเนื้อลดลง ลองกินให้ครบ 3 มื้อ ไม่ข้ามมื้อ",
    ("energy_kcal", "high"): "พลังงานเกินเป้า ลองลดขนาดจาน (เลือก 'จานเล็ก') เลี่ยงของทอด/ของหวาน และเครื่องดื่มหวาน",
    ("carb_available_g", "low"): "คาร์บน้อยไป อาจหิวบ่อยหรือเพลีย เพิ่มข้าวกล้อง/ธัญพืชไม่ขัดสีในมื้อหลัก",
    ("carb_available_g", "high"): "คาร์บเกิน ลดข้าว/เส้น/ขนมปังลง เพิ่มผักให้ได้ครึ่งจาน (สูตรจาน 2:1:1)",
    ("protein_g", "low"): "โปรตีนน้อยไป เพิ่มเนื้อปลา ไข่ เต้าหู้ หรือเนื้อไก่ไม่ติดหนังในทุกมื้อ",
    ("protein_g", "high"): "โปรตีนมากเกินไป ลดปริมาณเนื้อสัตว์ต่อมื้อลง",
    ("fat_g", "high"): "ไขมันเกิน เลี่ยงของทอด แกงกะทิ หนังสัตว์ เปลี่ยนเป็นต้ม นึ่ง ย่าง",
    ("sodium_mg", "high"): "โซเดียมเกิน ลดน้ำปลา ซีอิ๊ว ผงปรุงรส น้ำซุป และอาหารแปรรูป ชิมก่อนเติมเครื่องปรุง",
    ("potassium_mg", "high"): "โพแทสเซียมเกินสำหรับผู้ป่วยไต เลี่ยงกล้วย ฝรั่ง ทุเรียน ผักใบเขียวเข้ม เลือกแอปเปิ้ล ชมพู่ สับปะรดแทน",
    ("phosphorus_mg", "high"): "ฟอสฟอรัสเกินสำหรับผู้ป่วยไต ลดนม ถั่ว และอาหารแปรรูปที่เติมฟอสเฟต",
}

# ทำไมเรื่องนี้สำคัญกับโรคของผู้ใช้ (สั้นๆ อ้างอิงแนวทางที่ใช้ในระบบ)
WHY = {
    ("carb_available_g", "diabetes"): "คาร์บมีผลต่อระดับน้ำตาลในเลือดโดยตรง (แนวทางเบาหวาน 2566)",
    ("energy_kcal", "diabetes"): "คุมพลังงานช่วยคุมน้ำหนักและน้ำตาล ผู้ป่วยเบาหวานที่น้ำหนักเกินควรลดน้ำหนัก ≥5%",
    ("energy_kcal", "obesity"): "ลดพลังงาน 500 kcal/วัน ช่วยลดน้ำหนักได้ราว 0.5 กก./สัปดาห์",
    ("sodium_mg", "hypertension"): "โซเดียมทำให้ความดันสูงขึ้น ควรไม่เกิน 1,500-2,000 mg/วัน (แนวทางความดัน 2567)",
    ("sodium_mg", "ckd"): "โซเดียมสูงทำให้บวมและไตทำงานหนัก (สมาคมโรคไตฯ แนะนำ < 2,000 mg/วัน)",
    ("sodium_mg", "heart"): "โซเดียมเพิ่มภาระหัวใจและความดัน",
    ("fat_g", "heart"): "ไขมันอิ่มตัวเพิ่ม LDL คอเลสเตอรอล เสี่ยงหลอดเลือดหัวใจ",
    ("protein_g", "ckd"): "โปรตีนมากทำให้ไตทำงานหนัก แนะนำ 0.6-0.8 g/กก. น้ำหนักอุดมคติ (สมาคมโรคไตฯ)",
    ("potassium_mg", "ckd"): "ไตเสื่อมขับโพแทสเซียมได้น้อย ระดับสูงอันตรายต่อหัวใจ",
    ("phosphorus_mg", "ckd"): "ฟอสฟอรัสสะสมทำให้กระดูกเปราะและหลอดเลือดแข็ง",
}

# เรื่องไหนสำคัญกับโรคไหน (ใช้เรียงลำดับและเน้นสี)
CRITICAL = {
    "diabetes": {"carb_available_g", "energy_kcal"},
    "hypertension": {"sodium_mg"},
    "ckd": {"sodium_mg", "protein_g", "potassium_mg", "phosphorus_mg"},
    "heart": {"sodium_mg", "fat_g"},
    "obesity": {"energy_kcal", "fat_g"},
}


def _day_rows(summary_rows: list[dict], today: dt.date, n: int) -> list[dict]:
    by_date = {r["log_date"]: r for r in summary_rows}
    out = []
    for i in range(n - 1, -1, -1):
        d = today - dt.timedelta(days=i)
        r = by_date.get(d, {})
        out.append({"date": d, "meal_count": int(r.get("meal_count") or 0),
                    **{k2: _f(r.get(k2)) for _, k2, _, _ in NUTRIENTS}})
    return out


def analyze_week(days: list[dict], daily_limit: dict, diseases) -> dict:
    """days = 7 วัน (เก่า→ใหม่) ผลวิเคราะห์ + คำแนะนำ"""
    ds = set(diseases or [])
    logged = [d for d in days if d["meal_count"] > 0]
    full = [d for d in logged if d["meal_count"] >= 2]      # วันที่บันทึกครบพอจะเฉลี่ย
    basis = full or logged
    res = {"days_logged": len(logged), "days_total": len(days),
           "avg_meals": round(sum(d["meal_count"] for d in logged) / len(logged), 1) if logged else 0,
           "basis_days": len(basis), "findings": [], "verdict": "nodata", "headline": "", "tips": []}
    if not basis:
        res["headline"] = "สัปดาห์นี้ยังไม่มีบันทึกการกิน ลองบันทึกให้ได้อย่างน้อยวันละ 2 มื้อ ระบบจะวิเคราะห์ให้"
        return res

    for key, k2, name, unit in nutrient_keys(ds):
        target = _f(daily_limit.get(key))
        if target <= 0:
            continue
        avg = sum(d[k2] for d in basis) / len(basis)
        st = status_of(key, avg, target, ds)
        days_over = sum(1 for d in basis if status_of(key, d[k2], target, ds) == "high")
        crit_for = [x for x in ds if key in CRITICAL.get(x, set())]
        f = {"key": key, "name": name, "unit": unit, "avg": round(avg, 1), "target": round(target, 1),
             "pct": round(avg / target * 100), "status": st, "days_over": days_over,
             "critical": bool(crit_for), "advice": ADVICE.get((key, st), ""),
             "why": next((WHY[(key, x)] for x in crit_for if (key, x) in WHY), "")}
        res["findings"].append(f)

    bad = [f for f in res["findings"] if f["status"] != "ok"]
    bad_crit = [f for f in bad if f["critical"]]
    # เรียง: เรื่องที่สำคัญต่อโรค + ไม่ผ่าน ขึ้นก่อน
    res["findings"].sort(key=lambda f: (f["status"] == "ok", not f["critical"], -abs(f["pct"] - 100)))
    if not bad:
        res["verdict"], verdict_th = "good", "ดีมาก"
    elif len(bad_crit) == 0 and len(bad) <= 2:
        res["verdict"], verdict_th = "fair", "พอใช้"
    else:
        res["verdict"], verdict_th = "poor", "ควรปรับ"

    dn = "และ".join(DISEASE_TH[d] for d in ds if d in DISEASE_TH)
    if res["verdict"] == "good":
        res["headline"] = (f"สัปดาห์นี้กินได้ตามเป้าทุกด้าน{' เหมาะกับ' + dn if dn else ''} ทำต่อแบบนี้เลย 👍")
    else:
        parts = [f"{f['name']}{'เกิน' if f['status'] == 'high' else 'ขาด'}" for f in (bad_crit or bad)[:3]]
        res["headline"] = (f"ภาพรวม{verdict_th}: " + ", ".join(parts)
                           + (f" — เรื่องนี้สำคัญกับ{dn}" if bad_crit and dn else ""))
    res["tips"] = [f["advice"] for f in (bad_crit + [b for b in bad if b not in bad_crit])[:3] if f["advice"]]
    if len(logged) < 5:
        res["tips"].append(f"บันทึกไป {len(logged)}/7 วัน ลองบันทึกทุกวันให้ครบทุกมื้อ ผลวิเคราะห์จะแม่นขึ้น")
    return res


def build_payload(user: dict, targets: dict, summary_rows: list[dict], logs: list[dict],
                  today: dt.date) -> dict:
    ds = list(user.get("diseases") or [])
    dl = targets["daily_limit"]
    rows14 = _day_rows(summary_rows, today, 14)
    show = rows14[-SHOW_DAYS:]
    this_week, prev_week = rows14[-WEEK:], rows14[:WEEK]

    meals_by_day: dict = {}
    for lg in logs:
        d = lg["log_date"]
        meals_by_day.setdefault(d.isoformat(), []).append({
            "meal": MEAL_TH.get(str(lg.get("meal_type")), "ไม่ระบุมื้อ"),
            "meal_type": str(lg.get("meal_type")),
            "name": lg.get("food_name_th"), "kcal": round(_f(lg.get("energy_kcal"))),
            "portion": lg.get("portion"),
        })

    keys = nutrient_keys(ds)
    days_out = []
    for d in show:
        nutrients = []
        for key, k2, name, unit in keys:
            tgt = _f(dl.get(key))
            nutrients.append({"key": key, "name": name, "unit": unit, "value": round(d[k2], 1),
                              "target": round(tgt, 1),
                              "status": status_of(key, d[k2], tgt, set(ds)) if d["meal_count"] else "none"})
        days_out.append({"date": d["date"].isoformat(), "meal_count": d["meal_count"],
                         "nutrients": nutrients, "meals": meals_by_day.get(d["date"].isoformat(), [])})

    week = analyze_week(this_week, dl, ds)
    prev = analyze_week(prev_week, dl, ds)

    def _avg(rows, k2):
        lg = [r for r in rows if r["meal_count"] > 0]
        return round(sum(r[k2] for r in lg) / len(lg)) if lg else None

    compare = {
        "kcal_this": _avg(this_week, "total_energy_kcal"), "kcal_prev": _avg(prev_week, "total_energy_kcal"),
        "na_this": _avg(this_week, "total_sodium_mg"), "na_prev": _avg(prev_week, "total_sodium_mg"),
        "prev_verdict": prev["verdict"],
    }
    return {
        "user": {"name": user.get("name") or "", "diseases": [DISEASE_TH.get(x, x) for x in ds],
                 "bmi": targets.get("bmi")},
        "targets": {k: round(_f(dl.get(k)), 1) for k, *_ in keys},
        "today": today.isoformat(),
        "days": days_out,
        "week": week,
        "week_chart": [{"date": d["date"].isoformat(), "kcal": round(d["total_energy_kcal"]),
                        "logged": d["meal_count"] > 0} for d in this_week],
        "compare": compare,
    }
