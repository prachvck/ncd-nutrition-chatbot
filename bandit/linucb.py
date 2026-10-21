"""
bandit/linucb.py — Contextual Bandit (LinUCB) สำหรับเลือกเมนูที่โชว์ผู้ใช้
[DEV_LOG Entry 45]

ตำแหน่งใน pipeline (ตามที่ตกลงไว้ใน CLAUDE.md — ความปลอดภัยมาก่อนเสมอ):

    profile → targets → ANN cluster + Disease Override → _hard_filter
            → KNN + MMR (pool ผู้สมัคร ≤20 จาน ผ่านเกณฑ์ปลอดภัยแล้วทั้งหมด)
            → **LinUCB เลือก 3 จานจาก pool นี้**   ← โมดูลนี้
            → การ์ด LINE → ผู้ใช้กด "กินเมนูนี้" → reward

Bandit ไม่เคยเห็นจานที่ไม่ผ่าน hard filter จึงทำให้คำแนะนำ "ไม่ปลอดภัย" ไม่ได้
ทำได้แค่จัดลำดับจานที่ปลอดภัยอยู่แล้วตามความชอบของผู้ใช้

รูปแบบ: LinUCB แบบ shared/hybrid — โมเดลเชิงเส้นตัวเดียว (θ) กับ feature
ร่วมของ (ผู้ใช้ × อาหาร) แทนการมี θ แยกต่อจาน (disjoint) เพราะมีจาน 736 จาน
แต่ข้อมูล feedback น้อย — แบบ shared เรียนรู้ข้ามจานได้ ("คนเป็นเบาหวานมื้อเช้า
ชอบเมนูเส้น") จานที่ไม่เคยโชว์เลยก็ได้ประโยชน์

    score(x) = θᵀx + α·sqrt(xᵀA⁻¹x) + β·prior
    θ = A⁻¹b,  A = I + Σ xxᵀ,  b = Σ r·x

prior = อันดับจาก KNN+MMR เดิม (1 = อันดับแรก) — ตอนยังไม่มีข้อมูล (θ=0,
A=I, x ถูก normalize ให้ ||x||=1 → ความไม่แน่นอนเท่ากันทุกจาน) ลำดับจะเท่ากับ
ระบบเดิมพอดี (warm start) แล้วค่อยๆ ปรับตาม feedback

reward: กด "กินเมนูนี้" แล้วยืนยัน = 1 ให้จานที่เลือก, 0 ให้จานอื่นในรอบเดียวกัน
ขอ "แนะนำใหม่" สำหรับมื้อเดิมโดยไม่เลือกเลย = 0 ทุกจานในรอบก่อน
เปลี่ยนมื้อ/ไม่ตอบ = ไม่อัปเดต (ไม่ใช่สัญญาณว่าไม่ชอบอาหาร)
"""
from __future__ import annotations

import math
import threading
import numpy as np

FEATURE_VERSION = "v1"

# ผู้ใช้ (u) — 7 มิติ
DISEASES = ["diabetes", "hypertension", "ckd", "heart", "obesity"]

# อาหาร (f) — กลุ่มหมวดจาน (ย่อจาก _food_category ใน ml/pipeline.py)
CATEGORY_GROUPS = {
    "rice_dish": "rice", "noodle_soup": "noodle", "noodle_dish": "noodle",
    "khanom_jeen": "noodle", "curry_soup": "curry", "stirfry_side": "stirfry",
    "protein_side": "protein", "salad_yum": "salad",
}
GROUPS = ["rice", "noodle", "curry", "stirfry", "protein", "salad", "other"]

U_DIM = 1 + len(DISEASES) + 1            # bias, โรค 5, มื้อเช้า
F_DIM = 6 + len(GROUPS)                  # bias, พลังงาน, P%, F%, Na, ข้าว + หมวด 7
H_DIM = 3                                # ประวัติส่วนตัว
D = U_DIM * F_DIM + H_DIM                # = 7*13 + 3 = 94


def user_vector(profile: dict, meal_type: str) -> np.ndarray:
    ds = set(profile.get("diseases") or [])
    return np.array([1.0] + [1.0 if d in ds else 0.0 for d in DISEASES]
                    + [1.0 if meal_type == "breakfast" else 0.0])


def food_vector(food: dict, meal_limit: dict) -> np.ndarray:
    e = float(food.get("energy_kcal") or 0)
    lim_e = float(meal_limit.get("energy_kcal") or 0) or 1.0
    lim_na = float(meal_limit.get("sodium_mg") or 0) or 1.0
    kcal = max(e, 1.0)
    p_share = min(4 * float(food.get("protein_g") or 0) / kcal, 1.0)
    f_share = min(9 * float(food.get("fat_g") or 0) / kcal, 1.0)
    grp = CATEGORY_GROUPS.get(str(food.get("_food_category") or "other"), "other")
    return np.array([
        1.0,
        min(e / lim_e, 2.0) / 2.0,
        p_share,
        f_share,
        min(float(food.get("sodium_mg") or 0) / lim_na, 2.0) / 2.0,
        1.0 if food.get("_includes_rice") else 0.0,
    ] + [1.0 if grp == g else 0.0 for g in GROUPS])


