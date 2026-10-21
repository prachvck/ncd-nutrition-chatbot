"""
eval/eval_meal_parse.py — วัด LLM แปลงข้อความบันทึกการกิน (รายงานบท 3.5.3 งานที่ 1) [DEV_LOG Entry 53]

ชุดทดสอบ: eval/meal_parse_testset.csv (50 ประโยค) — มีคำแสลง สะกดผิด ไม่ระบุมื้อ สองเมนู อังกฤษ
แต่ละข้อทำเหมือนแอปจริงทุกขั้น: parse_meal_text (Typhoon) → search_food(ชื่อที่ได้) → จานที่จะบันทึก

ตัวชี้วัด:
  - food_accuracy     : จานที่ระบบจะบันทึก (ค้นจากชื่อที่ LLM แยกได้) มีคำที่คาดไว้ = บันทึกถูกจาน
  - meal_type_accuracy: มื้อถูก (ข้อที่ไม่ระบุมื้อ ต้องได้ unknown — แอปจะเติมมื้อถัดไปให้เอง)
  - portion_accuracy  : ขนาดจานถูก (small/normal/large)
  - exact_match       : ถูกครบทั้ง 3 อย่าง
  - partial_match_rate: สัดส่วนที่ไม่เจอชื่อตรงตัว ใช้จานใกล้เคียงแทน (แอปเตือนผู้ใช้ก่อนยืนยัน)
  - low_confidence    : สัดส่วนที่ confidence < 0.4 (แอปจะขอให้พิมพ์ใหม่แทนการบันทึก)
  - เวลาเฉลี่ยต่อข้อความ

รัน:  python -m eval.eval_meal_parse      (ต้องมี TYPHOON_API_KEY)
"""
import os, sys, csv, json, time, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(override=True)

HERE = os.path.dirname(os.path.abspath(__file__))


def _norm(s):
    from ml.pipeline import _norm_name   # [Entry 56] รวมสะกดต่าง (กระเพรา/กะเพรา)
    return _norm_name(str(s or ""))


def main():
    from app.llm_service import parse_meal_text
    from ml.pipeline import NCDModel
    model = NCDModel(csv_path=os.getenv("CSV_PATH", "foods_master_v2.csv"))
    with open(os.path.join(HERE, "meal_parse_testset.csv"), encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    out, fails = [], 0
    for i, r in enumerate(rows, 1):
        t = time.perf_counter()
        p = parse_meal_text(r["text"])
        ms = (time.perf_counter() - t) * 1000
        if p.get("confidence", 0) == 0.3 and p.get("food_name_th") == r["text"][:50]:
            fails += 1                      # fallback ของ parse_meal_text = เรียก LLM ไม่สำเร็จ
        name = p.get("food_name_th", "")
        res = model.search_food(name, 1) if name else []
        logged = res[0]["food_name_th"] if res else ""
        match = res[0].get("_match", "full") if res else "none"
        ok_food = bool(logged) and _norm(r["expected_food"]) in _norm(logged)
        ok_meal = p.get("meal_type", "unknown") == r["meal_type"]
        ok_portion = p.get("portion", "normal") == r["portion"]
        out.append({**r, "parsed_name": name, "logged_food": logged,
                    "parsed_meal": p.get("meal_type"), "parsed_portion": p.get("portion"),
                    "confidence": p.get("confidence"), "ms": round(ms, 1), "match": match,
                    "food_ok": ok_food, "meal_ok": ok_meal, "portion_ok": ok_portion,
                    "exact": ok_food and ok_meal and ok_portion})
        print(f"\r  {i}/{len(rows)}", end="", flush=True)
    print()
    if fails == len(rows):
        raise SystemExit("เรียก LLM ไม่สำเร็จเลย (เช็ค TYPHOON_API_KEY) — ไม่บันทึกผล")

    n = len(out)
    s = {
        "n": n,
        "food_accuracy": round(sum(o["food_ok"] for o in out) / n, 4),
        "meal_type_accuracy": round(sum(o["meal_ok"] for o in out) / n, 4),
        "portion_accuracy": round(sum(o["portion_ok"] for o in out) / n, 4),
        "exact_match": round(sum(o["exact"] for o in out) / n, 4),
        "partial_match_rate": round(sum(o["match"] == "partial" for o in out) / n, 4),
        "low_confidence_rate": round(sum((o["confidence"] or 0) < 0.4 for o in out) / n, 4),
        "mean_ms": round(sum(o["ms"] for o in out) / n, 1),
        "llm_failures": fails,
    }
    print(json.dumps(s, ensure_ascii=False, indent=2))
    for o in out:
        if not o["exact"]:
            print(f"  ✗ {o['text']}  → {o['parsed_name']} ({o['logged_food']}) "
                  f"{o['parsed_meal']}/{o['parsed_portion']}  [คาด {o['expected_food']} {o['meal_type']}/{o['portion']}]")
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    with open(os.path.join(HERE, "results", f"meal_parse_{stamp}.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    with open(os.path.join(HERE, "results", f"meal_parse_{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
