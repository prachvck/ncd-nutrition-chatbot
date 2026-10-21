"""
eval/review_replies.py — หาคำตอบที่น่าสงสัยจาก log การใช้งานจริง [DEV_LOG Entry 71]

fallback rate (eval/usage_report.py) นับได้แค่ตอนที่บอท "รู้ตัว" ว่าตอบไม่ได้ แต่คำตอบที่ผิดโดยไม่รู้ตัว
(เช่น "ไข่เจียวใส่เยลลี่หมี" ได้ค่าของไข่เจียวธรรมดา หรือ LLM แต่งตัวเลขแคลเอง) ต้องอ่าน reply_text
สคริปต์นี้คัดข้อความที่ควรให้คนตรวจก่อน แทนการอ่านทุกข้อความ:

  kcal_mismatch   ถามแคล/บันทึก แล้วตัวเลข kcal ในคำตอบไม่ตรงกับฐานข้อมูล (±15% รวมขนาดจานเล็ก/ใหญ่)
  partial_silent  ฐานข้อมูลใช้จานใกล้เคียง แต่คำตอบไม่ได้บอกผู้ใช้ ("ไม่พบ"/"ใกล้เคียง")
  fallback        บอทตอบไม่ได้ (hard/soft) — ดูว่าควรรองรับไหม
  error           ระบบผิดพลาด
  slow            ใช้เวลาเกิน 8 วินาที
  retry           ผู้ใช้พิมพ์ข้อความเดิม/คล้ายเดิมซ้ำภายใน 2 นาที (บอทตอบไม่ถูกใจ)
  odd_text        คำตอบมีตัวอักษรจีน/ญี่ปุ่น/เกาหลี หรือยาวผิดปกติ

รัน:
  python -m eval.review_replies --since 2026-11-01 --exclude <ไอดีผู้พัฒนา>
  python -m eval.review_replies --csv eval/results/log_il.csv      (ไฟล์ที่ export จาก docker)
ผล: eval/results/review_<วันเวลา>.csv — มีคอลัมน์ human_ok ว่างไว้ให้กรอกตอนตรวจ
"""
import os, sys, re, csv, argparse, asyncio, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("USE_TF", "0")

CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
KCAL = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:kcal|กิโลแคลอรี่|กิโลแคลอรี|แคลอรี่|แคล)")
PARTIAL_WORDS = ("ไม่พบ", "ใกล้เคียง", "ไม่มีในระบบ", "ไม่มีข้อมูล")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


async def _load_db(since, excl):
    from db.database import get_pool, init_db
    await init_db()
    pool = await get_pool()
    async with pool.acquire() as c:
        rows = await c.fetch("""
            SELECT id, line_user_id, event_type, input_text, route, intent, fallback, error,
                   server_ms, reply_text, created_at
            FROM interaction_logs
            WHERE created_at >= $1 AND NOT (line_user_id = ANY($2::text[])) AND event_type <> 'liff'
            ORDER BY created_at""", dt.datetime.combine(since, dt.time()).astimezone(), excl)
    return [dict(r) for r in rows]


def _load_csv(path, excl):
    with open(path, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r.get("line_user_id") not in excl
                and r.get("event_type") != "liff"]
    for r in rows:
        r["error"] = str(r.get("error", "")).lower() in ("t", "true", "1")
        ts = re.sub(r"\.\d+", "", str(r["created_at"])).replace("+00", "")   # ตัดเศษวินาที/โซนเวลา (py3.10)
        r["created_at"] = dt.datetime.fromisoformat(ts.strip())
    return rows