def history_vector(food: dict, hist: dict | None, food_group_of=None) -> np.ndarray:
    """hist = db.get_user_food_history_stats(): {"food_counts", "name_counts", "total"}
    food_group_of: dict food_id → group (ใช้หาสัดส่วนหมวดที่ผู้ใช้กินบ่อย)"""
    if not hist or not hist.get("total"):
        return np.zeros(H_DIM)
    fid = food.get("food_id")
    n_this = hist["food_counts"].get(fid, 0) if fid is not None else \
        hist["name_counts"].get(food.get("food_name_th"), 0)
    grp = CATEGORY_GROUPS.get(str(food.get("_food_category") or "other"), "other")
    grp_share = 0.0
    if food_group_of:
        same = sum(n for f, n in hist["food_counts"].items() if food_group_of.get(f) == grp)
        grp_share = same / max(hist["total"], 1)
    return np.array([min(math.log1p(n_this) / 2.0, 1.0), grp_share, 1.0])


def build_context(profile: dict, meal_type: str, food: dict, meal_limit: dict,
                  hist: dict | None = None, food_group_of=None) -> np.ndarray:
    u = user_vector(profile, meal_type)
    f = food_vector(food, meal_limit)
    x = np.concatenate([np.outer(u, f).ravel(), history_vector(food, hist, food_group_of)])
    n = np.linalg.norm(x)
    return x / n if n > 0 else x


class LinUCB:
    def __init__(self, d: int = D, alpha: float = 0.6, beta: float = 0.35,
                 diversity_penalty: float = 0.05):
        self.d = d
        self.alpha = alpha
        self.beta = beta
        self.diversity_penalty = diversity_penalty
        self.A_inv = np.eye(d)
        self.b = np.zeros(d)
        self.n_updates = 0
        self._lock = threading.Lock()

    # ── persistence ────────────────────────────────────────────────
    def to_state(self) -> dict:
        with self._lock:
            return {"feature_version": FEATURE_VERSION, "d": self.d,
                    "a_inv": np.round(self.A_inv, 8).tolist(),
                    "b": np.round(self.b, 8).tolist(), "n_updates": self.n_updates}

    def load_state(self, st: dict) -> bool:
        if not st or st.get("feature_version") != FEATURE_VERSION or int(st.get("d", 0)) != self.d:
            return False
        with self._lock:
            self.A_inv = np.array(st["a_inv"], dtype=float)
            self.b = np.array(st["b"], dtype=float)
            self.n_updates = int(st.get("n_updates", 0))
        return True

    # ── policy ─────────────────────────────────────────────────────
    def scores(self, X: np.ndarray, priors: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        with self._lock:
            theta = self.A_inv @ self.b
            mean = X @ theta
            unc = np.sqrt(np.einsum("ij,jk,ik->i", X, self.A_inv, X).clip(min=0))
        return mean + self.alpha * unc + self.beta * priors, mean, unc

    def select(self, X: np.ndarray, priors: np.ndarray, k: int,
               groups: list[str] | None = None) -> tuple[list[int], np.ndarray]:
        """เลือก k ตัวจาก X (แถว = ผู้สมัคร) — คืน (index ที่เลือกตามลำดับ, คะแนน)"""
        total, _, _ = self.scores(X, priors)
        chosen: list[int] = []
        remaining = list(range(len(X)))
        while remaining and len(chosen) < k:
            adj = []
            for i in remaining:
                s = total[i]
                if groups and self.diversity_penalty:
                    s -= self.diversity_penalty * sum(groups[i] == groups[j] for j in chosen)
                adj.append(s)
            best = remaining[int(np.argmax(adj))]
            chosen.append(best)
            remaining.remove(best)
        return chosen, total

    def update(self, x: np.ndarray, reward: float) -> None:
        x = np.asarray(x, dtype=float)
        with self._lock:
            Ax = self.A_inv @ x
            self.A_inv -= np.outer(Ax, Ax) / (1.0 + x @ Ax)    # Sherman–Morrison
            self.b += reward * x
            self.n_updates += 1


def knn_prior(n: int) -> np.ndarray:
    """อันดับ KNN+MMR → prior ในช่วง [0,1] (อันดับแรก = 1)"""
    if n <= 1:
        return np.ones(n)
    return 1.0 - np.arange(n) / (n - 1)
