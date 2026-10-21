"""
eval/eval_diversity.py — วัดความหลากหลายของเมนูที่แนะนำ (รายงานบท 3.5.2 เกณฑ์ที่ 2) [DEV_LOG Entry 53]

เทียบ 3 แบบบนโปรไฟล์จำลองชุดเดียวกับ eval_safety (72 โปรไฟล์ × 3 มื้อ):
  knn_only — KNN เรียงตามความใกล้อย่างเดียว (MMR λ=1.0 = ไม่สนความหลากหลาย)
  knn_mmr  — ระบบ Project 1 (MMR λ=0.6)
  linucb   — ระบบปัจจุบัน (pool KNN+MMR → LinUCB เลือก 3 + โทษหมวดซ้ำ) ตอนยังไม่มี feedback

ตัวชี้วัด (ต่อการแนะนำ 1 ครั้ง = การ์ด 3 ใบ แล้วเฉลี่ย):
  - ILD (intra-list diversity): ระยะห่างเฉลี่ยระหว่างคู่จานใน 3 ใบ (feature โภชนาการ 10 ตัว
    ที่ standardize แล้ว — ตัวเดียวกับที่ KNN ใช้) ยิ่งมาก = 3 ตัวเลือกต่างกันมาก
  - category_coverage: จำนวนหมวดอาหารที่ต่างกันใน 3 ใบ (ข้าว/เส้น/แกง/ผัด/โปรตีน/ยำ/อื่นๆ) เต็ม 3
  - novelty@3: ขอ "แนะนำใหม่" มื้อเดิม 3 รอบติด (รอบหลังกันเมนูที่เพิ่งโชว์ ตามที่แอปทำ) →
    สัดส่วนจานที่ไม่ซ้ำจาก 9 ใบ (1.0 = ไม่ซ้ำเลย)

รัน:  python -m eval.eval_diversity
"""
import os, sys, json, itertools, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MEALS = ["breakfast", "lunch", "dinner"]


def recommend(model, prof, history, lmbda, policy, meal):
    from ml.pipeline import compute_meal_limit, features_to_list, FEATURES, NCOLS
    from bandit import service as B
    t = model.compute_user_targets(prof)
    meal_lim = compute_meal_limit(t["daily_limit"], {}, 3)
    _, final_c, _ = model.predict_cluster(t["meal_limit"], t["diseases"])
    user_sc = model.scaler_full.transform(pd.DataFrame([features_to_list(t["meal_limit"])], columns=FEATURES))
    n_ret = B.N_CANDIDATES if policy == "linucb" else 3
    cands = model._knn_mmr(final_c, user_sc, meal_lim, history, 3, lmbda=lmbda,
                           diseases=t["diseases"], main_meal=True, n_return=n_ret)
    if cands.empty:
        return []
    rows = [r for _, r in cands.iterrows()]
    if policy != "linucb":
        return rows[:3]
    dicts = [{"food_id": r["food_id"], "food_name_th": r["food_name_th"],
              "energy_kcal": r["energy_kcal"], "protein_g": r["protein_g"], "fat_g": r["fat_g"],
              "sodium_mg": r["sodium_mg"], "_includes_rice": r.get("_includes_rice", False),
              "_food_category": r.get("_food_category", "other"), "_portion": r.get("_portion"),
              "_knn_rank": i} for i, r in enumerate(rows)]
    meals, _ = B.rank(prof, meal, dicts, meal_lim, None, 3, "linucb")
    ids = [m["food_id"] for m in meals]
    return [r for r in rows if r["food_id"] in ids]


def ild(model, rows):
    from ml.pipeline import FEATURES
    if len(rows) < 2:
        return 0.0
    X = model.scaler_full.transform(pd.DataFrame([[r[f] for f in FEATURES] for r in rows], columns=FEATURES))
    d = [np.linalg.norm(X[i] - X[j]) for i, j in itertools.combinations(range(len(X)), 2)]
    return float(np.mean(d))


def main():
    from ml.pipeline import NCDModel
    from bandit.linucb import CATEGORY_GROUPS
    from eval.eval_safety import profiles
    model = NCDModel(csv_path=os.getenv("CSV_PATH", "foods_master_v2.csv"))
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["all", "knn_only", "knn_mmr", "linucb"], default="all")
    a = ap.parse_args()
    variants = {"knn_only": (1.0, "knn"), "knn_mmr": (0.6, "knn"), "linucb": (0.6, "linucb")}
    if a.variant != "all":
        variants = {a.variant: variants[a.variant]}
    res = {}
    for name, (lmbda, pol) in variants.items():
        ilds, covs, novs = [], [], []
        for prof in profiles():
            for meal in MEALS:
                shown_all, hist = [], []
                for rnd in range(3):
                    rows = recommend(model, prof, hist, lmbda, pol, meal)
                    if rnd == 0 and rows:
                        ilds.append(ild(model, rows))
                        covs.append(len({CATEGORY_GROUPS.get(r.get("_food_category"), "other") for r in rows}))
                    names = [r["food_name_th"] for r in rows]
                    shown_all += names
                    hist += names           # แอปกันเมนูที่เพิ่งโชว์ใน 6 ชม. (get_recently_shown_names)
                if shown_all:
                    novs.append(len(set(shown_all)) / len(shown_all))
        res[name] = {"ILD_mean": round(float(np.mean(ilds)), 3), "ILD_sd": round(float(np.std(ilds)), 3),
                     "category_coverage_mean": round(float(np.mean(covs)), 3),
                     "novelty_at_3_rounds": round(float(np.mean(novs)), 4), "n_requests": len(ilds)}
        print(name, res[name])
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    with open(os.path.join(HERE, "results", f"diversity_{'_'.join(variants)}_{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
