"""
eval/simulate_bandit.py — ทดสอบ LinUCB กับผู้ใช้จำลอง (offline simulation) [DEV_LOG Entry 45]

ทำไมต้องจำลอง: ยังไม่มีผู้ใช้จริงพอจะวัด Bandit (ต้องการ feedback หลายร้อยครั้ง)
วิธีมาตรฐานในงานวิจัย recommender คือจำลองผู้ใช้ที่มี "รสนิยมซ่อนอยู่" แล้วดูว่า
policy ไหนเรียนรู้ได้เร็ว/แม่นกว่า (Li et al., 2010 ใช้ offline replay; ที่นี่ใช้
simulator เพราะไม่มี log จริง)

ผู้ใช้จำลอง:
  - โปรไฟล์สุขภาพ 24 แบบ (โรค 6 แบบ × รูปร่าง 4 แบบ) → pool เมนูจากระบบจริง
    (ผ่าน Disease Override + hard filter + KNN/MMR เหมือนใช้งานจริงทุกอย่าง)
  - รสนิยมซ่อน: ชอบหมวดอาหารต่างกัน (สุ่ม) + ชอบ/ไม่ชอบโปรตีนสูง + ความชอบรายจาน
  - เห็นการ์ด 3 ใบ → เลือกกินใบที่ชอบที่สุดถ้าความชอบสูงพอ (โอกาสตาม logistic)
    ไม่ชอบสักใบ → ขอแนะนำใหม่ (reward 0 ทั้ง 3 ใบ)
  - กินซ้ำเมนูเดิมภายใน 3 มื้อไม่ได้ (เลียน history filter)

เทียบ 3 policy บนผู้ใช้ชุดเดียวกัน (seed เดียวกัน):
  random — สุ่ม 3 จานจาก pool | knn — ระบบเดิม (3 อันดับแรก KNN+MMR) | linucb
วัด: acceptance rate (CTR) รวม / ช่วงแรก / ช่วงท้าย, cumulative regret เทียบ oracle
(oracle = รู้รสนิยมจริง เลือก 3 จานที่ดีที่สุดใน pool)

รัน:  python -m eval.simulate_bandit [--rounds 60] [--seeds 5]
"""
import os, sys, json, argparse, datetime, itertools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MEALS = ["breakfast", "lunch", "dinner"]


def sim_profiles():
    combos = [(), ("diabetes",), ("hypertension",), ("ckd",), ("heart",), ("diabetes", "hypertension")]
    bodies = [("male", 35, 70, 172, 2), ("female", 62, 55, 155, 1),
              ("male", 58, 90, 170, 3), ("female", 45, 75, 160, 2)]
    for ds, (g, age, w, h, act) in itertools.product(combos, bodies):
        yield {"line_user_id": f"sim_{'_'.join(ds) or 'none'}_{g}{age}", "age": age, "gender": g,
               "weight_kg": w, "height_cm": h, "activity_level": act, "diseases": list(ds)}


def build_pools(model, profiles, n_cand):
    """pool ผู้สมัครต่อ (ผู้ใช้, มื้อ) — คำนวณครั้งเดียว (งบมื้อเทียบเท่ากินครบตามแผน)"""
    pools = {}
    for p in profiles:
        used = {"meal_count": 0}
        for mi, meal in enumerate(MEALS):
            res = model.recommend_next_meal(p, [], used, 3, True, n_cand)
            pools[(p["line_user_id"], meal)] = (res.get("candidates") or res["meals"], res["meal_limit"])
            # สมมติว่ากินพลังงานพอดีงบมื้อ เพื่อให้งบมื้อถัดไปสมจริง
            e = res["meal_limit"].get("energy_kcal", 0)
            used = {"meal_count": mi + 1,
                    "total_energy_kcal": float(used.get("total_energy_kcal", 0)) + e}
    return pools


class SimUser:
    def __init__(self, profile, rng, groups):
        self.p = profile
        self.group_pref = dict(zip(groups, rng.normal(0, 1.0, len(groups))))
        self.protein_pref = rng.normal(0, 1.0)
        self.rice_pref = rng.normal(0, 0.7)
        self.item_noise = {}
        self.rng = rng
        self.recent = []

    def utility(self, food):
        from bandit.linucb import CATEGORY_GROUPS
        fid = food["food_id"]
        if fid not in self.item_noise:
            self.item_noise[fid] = self.rng.normal(0, 0.5)
        kcal = max(food["energy_kcal"], 1)
        p_share = 4 * food["protein_g"] / kcal
        g = CATEGORY_GROUPS.get(food.get("_food_category"), "other")
        return (self.group_pref[g] + self.protein_pref * (p_share - 0.18) * 5
                + self.rice_pref * float(food.get("_includes_rice", False)) + self.item_noise[fid])

    def respond(self, shown):
        """คืน index ที่เลือก หรือ None (ไม่เอาสักจาน)"""
        us = [self.utility(f) for f in shown]
        best = int(np.argmax(us))
        p_accept = 1 / (1 + np.exp(-(us[best] - 0.5) * 2))
        return best if self.rng.random() < p_accept else None


