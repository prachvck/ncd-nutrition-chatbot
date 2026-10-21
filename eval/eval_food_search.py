"""
eval/eval_food_search.py — วัดความถูกต้องของการค้นหาเมนูจากชื่อที่ผู้ใช้พิมพ์ [DEV_LOG Entry 44]
(ใช้ทั้งตอน "ถามแคล" และ "บันทึกการกินแบบพิมพ์เอง")

ชุดทดสอบ: eval/food_search_testset.csv (query, expected_contains) — ถือว่าถูก
ถ้าผลอันดับ 1 มีคำที่คาดไว้อยู่ในชื่อ (Top-1) / อยู่ใน 3 อันดับแรก (Top-3)
และรายงานว่าผลอันดับ 1 เป็น "จาน" (dish) กี่ % (ไม่ใช่วัตถุดิบดิบ)

รัน:  python -m eval.eval_food_search
"""
import os, sys, csv, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    from ml.pipeline import NCDModel
    m = NCDModel(csv_path=os.getenv("CSV_PATH", "foods_master_v2.csv"))
    with open(os.path.join(HERE, "food_search_testset.csv"), encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    top1 = top3 = dish1 = 0
    out = []
    for r in rows:
        res = m.search_food(r["query"], 3)
        names = [x["food_name_th"] for x in res]
        from ml.pipeline import _norm_name as norm   # [Entry 56] รวมสะกดต่าง (กระเพรา/กะเพรา)
        exp = norm(r["expected_contains"])
        t1 = bool(names) and exp in norm(names[0])
        t3 = any(exp in norm(n) for n in names)
        d1 = bool(res) and res[0].get("food_type") == "dish"
        top1 += t1; top3 += t3; dish1 += d1
        out.append({**r, "top1": names[0] if names else "", "top3": " | ".join(names),
                    "top1_ok": t1, "top3_ok": t3, "top1_type": res[0].get("food_type") if res else ""})
        if not t1:
            print(f"  ✗ {r['query']:20s} → {names}")
    n = len(rows)
    s = {"n": n, "top1_accuracy": round(top1 / n, 4), "top3_accuracy": round(top3 / n, 4),
         "top1_is_dish": round(dish1 / n, 4)}
    print(json.dumps(s, ensure_ascii=False, indent=2))
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "food_search.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    with open(os.path.join(HERE, "results", "food_search.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
