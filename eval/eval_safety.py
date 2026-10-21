"""
eval/eval_safety.py — วัดว่าเมนูที่ระบบแนะนำ "ปลอดภัยตามเกณฑ์โรค" กี่ % [DEV_LOG Entry 44]

จำลองผู้ใช้หลายแบบ (โรค 0-3 โรค × เพศ × อายุ × น้ำหนัก × กิจกรรม) ให้แต่ละคน
ขอเมนู เช้า → เที่ยง → เย็น (กินตัวเลือกแรกทุกมื้อ เพื่อให้งบมื้อถัดไปลดลงจริง)
แล้วตรวจทุกจานที่โชว์ด้วย evaluate_food_limits() (เกณฑ์เดียวกับที่ใช้ตอบ
"กินได้ไหม") + ตรวจเพิ่มแบบอิสระ:
  - ไม่มีวัตถุดิบดิบ (food_type=ingredient) หลุดมาเป็นมื้อ
  - เบาหวาน: คาร์บต่อมื้อ ≤ 60g×1.1, ไม่ใช่ของหวาน/น้ำตาลอิสระ
  - โรคหัวใจ: ไม่ใช่เมนูกลุ่มไขมันอิ่มตัวสูง
  - CKD: K/P (ค่า conservative) ≤ งบต่อมื้อ×1.1, ไม่มีจานที่ไม่มีข้อมูล K/P
  - โรคคุมโซเดียม: ไม่มีจานที่ไม่มีข้อมูลโซเดียม

รัน:  python -m eval.eval_safety [--policy linucb|knn]
ผล:  compliance rate (%), จำนวนตัวเลือกเฉลี่ย, โปรไฟล์ที่ได้ตัวเลือกไม่ครบ 3
"""
import os, sys, csv, json, itertools, argparse, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DISEASES = ["diabetes", "hypertension", "ckd", "heart", "obesity"]
MEALS = ["breakfast", "lunch", "dinner"]


def profiles():
    combos = [()] + [(d,) for d in DISEASES] + list(itertools.combinations(DISEASES, 2)) \
        + [("diabetes", "hypertension", "ckd"), ("diabetes", "hypertension", "heart")]
    bodies = [("male", 35, 70, 172, 2), ("female", 62, 55, 155, 1), ("male", 58, 95, 170, 3),
              ("female", 45, 80, 160, 2)]
    for ds in combos:
        for g, age, w, h, act in bodies:
            yield {"line_user_id": f"sim_{'_'.join(ds) or 'none'}_{g}_{age}", "name": "sim",
                   "age": age, "gender": g, "weight_kg": w, "height_cm": h,
                   "activity_level": act, "diseases": list(ds)}


