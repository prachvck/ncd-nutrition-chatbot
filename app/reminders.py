"""
app/reminders.py — แจ้งเตือนมื้ออาหาร + สรุปเป้าหมายรายสัปดาห์ผ่าน LINE push [DEV_LOG Entry 54]
(รายงาน Project 1 บทที่ 5.4 ข้อ 6)

- ผู้ใช้เปิดเอง: พิมพ์ "เปิดแจ้งเตือน" / "ปิดแจ้งเตือน" / "ตั้งเวลาเที่ยง 12:30"
  (ปิดไว้เป็นค่าเริ่มต้น เพราะ push message ของ LINE OA มีโควตาฟรีต่อเดือนจำกัด)
- ลูปเบื้องหลังในแอปเช็คทุก 60 วินาที (เวลาไทย):
    มื้อเช้า/เที่ยง/เย็น — ถึงเวลาที่ตั้ง (หน้าต่าง 60 นาที) และยังไม่ได้บันทึกมื้อนั้น → ส่งเตือน 1 ครั้ง/วัน
    วันอาทิตย์ 19:00 — สรุป 7 วันที่ผ่านมาเทียบเป้า
- กันส่งซ้ำด้วย UPDATE ... RETURNING ใน DB (รันหลาย worker/หลายเครื่องก็ไม่ส่งซ้ำ)
- ปิดทั้งระบบได้ด้วย REMINDERS_ENABLED=0
"""
from __future__ import annotations

import os
import re
import asyncio
import logging
import datetime as dt

log = logging.getLogger(__name__)

CHECK_EVERY_S = 60
MEAL_TH = {"breakfast": "มื้อเช้า", "lunch": "มื้อเที่ยง", "dinner": "มื้อเย็น"}
MEAL_WORD = {"เช้า": "breakfast", "เที่ยง": "lunch", "กลางวัน": "lunch", "เย็น": "dinner", "ค่ำ": "dinner"}
SET_TIME_RE = re.compile(r"^ตั้งเวลา(?:แจ้งเตือน)?\s*(?:มื้อ)?(เช้า|เที่ยง|กลางวัน|เย็น|ค่ำ)\s*(\d{1,2})[:.](\d{2})\s*(?:น\.?)?$")

CMD_ON = {"เปิดแจ้งเตือน", "เปิดการแจ้งเตือน", "เตือนมื้ออาหาร"}
CMD_OFF = {"ปิดแจ้งเตือน", "ปิดการแจ้งเตือน", "ไม่ต้องเตือน"}
CMD_STATUS = {"แจ้งเตือน", "ตั้งค่าแจ้งเตือน", "การแจ้งเตือน"}


def enabled_globally() -> bool:
    return os.getenv("REMINDERS_ENABLED", "1") == "1"


def _fmt(t) -> str:
    return t.strftime("%H:%M") if t else "-"


def status_text(r: dict | None) -> str:
    if not r or not r.get("enabled"):
        return ("ตอนนี้ปิดการแจ้งเตือนอยู่ครับ\n"
                "พิมพ์ 'เปิดแจ้งเตือน' เพื่อให้เตือนมื้อเช้า 07:30 เที่ยง 12:00 เย็น 18:00 "
                "และสรุปรายสัปดาห์ทุกวันอาทิตย์")
    return ("เปิดการแจ้งเตือนอยู่ครับ ⏰\n"
            f"มื้อเช้า {_fmt(r['breakfast_time'])} · เที่ยง {_fmt(r['lunch_time'])} · "
            f"เย็น {_fmt(r['dinner_time'])}\n"
            "จะเตือนเฉพาะมื้อที่ยังไม่ได้บันทึก + สรุปรายสัปดาห์ทุกวันอาทิตย์ 19:00\n"
            "เปลี่ยนเวลา เช่น 'ตั้งเวลาเที่ยง 12:30' · ปิด พิมพ์ 'ปิดแจ้งเตือน'")


async def handle_command(uid: str, text: str):
    """คืน list ข้อความตอบกลับ ถ้าเป็นคำสั่งแจ้งเตือน ไม่ใช่ → None"""
    from db.database import get_reminder, set_reminder
    from app.line_reply import text_msg, quick_reply
    t = text.strip()
    if t in CMD_ON:
        r = await set_reminder(uid, enabled=True)
        return [text_msg(status_text(r))]
    if t in CMD_OFF:
        r = await set_reminder(uid, enabled=False)
        return [text_msg("ปิดการแจ้งเตือนแล้วครับ เปิดใหม่ได้ด้วย 'เปิดแจ้งเตือน'")]
    if t in CMD_STATUS:
        r = await get_reminder(uid)
        on = bool(r and r.get("enabled"))
        return [quick_reply(status_text(r), [("ปิดแจ้งเตือน", "ปิดแจ้งเตือน")] if on
                            else [("เปิดแจ้งเตือน", "เปิดแจ้งเตือน")])]
    m = SET_TIME_RE.match(t)
    if m:
        hh, mm = int(m.group(2)), int(m.group(3))
        if hh > 23 or mm > 59:
            return [text_msg("เวลาไม่ถูกต้องครับ ตัวอย่าง: 'ตั้งเวลาเที่ยง 12:30'")]
        r = await set_reminder(uid, meal=MEAL_WORD[m.group(1)], at=dt.time(hh, mm))
        return [text_msg(status_text(r))]
    return None


