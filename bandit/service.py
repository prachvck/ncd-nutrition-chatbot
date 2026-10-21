"""
bandit/service.py — เชื่อม LinUCB เข้ากับแอป (DB + การแนะนำ + reward)
[DEV_LOG Entry 45]

ตั้งค่าผ่าน .env:
    BANDIT_POLICY = linucb (ค่าเริ่มต้น) | knn | ab
        linucb — Bandit เลือก 3 จานจาก pool ที่ผ่าน safety filter
        knn    — ระบบเดิม (3 อันดับแรกของ KNN+MMR) แต่ยังเก็บ context/reward
                 ไว้ให้ Bandit เรียนรู้ (ใช้เป็น baseline)
        ab     — แบ่งผู้ใช้ครึ่ง/ครึ่งตาม hash ของ userId (คนเดิมได้ policy เดิม
                 ตลอด) เพื่อเทียบ acceptance rate ระหว่าง 2 แบบตอนทดสอบกับคนจริง
    BANDIT_ALPHA (0.6), BANDIT_BETA (0.35)
"""
from __future__ import annotations

import os
import hashlib
import logging
import numpy as np

from bandit.linucb import LinUCB, build_context, knn_prior, CATEGORY_GROUPS, D

log = logging.getLogger(__name__)

MODEL_NAME = "global"
N_CANDIDATES = 20

_model = LinUCB(d=D, alpha=float(os.getenv("BANDIT_ALPHA", "0.6")),
                beta=float(os.getenv("BANDIT_BETA", "0.35")))
_food_group_of: dict[int, str] = {}


def policy_for(uid: str) -> str:
    p = os.getenv("BANDIT_POLICY", "linucb").strip().lower()
    if p == "ab":
        h = int(hashlib.sha256(uid.encode()).hexdigest(), 16)
        return "linucb" if h % 2 == 0 else "knn"
    return p if p in ("linucb", "knn") else "linucb"


async def init_bandit(ncd_model=None):
    global _food_group_of
    if ncd_model is not None and getattr(ncd_model, "df", None) is not None:
        df = ncd_model.df
        if "food_id" in df.columns and "_food_category" in df.columns:
            _food_group_of = {
                int(fid): CATEGORY_GROUPS.get(str(cat), "other")
                for fid, cat in zip(df["food_id"], df["_food_category"]) if fid == fid
            }
    try:
        from db.database import load_bandit_model
        st = await load_bandit_model(MODEL_NAME)
        if st and _model.load_state(st):
            log.info(f"Bandit: โหลดโมเดล LinUCB (อัปเดตแล้ว {_model.n_updates} ครั้ง)")
        else:
            log.info("Bandit: เริ่มโมเดล LinUCB ใหม่ (ยังไม่มี feedback)")
    except Exception as e:
        log.warning(f"Bandit: โหลดโมเดลจาก DB ไม่สำเร็จ ({e}) — เริ่มใหม่ในหน่วยความจำ")


def model_stats() -> dict:
    return {"n_updates": _model.n_updates, "alpha": _model.alpha, "beta": _model.beta}


def rank(profile: dict, meal_type: str, candidates: list[dict], meal_limit: dict,
         hist: dict | None, k: int, policy: str) -> tuple[list[dict], list[dict]]:
    """เลือก k จานจาก candidates (เรียงตาม KNN+MMR มาแล้ว ผ่าน safety ครบ)
    คืน (meals ที่จะโชว์, items สำหรับบันทึก DB พร้อม context/score)"""
    if not candidates:
        return [], []
    X = np.vstack([build_context(profile, meal_type, c, meal_limit, hist, _food_group_of)
                   for c in candidates])
    priors = knn_prior(len(candidates))
    groups = [CATEGORY_GROUPS.get(str(c.get("_food_category")), "other") for c in candidates]
    if policy == "linucb":
        idx, total = _model.select(X, priors, k, groups)
    else:
        idx = list(range(min(k, len(candidates))))
        total, _, _ = _model.scores(X, priors)
    meals, items = [], []
    for i in idx:
        c = candidates[i]
        meals.append(c)
        items.append({
            "food_id": c.get("food_id"), "food_name_th": c.get("food_name_th", ""),
            "portion": c.get("_portion", "normal"), "knn_rank": int(c.get("_knn_rank", i)),
            "bandit_score": float(total[i]), "context": [round(float(v), 6) for v in X[i]],
        })
    return meals, items


async def _apply_and_persist(updates: list[tuple[list, float]]):
    for ctx, r in updates:
        if ctx is not None and len(ctx) == _model.d:
            _model.update(np.array(ctx, dtype=float), r)
    try:
        from db.database import save_bandit_model
        st = _model.to_state()
        await save_bandit_model(MODEL_NAME, st["feature_version"], st["d"],
                                st["a_inv"], st["b"], st["n_updates"])
    except Exception as e:
        log.warning(f"Bandit: บันทึกโมเดลลง DB ไม่สำเร็จ: {e}")


async def reward_choice(rec_id: int, chosen_item_id: int | None = None,
                        chosen_food_id: int | None = None) -> bool:
    """ผู้ใช้เลือกกินจานหนึ่งจากรอบแนะนำ rec_id → reward 1 / 0 ที่เหลือ"""
    from db.database import get_recommendation_items, close_recommendation
    rec = await get_recommendation_items(rec_id)
    if not rec or rec["status"] != "open":
        return False
    items = rec["items"]
    chosen = None
    for it in items:
        if (chosen_item_id is not None and it["id"] == chosen_item_id) or \
           (chosen_item_id is None and chosen_food_id is not None and it["food_id"] == chosen_food_id):
            chosen = it["id"]
            break
    if chosen is None:
        return False
    rewards = {it["id"]: (1.0 if it["id"] == chosen else 0.0) for it in items}
    if not await close_recommendation(rec_id, "chosen", rewards):
        return False
    await _apply_and_persist([(it["context"], rewards[it["id"]]) for it in items])
    log.info(f"Bandit reward: rec={rec_id} chosen_item={chosen} (updates={_model.n_updates})")
    return True


async def resolve_previous(uid: str, new_meal_type: str) -> None:
    """เรียกก่อนสร้างรอบแนะนำใหม่: รอบเก่าที่ยังไม่ได้เลือก
    - มื้อเดียวกัน → ผู้ใช้ขอแนะนำใหม่ = ไม่เอาสักจาน → reward 0 ทุกจาน
    - คนละมื้อ → expired (ไม่อัปเดต: ไม่ใช่สัญญาณเรื่องรสนิยม)"""
    from db.database import get_open_recommendation, close_recommendation
    rec = await get_open_recommendation(uid)
    if not rec:
        return
    if rec.get("meal_type") == new_meal_type:
        rewards = {it["id"]: 0.0 for it in rec["items"]}
        if await close_recommendation(rec["id"], "rejected", rewards):
            await _apply_and_persist([(it["context"], 0.0) for it in rec["items"]])
    else:
        await close_recommendation(rec["id"], "expired", {})


async def reward_typed_log(uid: str, food_id: int | None) -> bool:
    """ผู้ใช้พิมพ์บันทึกเอง แต่เป็นจานที่อยู่ในการ์ดรอบล่าสุด → นับว่าเลือกจานนั้น"""
    if food_id is None:
        return False
    from db.database import get_open_recommendation
    rec = await get_open_recommendation(uid)
    if not rec or not any(it["food_id"] == food_id for it in rec["items"]):
        return False
    return await reward_choice(rec["id"], chosen_food_id=food_id)