def independent_violations(model, food, diseases, meal_lim):
    from ml.pipeline import DIABETES_MAX_CARB_G_PER_MEAL, SODIUM_STRICT_DISEASES
    v = []
    row = model.df[model.df["food_id"] == food["food_id"]]
    row = row.iloc[0] if len(row) else None
    if row is not None and row.get("food_type") == "ingredient":
        v.append("ingredient_as_meal")
    if "diabetes" in diseases:
        if food["carb_available_g"] > DIABETES_MAX_CARB_G_PER_MEAL * 1.1:
            v.append("diabetes_carb")
        if row is not None and bool(row.get("_free_sugar", False)):
            v.append("diabetes_free_sugar")
    if "ckd" in diseases and row is not None:
        mul = {"small": 0.75, "normal": 1.0, "large": 1.35}.get(food.get("_portion", "normal"), 1.0)
        for col in ("potassium_mg", "phosphorus_mg"):
            c = row.get(col + "_ckd_conservative")
            if c is None or c != c:
                v.append(f"ckd_{col}_missing")
            elif c * mul > meal_lim.get(col, 1e9) * 1.1:
                v.append(f"ckd_{col}")
    if "heart" in diseases:
        import re
        from ml.pipeline import HEART_HIGH_SATFAT_NAME_PATTERN, HEART_SATFAT_EXCEPT_PATTERN
        if re.search(HEART_HIGH_SATFAT_NAME_PATTERN, food["food_name_th"]) and \
                not re.search(HEART_SATFAT_EXCEPT_PATTERN, food["food_name_th"]):
            v.append("heart_satfat")
    if set(diseases) & SODIUM_STRICT_DISEASES and row is not None and bool(row.get("_sodium_missing")):
        v.append("sodium_missing")
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="linucb", choices=["linucb", "knn"])
    a = ap.parse_args()
    from ml.pipeline import NCDModel
    from bandit import service as B
    model = NCDModel(csv_path=os.getenv("CSV_PATH", "foods_master_v2.csv"))
    rows, n_short, n_items, n_bad, n_bad_ind = [], 0, 0, 0, 0
    ps = list(profiles())
    for prof in ps:
        diseases = set(prof["diseases"])
        used = {"meal_count": 0}
        history = []
        for meal in MEALS:
            res = model.recommend_next_meal(prof, history, used, 3, True, B.N_CANDIDATES)
            cands = res.get("candidates") or res["meals"]
            meals, _ = B.rank(prof, meal, cands, res["meal_limit"], None, 3, a.policy)
            if len(meals) < 3:
                n_short += 1
            for m in meals:
                n_items += 1
                full = model.get_food_by_id(m["food_id"], with_rice=True) or m
                mul = {"small": 0.75, "normal": 1.0, "large": 1.35}.get(m.get("_portion", "normal"), 1.0)
                scaled = {k: (v * mul if isinstance(v, (int, float)) and not isinstance(v, bool)
                              and k not in ("food_id", "sugar_risk", "_serving_g") else v)
                          for k, v in full.items()}
                # ค่าหลักใช้ตัวที่ pipeline คูณขนาดจานแล้ว (ปัดหลังคูณ) — ปัดก่อนคูณ ×1.35 ทำให้
                # จานที่ชิดเพดานดูเกินได้ ~0.05 g
                for k in ("energy_kcal", "carb_available_g", "protein_g", "fat_g", "sodium_mg"):
                    scaled[k] = m[k]
                # tol 1.101: ค่าใน dict ถูกปัดทศนิยม 1 ตำแหน่ง (เช่น 22.58→22.6) ทำให้
                # จานที่อยู่ชิดเพดานพอดีดูเกินได้ ±0.05 — ไม่ใช่การละเมิดจริง
                ev = model.evaluate_food_limits(scaled, diseases, res["meal_limit"], tol=1.101)
                ind = independent_violations(model, m, diseases, res["meal_limit"])
                n_bad += (not ev["ok"])
                n_bad_ind += bool(ind)
                rows.append({"profile": prof["line_user_id"], "diseases": "+".join(prof["diseases"]) or "none",
                             "meal": meal, "food_id": m["food_id"], "food": m["food_name_th"],
                             "portion": m.get("_portion"), "kcal": m["energy_kcal"],
                             "meal_limit_kcal": res["meal_limit"].get("energy_kcal"),
                             "evaluate_ok": ev["ok"],
                             "evaluate_exceeds": ";".join(e["nutrient"] for e in ev["exceeds"]),
                             "independent_violations": ";".join(ind)})
            if meals:
                first = meals[0]
                history.append(first["food_name_th"])
                mul = {"small": 0.75, "normal": 1.0, "large": 1.35}.get(first.get("_portion", "normal"), 1.0)
                full = model.get_food_by_id(first["food_id"], with_rice=True)
                used = {"meal_count": used["meal_count"] + 1,
                        "total_energy_kcal": float(used.get("total_energy_kcal", 0)) + full["energy_kcal"] * mul,
                        "total_carb_g": float(used.get("total_carb_g", 0)) + full["carb_available_g"] * mul,
                        "total_protein_g": float(used.get("total_protein_g", 0)) + full["protein_g"] * mul,
                        "total_fat_g": float(used.get("total_fat_g", 0)) + full["fat_g"] * mul,
                        "total_sodium_mg": float(used.get("total_sodium_mg", 0)) + full["sodium_mg"] * mul,
                        "total_potassium_mg": float(used.get("total_potassium_mg", 0)) + full["potassium_mg"] * mul,
                        "total_phosphorus_mg": float(used.get("total_phosphorus_mg", 0)) + full["phosphorus_mg"] * mul}
    summary = {
        "policy": a.policy, "profiles": len(ps), "requests": len(ps) * len(MEALS),
        "items_shown": n_items,
        "compliance_evaluate_food_limits": round(1 - n_bad / max(n_items, 1), 4),
        "compliance_independent_checks": round(1 - n_bad_ind / max(n_items, 1), 4),
        "requests_with_fewer_than_3_options": n_short,
        "mean_options_per_request": round(n_items / (len(ps) * len(MEALS)), 2),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    outdir = os.path.join(HERE, "results"); os.makedirs(outdir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    with open(os.path.join(outdir, f"safety_{a.policy}_{stamp}.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with open(os.path.join(outdir, f"safety_{a.policy}_{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
