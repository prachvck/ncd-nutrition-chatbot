"""
eval/usage_report.py — วัดประสิทธิภาพแชทบอทจากการใช้งานจริง (ผู้ทดสอบ) [DEV_LOG Entry 64]

ข้อมูลทั้งหมดมาจาก log ที่แอปบันทึกให้อัตโนมัติ (ไม่ต้องถามผู้ใช้):
  interaction_logs        ทุกข้อความ: route, fallback, ข้อความที่บอทตอบ, เวลาตอบ
  food_logs.source        typed / button / image
  food_image_predictions  ผล CNN + ผู้ใช้กดยืนยัน/ยกเลิก

ตัวชี้วัด (อ้างอิงใน docs/REFERENCES.md หัวข้อ 4ก):
  1) Fallback rate        — สัดส่วนข้อความที่บอทตอบไม่ได้ (Abd-Alrazaq 2020; Li et al. CHI 2020)
       hard = ช่วยไม่ได้จริง (ไม่เข้าใจ / หาเมนูไม่เจอ / error ...)
       soft = ต้องถามกลับให้ผู้ใช้เลือก (ไม่ได้ผิด แต่ไม่ได้ตอบทันที)
  2) Task completion      — ผู้ทดสอบทำงานในสคริปต์สำเร็จกี่งาน (Casas 2020: effectiveness)
  3) ความแม่น CNN ตอนใช้จริง — Top-1 / Top-3 จากที่ผู้ใช้กดยืนยัน
  4) เวลาตอบ              — server_ms (Casas 2020: efficiency)

รัน:
  python -m eval.usage_report --since 2026-11-01 --exclude Uxxxx(ไอดีของผู้พัฒนา)
  python -m eval.usage_report --since 2026-11-01 --csv eval/results/usage_tasks.csv
  ดูไอดีตัวเอง: python -m eval.usage_report --list-users
"""
import os, sys, argparse, asyncio, csv, json, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HARD = {"unknown_intent": "ไม่เข้าใจว่าต้องการอะไร", "parse_fail": "ไม่เข้าใจว่ากินอะไร",
        "food_not_found": "หาเมนูในฐานข้อมูลไม่เจอ", "confirm_unclear": "ตอบยืนยันไม่ตรงปุ่ม",
        "cnn_unavailable": "ระบบรูปภาพไม่พร้อม", "error": "ระบบผิดพลาด",
        "unsupported": "ขอสิ่งที่ระบบยังไม่รองรับ (เช่น ออกกำลังกาย)"}
SOFT = {"disambiguation": "ถามกลับให้เลือกเจตนา", "partial_match": "ใช้เมนูใกล้เคียงแทน (เตือนผู้ใช้)",
        "cnn_low_conf": "รูปไม่ชัด ให้เลือกจาก 3 อันดับ", "cnn_corrected": "ผู้ใช้พิมพ์แก้ผลจากรูป",
        "food_generic": "ชื่ออาหารกว้างไป ถามกลับ", "food_not_in_db": "ไม่มีในฐาน ตอบจากความรู้ทั่วไป"}

TASKS = [
    ("profile",   "1. กรอกโปรไฟล์สุขภาพ"),
    ("rec_eat",   "2. ขอแนะนำอาหาร แล้วกดกินเมนูที่แนะนำ"),
    ("typed_log", "3. พิมพ์บันทึกการกินเอง"),
    ("image_log", "4. ส่งรูปอาหารให้บันทึก"),
    ("ask",       "5. ถามแคล/ถามว่ากินได้ไหม (บอทตอบได้)"),
    ("dashboard", "6. เปิดดูสรุปย้อนหลัง (Dashboard)"),
]