def run(policy, model, pools, profiles, rounds, seed, bandit_alpha, bandit_beta):
    from bandit.linucb import LinUCB, build_context, knn_prior, CATEGORY_GROUPS, GROUPS, D
    rng = np.random.default_rng(seed)
    users = [SimUser(p, np.random.default_rng(seed * 1000 + i), GROUPS) for i, p in enumerate(profiles)]
    bandit = LinUCB(d=D, alpha=bandit_alpha, beta=bandit_beta)
    hist = {u.p["line_user_id"]: {"food_counts": {}, "name_counts": {}, "total": 0} for u in users}
    group_of = {}
    accepts = np.zeros(rounds); regret = np.zeros(rounds)
    for t in range(rounds):
        meal = MEALS[t % 3]
        for u in users:
            uid = u.p["line_user_id"]
            cands, lim = pools[(uid, meal)]
            cands = [c for c in cands if c["food_id"] not in u.recent[-3:]] or cands
            for c in cands:
                group_of[c["food_id"]] = CATEGORY_GROUPS.get(c.get("_food_category"), "other")
            X = np.vstack([build_context(u.p, meal, c, lim, hist[uid], group_of) for c in cands])
            k = min(3, len(cands))
            if policy == "random":
                idx = list(rng.choice(len(cands), size=k, replace=False))
            elif policy == "knn":
                idx = list(range(k))
            else:
                idx, _ = bandit.select(X, knn_prior(len(cands)), k,
                                       [CATEGORY_GROUPS.get(c.get("_food_category"), "other") for c in cands])
            shown = [cands[i] for i in idx]
            choice = u.respond(shown)
            # oracle: 3 จานที่ผู้ใช้ชอบที่สุดใน pool → ความน่าจะเป็นที่จะรับ (คาดหวัง)
            us = np.array([u.utility(c) for c in cands])
            p_best = 1 / (1 + np.exp(-(us.max() - 0.5) * 2))
            p_shown = 1 / (1 + np.exp(-(max(us[i] for i in idx) - 0.5) * 2))
            regret[t] += p_best - p_shown
            for j, i in enumerate(idx):
                bandit.update(X[i], 1.0 if choice == j else 0.0)
            if choice is not None:
                accepts[t] += 1
                f = shown[choice]
                u.recent.append(f["food_id"])
                h = hist[uid]
                h["food_counts"][f["food_id"]] = h["food_counts"].get(f["food_id"], 0) + 1
                h["total"] += 1
    n = len(users)
    return accepts / n, np.cumsum(regret) / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=60, help="จำนวนมื้อที่ขอแนะนำต่อผู้ใช้ (60 = 20 วัน)")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--alpha", type=float, default=float(os.getenv("BANDIT_ALPHA", "0.6")))
    ap.add_argument("--beta", type=float, default=float(os.getenv("BANDIT_BETA", "0.35")))
    a = ap.parse_args()
    from ml.pipeline import NCDModel
    model = NCDModel(csv_path=os.getenv("CSV_PATH", "foods_master_v2.csv"))
    profiles = list(sim_profiles())
    pools = build_pools(model, profiles, 20)
    sizes = [len(v[0]) for v in pools.values()]
    print(f"ผู้ใช้จำลอง {len(profiles)} คน, pool ต่อมื้อ เฉลี่ย {np.mean(sizes):.1f} (min {min(sizes)})")

    res = {}
    for pol in ("random", "knn", "linucb"):
        ctr, reg = [], []
        for s in range(a.seeds):
            c, r = run(pol, model, pools, profiles, a.rounds, s, a.alpha, a.beta)
            ctr.append(c); reg.append(r)
        ctr = np.array(ctr); reg = np.array(reg)
        q = max(a.rounds // 4, 1)
        res[pol] = {
            "acceptance_overall": round(float(ctr.mean()), 4),
            "acceptance_overall_sd": round(float(ctr.mean(axis=1).std()), 4),
            f"acceptance_first_{q}": round(float(ctr[:, :q].mean()), 4),
            f"acceptance_last_{q}": round(float(ctr[:, -q:].mean()), 4),
            "cumulative_regret_end": round(float(reg[:, -1].mean()), 3),
            "acceptance_curve": [round(float(x), 4) for x in ctr.mean(axis=0)],
        }
        print(f"{pol:7s} acceptance={res[pol]['acceptance_overall']:.3f}±{res[pol]['acceptance_overall_sd']:.3f} "
              f"first{q}={res[pol][f'acceptance_first_{q}']:.3f} last{q}={res[pol][f'acceptance_last_{q}']:.3f} "
              f"regret={res[pol]['cumulative_regret_end']:.2f}")
    out = {"rounds": a.rounds, "seeds": a.seeds, "users": len(profiles), "alpha": a.alpha, "beta": a.beta,
           "results": res}
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    with open(os.path.join(HERE, "results", f"bandit_sim_{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        w = 6
        for pol in res:
            c = np.convolve(res[pol]["acceptance_curve"], np.ones(w) / w, mode="valid")
            plt.plot(range(w, w + len(c)), c, label=pol)
        plt.xlabel("recommendation round (meal)"); plt.ylabel("acceptance rate (moving avg, 6 rounds)")
        plt.legend(); plt.title("Bandit simulation"); plt.tight_layout()
        plt.savefig(os.path.join(HERE, "results", f"bandit_sim_{stamp}.png"), dpi=130)
    except Exception as e:
        print(f"(ไม่ได้วาดกราฟ: {e})")


if __name__ == "__main__":
    main()