def review(rows, model):
    from app.state import extract_food_keyword, is_generic_food_term
    flagged = []
    last = {}
    for r in rows:
        reasons = []
        txt = r.get("input_text") or ""
        reply = r.get("reply_text") or ""
        route = r.get("route") or ""
        if r.get("error"):
            reasons.append("error")
        if r.get("fallback"):
            reasons.append(f"fallback:{r['fallback']}")
        ms = _f(r.get("server_ms"))
        if ms and ms > 8000:
            reasons.append(f"slow:{ms / 1000:.1f}s")
        if reply and (CJK.search(reply) or len(reply) > 1500):
            reasons.append("odd_text")
        # ผู้ใช้พิมพ์ซ้ำ
        u = r.get("line_user_id")
        prev = last.get(u)
        if prev and txt and not txt.startswith("__") and txt not in ("ยืนยัน", "ยกเลิก"):
            gap = (r["created_at"] - prev[1]).total_seconds()
            a, b = set(txt.replace(" ", "")), set(prev[0].replace(" ", ""))
            sim = len(a & b) / max(1, len(a | b))
            if gap < 120 and sim > 0.8:
                reasons.append("retry")
        if txt:
            last[u] = (txt, r["created_at"])
        # ตรวจตัวเลข kcal กับฐานข้อมูล
        db_food = None
        if reply and ("ask_calorie" in route or "log_meal" in route):
            kw = extract_food_keyword(txt) if "ask_calorie" in route else txt
            for w in ("กิน", "ทาน", "แดก", "มื้อเช้า", "มื้อเที่ยง", "มื้อเย็น", "ตอนเที่ยง", "ตอนเช้า", "ตอนเย็น", "ไป"):
                kw = kw.replace(w, "") if "log_meal" in route else kw
            if kw and not is_generic_food_term(kw):
                res = model.search_food(kw.strip(), 1)
                if res:
                    db_food = res[0]
        if db_food:
            nums = [float(x.replace(",", "")) for x in KCAL.findall(reply)]
            e = db_food["energy_kcal"]
            ok = any(abs(n - e * m) <= 0.15 * e * m for n in nums for m in (0.75, 1.0, 1.35)) if nums else True
            if nums and not ok:
                reasons.append(f"kcal_mismatch: ตอบ {nums[:3]} / ฐาน {e:.0f} ({db_food['food_name_th']})")
            if db_food.get("_match") == "partial" and not any(w in reply for w in PARTIAL_WORDS):
                reasons.append(f"partial_silent: ใช้ค่าของ {db_food['food_name_th']}")
        if reasons:
            flagged.append({"created_at": str(r["created_at"])[:19], "user": u, "route": route,
                            "input": txt[:200], "reply": reply[:600], "reasons": " | ".join(reasons),
                            "human_ok": ""})
    return flagged


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None)
    ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--csv", default=None, help="ใช้ไฟล์ log ที่ export แทนการต่อ DB")
    a = ap.parse_args()
    excl = list(a.exclude) + [x for x in os.getenv("EVAL_EXCLUDE_UIDS", "").split(",") if x]
    since = dt.date.fromisoformat(a.since) if a.since else dt.date.today() - dt.timedelta(days=30)
    rows = _load_csv(a.csv, excl) if a.csv else await _load_db(since, excl)
    if not rows:
        print("ไม่มีข้อความในช่วงนี้"); return
    from ml.pipeline import NCDModel
    model = NCDModel(csv_path=os.getenv("CSV_PATH", "foods_master_v2.csv"))
    flagged = review(rows, model)
    with_reply = sum(1 for r in rows if r.get("reply_text"))
    print(f"ข้อความ {len(rows)} (มี reply_text {with_reply}) → ควรตรวจ {len(flagged)} ข้อความ")
    if with_reply == 0:
        print("หมายเหตุ: ไม่มี reply_text (log ก่อน Entry 64) ตรวจได้แค่ fallback/error/slow/retry")
    cnt = {}
    for f in flagged:
        for reason in f["reasons"].split(" | "):
            k = reason.split(":")[0]
            cnt[k] = cnt.get(k, 0) + 1
    for k, v in sorted(cnt.items(), key=lambda kv: -kv[1]):
        print(f"  {k:16s} {v}")
    for f in flagged[:15]:
        print(f"\n[{f['created_at']}] {f['route']} — {f['reasons']}\n  ผู้ใช้: {f['input'][:80]}\n  บอท: {f['reply'][:160]}")
    os.makedirs("eval/results", exist_ok=True)
    out = f"eval/results/review_{dt.datetime.now():%Y%m%d_%H%M}.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(flagged[0].keys()) if flagged else ["none"])
        w.writeheader(); w.writerows(flagged)
    print(f"\nบันทึก → {out}  (กรอก human_ok = 1 ถูก / 0 ผิด ตอนตรวจ)")


if __name__ == "__main__":
    asyncio.run(main())