def meal_reminder_message(meal: str) -> dict:
    from app.line_reply import quick_reply_postback
    return quick_reply_postback(
        f"ถึงเวลา{MEAL_TH[meal]}แล้วครับ 🍽️ ให้ช่วยแนะนำเมนูที่เหมาะกับคุณไหม\n"
        f"ถ้ากินไปแล้ว บันทึกไว้ด้วยนะครับ จะได้คุมเป้าหมายวันนี้ได้",
        [("แนะนำอาหาร", f"__meal__:{meal}", f"แนะนำ{MEAL_TH[meal]}"),
         ("บันทึกการกิน", "บันทึกการกิน", "บันทึกการกิน"),
         ("ปิดแจ้งเตือน", "ปิดแจ้งเตือน", "ปิดแจ้งเตือน")])


def weekly_summary_text(days: list[dict], daily_limit: dict, diseases: list) -> str:
    """days: แถวจาก daily_nutrition_summary (7 วันล่าสุด)"""
    goal = float(daily_limit.get("energy_kcal") or 0)
    na_lim = float(daily_limit.get("sodium_mg") or 0)
    n = len(days)
    if n == 0:
        return ("สรุปสัปดาห์นี้ 📅\nสัปดาห์นี้ยังไม่มีบันทึกการกินเลยครับ "
                "ลองกด 'แนะนำอาหาร' หรือพิมพ์บันทึกมื้อที่กินดูนะครับ")
    kcal = [float(d.get("total_energy_kcal") or 0) for d in days]
    on_target = sum(1 for k in kcal if goal and 0.9 * goal <= k <= 1.1 * goal)
    over_na = sum(1 for d in days if na_lim and float(d.get("total_sodium_mg") or 0) > na_lim)
    lines = [
        "สรุปสัปดาห์นี้ 📅",
        f"บันทึกการกิน {n}/7 วัน (รวม {sum(int(d.get('meal_count') or 0) for d in days)} มื้อ)",
        f"พลังงานเฉลี่ย {sum(kcal) / n:.0f} kcal/วัน (เป้า {goal:.0f})",
        f"วันที่พลังงานอยู่ในเป้า ±10%: {on_target}/{n} วัน",
        f"วันที่โซเดียมเกิน {na_lim:.0f} mg: {over_na}/{n} วัน",
    ]
    if "ckd" in (diseases or []):
        k_lim = float(daily_limit.get("potassium_mg") or 0)
        p_lim = float(daily_limit.get("phosphorus_mg") or 0)
        over_k = sum(1 for d in days if k_lim and float(d.get("total_potassium_mg") or 0) > k_lim)
        over_p = sum(1 for d in days if p_lim and float(d.get("total_phosphorus_mg") or 0) > p_lim)
        lines.append(f"วันที่โพแทสเซียมเกิน: {over_k}/{n} · ฟอสฟอรัสเกิน: {over_p}/{n} วัน")
    if "diabetes" in (diseases or []):
        c_lim = float(daily_limit.get("carb_available_g") or 0)
        over_c = sum(1 for d in days if c_lim and float(d.get("total_carb_g") or 0) > c_lim * 1.1)
        lines.append(f"วันที่คาร์บเกินเป้า: {over_c}/{n} วัน")
    tip = ("เยี่ยมมากครับ ทำต่อแบบนี้เลย 👍" if on_target >= max(n - 1, 1) and over_na == 0
           else "สัปดาห์หน้าลองบันทึกให้ครบทุกมื้อ และระวังอาหารรสเค็มนะครับ" if over_na
           else "สัปดาห์หน้าลองให้พลังงานแต่ละวันใกล้เป้ามากขึ้นนะครับ")
    lines.append(tip)
    return "\n".join(lines)


async def _tick(push, ncd_model):
    from db.database import (claim_due_meal_reminders, claim_due_weekly, get_week_summary,
                             get_user, REMINDER_MEALS)
    from app.line_reply import text_msg
    for meal in REMINDER_MEALS:
        for uid in await claim_due_meal_reminders(meal):
            try:
                await push(uid, [meal_reminder_message(meal)])
                log.info(f"[reminder] {meal} → {uid}")
            except Exception as e:
                log.warning(f"[reminder] push failed {uid}: {e}")
    for uid in await claim_due_weekly():
        try:
            user = await get_user(uid)
            if not user:
                continue
            tg = await asyncio.to_thread(ncd_model.compute_user_targets, user)
            days = await get_week_summary(uid)
            await push(uid, [text_msg(weekly_summary_text(days, tg["daily_limit"], user.get("diseases") or []))])
            log.info(f"[reminder] weekly → {uid}")
        except Exception as e:
            log.warning(f"[reminder] weekly failed {uid}: {e}")


async def run_loop(push, get_model):
    """เรียกจาก lifespan: asyncio.create_task(run_loop(_push, lambda: ncd_model))"""
    if not enabled_globally():
        log.info("Reminders: ปิดทั้งระบบ (REMINDERS_ENABLED=0)")
        return
    log.info("Reminders: เริ่มลูปแจ้งเตือน (เช็คทุก 60 วินาที)")
    while True:
        try:
            await _tick(push, get_model())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"Reminders tick error: {e}")
        await asyncio.sleep(CHECK_EVERY_S)