def _pct(a, b):
    return f"{a / b:.1%}" if b else "-"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="YYYY-MM-DD (ค่าเริ่มต้น 30 วันล่าสุด)")
    ap.add_argument("--until", default=None, help="YYYY-MM-DD (ไม่รวมวันนี้)")
    ap.add_argument("--exclude", nargs="*", default=[], help="LINE user id ที่ไม่นับ (ผู้พัฒนา)")
    ap.add_argument("--csv", default=None, help="บันทึกผล task รายคนเป็น CSV")
    ap.add_argument("--list-users", action="store_true")
    a = ap.parse_args()
    since = dt.date.fromisoformat(a.since) if a.since else dt.date.today() - dt.timedelta(days=30)
    until = dt.date.fromisoformat(a.until) if a.until else dt.date.today() + dt.timedelta(days=1)
    excl = list(a.exclude) + [u for u in os.getenv("EVAL_EXCLUDE_UIDS", "").split(",") if u]

    from db.database import get_pool, init_db
    await init_db()                       # ให้แน่ใจว่าคอลัมน์ใหม่ (Entry 64) มีแล้ว
    pool = await get_pool()
    W = "created_at >= $1 AND created_at < $2 AND NOT (line_user_id = ANY($3::text[]))"
    args = (dt.datetime.combine(since, dt.time()).astimezone(),
            dt.datetime.combine(until, dt.time()).astimezone(), excl)
    async with pool.acquire() as c:
        if a.list_users:
            for r in await c.fetch(f"""SELECT u.line_user_id, u.name, COUNT(i.id) n
                FROM users u LEFT JOIN interaction_logs i ON i.line_user_id=u.line_user_id
                GROUP BY 1,2 ORDER BY n DESC"""):
                print(f"{r['line_user_id']}  {r['name'] or '-':20s} {r['n']} ข้อความ")
            return
        msgs = [dict(r) for r in await c.fetch(f"""
            SELECT line_user_id, event_type, route, fallback, error, server_ms, cnn_ms
            FROM interaction_logs WHERE {W}""", *args)]
        logs = [dict(r) for r in await c.fetch(f"""
            SELECT line_user_id, source, recommendation_item_id FROM food_logs
            WHERE eaten_at >= $1 AND eaten_at < $2 AND NOT (line_user_id = ANY($3::text[]))""", *args)]
        users = [dict(r) for r in await c.fetch("""
            SELECT line_user_id, name, weight_kg, height_cm FROM users
            WHERE NOT (line_user_id = ANY($1::text[]))""", excl)]
        preds = [dict(r) for r in await c.fetch(f"""
            SELECT predicted_food_id, top3, confirmed, confirmed_food_id
            FROM food_image_predictions WHERE {W}""", *args)]

    user_msgs = [m for m in msgs if m["event_type"] != "liff"]
    active = sorted({m["line_user_id"] for m in user_msgs})
    print(f"ช่วง {since} ถึง {until - dt.timedelta(days=1)}  | ผู้ใช้ที่มีข้อความ {len(active)} คน"
          f" | ข้อความทั้งหมด {len(user_msgs)} | ไม่นับ {len(excl)} ไอดี")
    if not user_msgs:
        print("ยังไม่มีข้อมูลในช่วงนี้ (ให้ผู้ทดสอบใช้งานใน LINE ก่อน)")
        return

    # ── 1) Fallback rate ─────────────────────────────────────────────
    n = len(user_msgs)
    hard = [m for m in user_msgs if m["fallback"] in HARD]
    soft = [m for m in user_msgs if m["fallback"] in SOFT]
    print("\n── 1) Fallback rate (บอทตอบไม่ได้ทันที) ──")
    print(f"ตอบได้ทันที          {n - len(hard) - len(soft):5d}  {_pct(n - len(hard) - len(soft), n)}")
    print(f"hard fallback        {len(hard):5d}  {_pct(len(hard), n)}   ← ช่วยผู้ใช้ไม่ได้")
    print(f"soft fallback        {len(soft):5d}  {_pct(len(soft), n)}   ← ถามกลับให้เลือก")
    for k, name in {**HARD, **SOFT}.items():
        cnt = sum(m["fallback"] == k for m in user_msgs)
        if cnt:
            print(f"   {name:34s} {cnt:4d}  {_pct(cnt, n)}")

    # ── 2) Task completion ───────────────────────────────────────────
    done = {u: set() for u in active}
    prof = {u["line_user_id"] for u in users if u["weight_kg"] and u["height_cm"]}
    for u in active:
        if u in prof:
            done[u].add("profile")
    for l in logs:
        u = l["line_user_id"]
        if u not in done:
            continue
        if l["recommendation_item_id"]:
            done[u].add("rec_eat")
        if l["source"] == "typed":
            done[u].add("typed_log")
        if l["source"] == "image":
            done[u].add("image_log")
    for m in msgs:
        u = m["line_user_id"]
        if u not in done:
            continue
        r = m["route"] or ""
        if "ask_calorie" in r and not m["fallback"] and not m["error"]:
            done[u].add("ask")
        if r == "dashboard":
            done[u].add("dashboard")
    print(f"\n── 2) Task completion ({len(active)} คน × {len(TASKS)} งาน) ──")
    total = sum(len(v) for v in done.values())
    for key, name in TASKS:
        cnt = sum(key in v for v in done.values())
        print(f"{name:44s} {cnt:3d}/{len(active)}  {_pct(cnt, len(active))}")
    print(f"{'รวมทุกงาน':44s} {total:3d}/{len(active) * len(TASKS)}  {_pct(total, len(active) * len(TASKS))}")
    full = sum(len(v) == len(TASKS) for v in done.values())
    print(f"{'ทำครบทุกงาน':44s} {full:3d}/{len(active)}  {_pct(full, len(active))}")

    # ── 3) CNN จากรูปจริง ────────────────────────────────────────────
    print(f"\n── 3) ความแม่น CNN จากรูปที่ผู้ใช้ส่งจริง ({len(preds)} รูป) ──")
    res = [p for p in preds if p["confirmed"] is not None]
    if res:
        top1 = sum(p["confirmed"] and p["confirmed_food_id"] == p["predicted_food_id"] for p in res)
        def _in3(p):
            t = p["top3"] if isinstance(p["top3"], list) else json.loads(p["top3"] or "[]")
            return p["confirmed"] and p["confirmed_food_id"] in {x.get("food_id") for x in t}
        top3 = sum(_in3(p) for p in res)
        print(f"ผู้ใช้ตอบ (ยืนยัน/ยกเลิก)  {len(res)} รูป  (ไม่ได้ตอบ {len(preds) - len(res)})")
        print(f"Top-1 ถูก (ยืนยันเมนูที่ทายอันดับ 1)   {top1}/{len(res)}  {_pct(top1, len(res))}")
        print(f"Top-3 ถูก (ยืนยันเมนูใน 3 อันดับ)     {top3}/{len(res)}  {_pct(top3, len(res))}")
        print(f"ผู้ใช้กดยกเลิก (ไม่ใช่เมนูนี้)          {sum(not p['confirmed'] for p in res)}")
        print("หมายเหตุ: รูปที่ไม่อยู่ใน 100 เมนูของ THFOOD-100 จะนับเป็นผิดด้วย")
    else:
        print("ยังไม่มีรูปที่ผู้ใช้กดยืนยัน/ยกเลิก")

    # ── 4) เวลาตอบ ───────────────────────────────────────────────────
    import numpy as np
    print("\n── 4) เวลาตอบ (server_ms) ──")
    for name, rows in (("ทุกข้อความ", user_msgs),
                       ("ส่งรูป (รวม CNN)", [m for m in user_msgs if m["event_type"] == "image"])):
        v = np.array([m["server_ms"] for m in rows if m["server_ms"] is not None], float)
        if len(v):
            print(f"{name:18s} n={len(v):4d} เฉลี่ย {v.mean() / 1000:.2f} วิ  มัธยฐาน {np.median(v) / 1000:.2f}"
                  f"  p90 {np.percentile(v, 90) / 1000:.2f}  <5 วิ {(v < 5000).mean():.0%}")
    c = np.array([m["cnn_ms"] for m in user_msgs if m.get("cnn_ms")], float)
    if len(c):
        print(f"{'เฉพาะ CNN':18s} n={len(c):4d} เฉลี่ย {c.mean() / 1000:.2f} วิ")

    if a.csv:
        os.makedirs(os.path.dirname(a.csv) or ".", exist_ok=True)
        names = {u["line_user_id"]: u["name"] for u in users}
        with open(a.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["user_id", "name"] + [k for k, _ in TASKS] + ["tasks_done"])
            for u, v in done.items():
                w.writerow([u, names.get(u, "")] + [int(k in v) for k, _ in TASKS] + [len(v)])
        print(f"\nบันทึกผลรายคน → {a.csv}")


if __name__ == "__main__":
    asyncio.run(main())
