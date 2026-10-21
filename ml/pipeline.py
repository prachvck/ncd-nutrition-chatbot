"""
ml/pipeline.py  —  v3  (Phase 2 ready)
=========================================
ปรับปรุงจาก Model3_v3_fixed.ipynb:
  - โหลด user profile จาก DB (ไม่ hardcode ใน cell)
  - โหลด food data จาก DB (ไม่อ่าน CSV ทุกครั้ง)
  - ดึง meal history จาก DB เพื่อกรอง MMR
  - Dynamic meal budget (remaining budget หารด้วยมื้อที่เหลือ)
  - scaler_full / kmeans / ann_final โหลดครั้งเดียวตอน startup
  - map_cluster_for_disease() [FIX v3] override cluster ตามโรค
"""

import os
import json
import hashlib
import asyncio
import logging
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors

log = logging.getLogger(__name__)

FEATURES = [
    "energy_kcal", "water_g", "protein_g", "fat_g",
    "carb_available_g", "sodium_mg", "potassium_mg",
    "calcium_mg", "magnesium_mg", "phosphorus_mg",
]
# [FIX — DEV_LOG Entry 15] เดิม NCOLS มีแค่ energy/carb/protein/fat/sodium —
# ไม่มีโพแทสเซียม/ฟอสฟอรัสเลย ทั้งที่ 2 ตัวนี้อันตรายเฉียบพลันสำหรับผู้ป่วย
# โรคไต (CKD) ถ้าสูงเกิน (หัวใจเต้นผิดจังหวะได้) เพิ่มเข้ามาให้ทั้งสอง
# ถูกติดตามสะสมต่อวัน (`daily_used`) และมีเพดานต่อมื้อใน `_hard_filter`
# เหมือน 5 ตัวเดิม (ดู `_hard_filter` — บังคับเฉพาะผู้ป่วย CKD เท่านั้น
# เพราะโพแทสเซียมสำหรับความดันโลหิตสูงอย่างเดียว (ไม่มีโรคไต) เป็น "ค่าต่ำสุด
# ที่ควรได้" ไม่ใช่ "เพดานห้ามเกิน" — ดู adjust_features_by_disease)
NCOLS = ["energy_kcal", "carb_available_g", "protein_g", "fat_g", "sodium_mg",
         "potassium_mg", "phosphorus_mg"]
UNITS = {"energy_kcal": "kcal", "carb_available_g": "g",
         "protein_g": "g", "fat_g": "g", "sodium_mg": "mg",
         "potassium_mg": "mg", "phosphorus_mg": "mg"}

# [FIX — DEV_LOG Entry 16] เพดานคาร์บต่อมื้อแบบตายตัวสำหรับเบาหวาน อิงแนวทาง
# consistent-carbohydrate diet ที่ใช้กันทั่วไปในทางปฏิบัติ (45-60g คาร์บ/มื้อ)
# เดิมเบาหวานคุมคาร์บผ่าน ratio (cr<=0.45 ของพลังงาน) ในadjust_features_by_
# disease เท่านั้น ซึ่งแปลงเป็น meal_lim แบบ dynamic ได้ — แต่ไม่มี absolute
# cap ตรงๆ กันเคสที่ budget พลังงานต่อมื้อสูง (เช่นคนตัวใหญ่/กิจกรรมเยอะ)
# จนแปลงเป็นคาร์บต่อมื้อเกิน 60g ทั้งที่ ratio ผ่าน — เพดานนี้เป็นขอบบนตายตัว
# เพิ่มเติม ทำงานร่วมกับ (ไม่แทนที่) ระบบ ratio เดิม
DIABETES_MAX_CARB_G_PER_MEAL = 60

# [FIX — DEV_LOG Entry 20] sugar_risk (1-5, ยิ่งมากยิ่งไม่เหมาะกับเบาหวาน)
# เดิมเป็นแค่ข้อมูล advisory แนบไปให้ LLM พูดประกอบเท่านั้น (ดู Entry 17/18)
# ตอนนี้บังคับกรองจริงเฉพาะกลุ่มเสี่ยงสูงสุด (risk=5 เท่านั้น — เลือกจุดตัด
# เข้มที่สุดตามที่ผู้ใช้ยืนยัน เพื่อไม่ให้กรองเมนูดีๆ ออกโดยไม่จำเป็นจาก
# เกณฑ์ที่กว้างเกินไป) สำหรับผู้ป่วยเบาหวานเท่านั้น ทำงานเสริมจาก
# DIABETES_MAX_CARB_G_PER_MEAL ด้านบน ไม่ได้แทนที่กัน
DIABETES_SUGAR_RISK_HARD_LIMIT = 5

# [FIX — DEV_LOG Entry 20] เดิม _hard_filter ตีความ potassium_mg/phosphorus_mg
# ที่เป็น NaN ว่า "ไม่เกินเพดาน" (fail-open) ปล่อยผ่านการกรองสำหรับผู้ป่วย CKD
# ทั้งที่ไม่มีข้อมูลจริง เปลี่ยนเป็น fail-safe (กรองออก) แทน — margin ด้านล่าง
# บวกเพิ่มเข้ากับค่าที่ประมาณจาก regression (แถวที่ potassium_estimated/
# phosphorus_estimated = True ใน foods_master_v2.csv) เฉพาะตอนเช็คเพดาน CKD
# เท่านั้น (ไม่กระทบค่าที่แสดงผลทั่วไป) เพราะโมเดลทำนายโพแทสเซียมแม่นยำต่ำมาก
# (R²≈0.06 บน CV) จึงบวก margin แบบอนุรักษ์นิยม (residual std จาก 5-fold CV)
# กันจานที่ประมาณค่าต่ำกว่าความจริงหลุดผ่านเพดาน — ฟอสฟอรัสแม่นกว่า
# (R²≈0.50) แต่ใช้หลักการเดียวกันเพื่อความสม่ำเสมอ
#
# [FIX — DEV_LOG Entry 22] เดิม (Entry 21) คอลัมน์ *_ckd_conservative ถูก
# คำนวณไว้ล่วงหน้าใน CSV เป็นค่า "ต่อ 100g" แต่ _hard_filter เอาไปเทียบกับ
# เพดาน "ต่อมื้อ" (ค่าอื่นถูกคูณ serving + บวกข้าวแล้ว แต่คอลัมน์นี้ไม่ได้คูณ)
# ทำให้ค่าที่ใช้เช็คต่ำกว่าค่าจริงใน ~73% ของเมนู → ผู้ป่วย CKD ได้เมนูที่
# เกินเพดานจริง ตอนนี้คำนวณใหม่ใน pipeline หลังแปลงเป็นต่อมื้อแล้วเสมอ
# (add_ckd_conservative_columns) margin ต่อ 100g จึงถูกคูณด้วย serving ของ
# ตัวจาน (ไม่คูณส่วนข้าวที่บวกเพิ่ม เพราะค่าข้าวเป็นข้อมูลจริง ไม่ได้ประมาณ)
CKD_MINERAL_CONSERVATIVE_SUFFIX = "_ckd_conservative"
# [DEV_LOG Entry 23] เปลี่ยน margin จาก residual std (K 326.4 / P 181.6) เป็น
# MAE จาก 5-fold CV ตัวเดียวกัน (K 181.0 / P 82.5 mg ต่อ 100g) — ผู้ใช้
# ตัดสินใจเลือก เพราะ margin แบบ std สูงจนเมนูค่าประมาณไม่ผ่านเพดาน CKD เลย
# (pool เหลือ 0-4 เมนู) MAE ยังเข้มกว่าใช้ค่าประมาณตรงๆ แต่ปล่อยให้เมนูที่
# ค่าประมาณต่ำพอกลับมาแนะนำได้ — แลกกับความเสี่ยงที่ค่าจริงบางจานอาจสูง
# กว่าค่าประมาณ+MAE (ไม่ได้การันตีเหมือน std)
CKD_MINERAL_MARGIN_PER100G = {"potassium_mg": 181.0, "phosphorus_mg": 82.5}


def add_ckd_conservative_columns(df: pd.DataFrame, originally_missing: dict) -> None:
    """
    [FIX — DEV_LOG Entry 22] สร้างคอลัมน์ <col>_ckd_conservative (และ
    _dishonly_<col>_ckd_conservative สำหรับ search_food) จากค่าต่อมื้อที่
    แปลงแล้ว = ค่าต่อมื้อ + margin×(serving ตัวจาน/100) เฉพาะแถวที่ค่านั้น
    มาจาก regression — แถวที่ไม่มีข้อมูลเลยตั้งแต่แรก (ก่อนเติม median)
    ให้เป็น NaN เพื่อให้ fail-safe ใน _hard_filter/evaluate_food_limits
    กรองออก แก้ df in-place
    """
    if "_dishonly_serving_g" in df.columns:
        sf = df["_dishonly_serving_g"].astype(float) / 100.0
    elif "_serving_g" in df.columns:
        sf = df["_serving_g"].astype(float) / 100.0
    else:
        sf = pd.Series(DEFAULT_SERVING_G / 100.0, index=df.index)

    for col, margin in CKD_MINERAL_MARGIN_PER100G.items():
        if col not in df.columns:
            continue
        flag_col = col.replace("_mg", "") + "_estimated"
        if flag_col in df.columns:
            est = df[flag_col].astype(str).str.lower().isin(["true", "1"])
        else:
            est = pd.Series(False, index=df.index)
        extra = sf.where(est, 0.0) * margin
        missing = originally_missing.get(col, pd.Series(False, index=df.index))

        out = df[col] + extra
        out[missing] = np.nan
        df[col + CKD_MINERAL_CONSERVATIVE_SUFFIX] = out

        dcol = "_dishonly_" + col
        if dcol in df.columns:
            out_d = df[dcol] + extra
            out_d[missing] = np.nan
            df[dcol + CKD_MINERAL_CONSERVATIVE_SUFFIX] = out_d


# [FIX — DEV_LOG Entry 26] ANN ที่โหลดจากไฟล์ต้องทาย cluster ตรงกับ KMeans
# ปัจจุบันอย่างน้อยเท่านี้บนชุด train ไม่งั้นเทรนใหม่ (ANN ที่เพิ่งเทรนปกติ
# ได้ ~98% ตามตาราง 4.3 ในรายงาน)
ANN_MIN_AGREEMENT = 0.90

# [FIX — DEV_LOG Entry 26] โรคที่จำกัดโซเดียมเหลือ 1,500mg/วัน ใน
# adjust_features_by_disease — จานที่ไม่มีข้อมูลโซเดียมจริงจะไม่ถูกแนะนำ
SODIUM_STRICT_DISEASES = {"hypertension", "heart", "ckd"}

# [FIX — DEV_LOG Entry 35] กลุ่มอาหารโพแทสเซียมสูงที่ผู้ป่วยไตควรเลี่ยง (ตาม
# เอกสาร ckd_002 / CKD_SAFETY_RULE) — ใช้กับแถวที่ K เป็นค่าประมาณเท่านั้น
# [DEV_LOG Entry 50] ปรับตามตาราง 10.2 ของข้อแนะนำเวชปฏิบัติ CKD 2565 (สมาคมโรคไตฯ)
# — กลุ่ม "โพแทสเซียมสูง (250-350 มก./100 ก.)" ทั้งผักและผลไม้ ส้มโอ/ส้มเขียวหวานอยู่ในกลุ่ม
# "ต่ำถึงปานกลาง" ของตารางไทย จึงเอาออก (เดิมใส่ตามความรู้ทั่วไป) แต่น้ำส้มคั้นยังอยู่กลุ่มสูง
# + ของเดิมที่ไม่ขัดตาราง (มะเขือเทศ ถั่วเมล็ดแห้ง ลูกเดือย อินทผลัม มะละกอสุก)
CKD_HIGH_K_NAME_PATTERN = ("กล้วย|ฝรั่ง|ขนุน|ทุเรียน|น้อยหน่า|กระท้อน|ลำไย|ลูกพลับ|ลูกพรุน|ลูกเกด|"
                           "มะม่วง|มะเฟือง|มะปราง|มะขามหวาน|แคนตาลูป|ฮันนี่ดิว|น้ำส้มคั้น|น้ำมะพร้าว|"
                           "มะละกอสุก|อินทผลัม|"
                           "เห็ด|หน่อไม้ฝรั่ง|บรอค|บร็อค|ดอกกะหล่ำ|แครอท|กะหล่ำดาว|ผักโขม|ผักบุ้ง|คะน้า|"
                           "กวางตุ้ง|ใบแค|ข้าวโพด|มันเทศ|มันฝรั่ง|ฟักทอง|อะโวคาโด|อโวคาโด|มะเขือเทศ|"
                           "กระเจี๊ยบ|ผักแว่น|ผักหวาน|สะเดา|หัวปลี|"
                           "ถั่วเขียว|ถั่วดำ|ถั่วแดง|ลูกเดือย")
# [DEV_LOG Entry 46/50] โปรตีนสูงสุดสำหรับ CKD (g ต่อ กก. น้ำหนักอุดมคติ ต่อวัน) ตามข้อแนะนำ
# เวชปฏิบัติ CKD 2565 ข้อ 6.11/10.3: ไม่เป็นเบาหวาน ≤0.6, เป็นเบาหวานร่วม 0.6-0.8 (ใช้ 0.8)
CKD_PROTEIN_G_PER_KG = 0.6
CKD_DM_PROTEIN_G_PER_KG = 0.8
CKD_PROTEIN_MEAL_TOL = 1.25   # เพดานโปรตีนต่อมื้อ (ยอมให้เกินงบมื้อได้ 25% — งบทั้งวันยังคุมอยู่)

# [DEV_LOG Entry 46] โรคหัวใจ: ข้อมูลอาหารไทย (Thai FCD/INMU) ที่ใช้ไม่มีคอลัมน์
# ไขมันอิ่มตัว — ใช้ชื่ออาหารกลุ่มที่รู้กันว่าไขมันอิ่มตัวสูง (กะทิ, มันหมู/หนัง,
# เนย/ชีส/ครีม, ไส้กรอก/เบคอน) กรองออกแทน ตามแนวทาง AHA/กรมอนามัย ที่ให้จำกัด
# ไขมันอิ่มตัว (< 6-10% ของพลังงาน) — เป็น heuristic เหมือน CKD_HIGH_K_NAME_PATTERN
HEART_HIGH_SATFAT_NAME_PATTERN = ("กะทิ|แกงเขียวหวาน|มัสมั่น|พะแนง|ฉู่ฉี่|แกงเผ็ด|ต้มข่า|แกงคั่ว|"
                                  "หมูกรอบ|ขาหมู|คากิ|สามชั้น|หนังไก่|หนังหมู|แคบหมู|มันหมู|ไขมันหมู|"
                                  "เนย|ชีส|ครีม|ไส้กรอก|เบคอน|กุนเชียง|ข้าวมันไก่|ข้าวมัน,|หมูสับทอด|"
                                  "ปาท่องโก๋|โดนัท|ครัวซองต์|พาย|"
                                  # [Entry 69] ของทอด/ไข่เจียว (ทดสอบจริง: ปูนิ่มทอดกระเทียมถูกแนะนำให้ผู้ป่วยหัวใจ)
                                  # แนวทางโรคหัวใจ/ความดันแนะนำเลี่ยงอาหารทอดน้ำมันมาก
                                  "ทอด|ไข่เจียว|เจียวฝรั่ง")
HEART_SATFAT_EXCEPT_PATTERN = "ไม่ใส่กะทิ|ครีมเทียมไขมันต่ำ"
CKD_HIGH_K_EXCEPT_PATTERN = "หยวกกล้วย|ใบตอง|ฝรั่งเศส"

# [DEV_LOG Entry 35] ชื่อที่บ่งว่าเป็นขนม/ของว่าง (นอกเหนือหมวด dessert_snack
# จาก SERVING_MAP) — ไม่แนะนำเป็นมื้อหลัก
SNACK_NAME_PATTERN = ("ขนม(?!จีน|จีบ)|อบกรอบ|ปาท่องโก๋|ซาลาเปา|เค้ก|คุกกี้|คุ้กกี้|"
                      "ซอฟท์โรล|พาย|โดนัท|กาละแม|สาคู|ข้าวต้มมัด|ข้าวเหนียวปิ้ง|"
                      "ข้าวเหนียวมูน|ข้าวตัง|ข้าวแต๋น|(?<!หยวก)(?<!แกง)กล้วย|(?<!แกง)เผือก|มันเทศ|เชื่อม|"
                      "ลอดช่อง|บัวลอย|ไอศกรีม|วุ้น(?!เส้น)|เยลลี่|พุดดิ้ง|เอแคลร์|ครัวซองต์|เวเฟอร์")

# [FIX — DEV_LOG Entry 31] ขนาดจานที่ระบบเลือกให้ได้ตอนแนะนำเมนู — ตัวคูณต้อง
# ตรงกับ PORTION_MUL ใน db/database.py (ใช้ตอนบันทึก food_logs) ไม่งั้นค่าที่
# บันทึกจะไม่ตรงกับที่แนะนำ
ENABLE_PORTION_SCALING = True
PORTION_MULTIPLIERS = {"normal": 1.0, "small": 0.75, "large": 1.35}
PORTION_LABEL_TH = {"small": "จานเล็ก", "normal": "", "large": "จานใหญ่"}
PORTION_SCALE_COLS = FEATURES + [
    "potassium_mg" + "_ckd_conservative", "phosphorus_mg" + "_ckd_conservative", "_serving_g",
]


# [FIX — DEV_LOG Entry 27] เลข cluster ตายตัวตามความหมาย ให้ตรงกับรายงาน
# บทที่ 4 ตาราง 4.2: Cluster 0 = พลังงานปานกลาง, Cluster 1 = พลังงานสูง,
# Cluster 2 = พลังงานต่ำ (low-calorie, ใช้กับ Disease Override)
CLUSTER_ID_BY_ENERGY_RANK = {0: 2, 1: 0, 2: 1}   # อันดับพลังงาน (ต่ำ→สูง) → เลข cluster


def relabel_clusters_by_energy(kmeans) -> dict:
    """คืน dict {เลขดิบของ KMeans: เลขตามรายงาน} โดยเรียง centroid ตามค่า
    energy_kcal (มิติแรกของ FEATURES ใน scaled space — StandardScaler ไม่เปลี่ยน
    ลำดับ จึงเรียงได้ตรงกับพลังงานจริง)"""
    e_idx = FEATURES.index("energy_kcal")
    order = np.argsort(kmeans.cluster_centers_[:, e_idx])   # raw id เรียงจากพลังงานต่ำ→สูง
    return {int(raw): CLUSTER_ID_BY_ENERGY_RANK[rank] for rank, raw in enumerate(order)}


_ALIASES = None


def _food_aliases() -> dict:
    """[Entry 58] food_aliases.csv → {ชื่อ normalize: food_id} (โหลดครั้งเดียว)"""
    global _ALIASES
    if _ALIASES is None:
        _ALIASES = {}
        path = os.getenv("FOOD_ALIASES_CSV", "food_aliases.csv")
        if os.path.exists(path):
            try:
                a = pd.read_csv(path, encoding="utf-8-sig")
                _ALIASES = {_norm_name(r.alias): int(r.food_id) for r in a.itertuples()}
            except Exception as e:
                log.warning(f"โหลด {path} ไม่สำเร็จ: {e}")
    return _ALIASES


def _norm_name(s) -> str:
    """[DEV_LOG Entry 29] normalize ชื่ออาหารไว้เทียบ: ตัวเล็ก ตัดช่องว่าง/
    จุลภาค และส่วนท้าย " + ข้าวสวย" ที่การ์ดแนะนำเมนูต่อท้ายไว้"""
    if not isinstance(s, str):
        return ""
    s = s.lower().replace("+ ข้าวสวย", "").replace("+ข้าวสวย", "")
    s = s.replace(",", "").replace(" ", "").strip()
    # [Entry 56] สะกดต่างกันระหว่างผู้ใช้กับฐานข้อมูล (ฐานมีทั้ง "กะเพรา" และ "กระเพรา")
    for wrong, right in _SPELLING_VARIANTS:
        s = s.replace(wrong, right)
    return s


_SPELLING_VARIANTS = (("กระเพรา", "กะเพรา"), ("กะเพา", "กะเพรา"), ("ก๋วยเตี๊ยว", "ก๋วยเตี๋ยว"),
                      ("ก๊วยเตี๋ยว", "ก๋วยเตี๋ยว"), ("แซนด์วิช", "แซนวิช"), ("แซนวิด", "แซนวิช"),
                      ("ครัวซอง", "ครัวซองต์"), ("ครัวซองต์ต์", "ครัวซองต์"), ("ซีอิ้ว", "ซีอิ๊ว"),
                      ("คะแหนง", "คะน้า"))   # [Entry 76] ทดสอบจริง "คะแหนงหมูกรอบ"


def _training_fingerprint(X: pd.DataFrame, y) -> str:
    """hash ของข้อมูลที่ใช้เทรน ANN (ค่า FEATURES ต่อมื้อ + label KMeans)
    ข้อมูลเปลี่ยน/ลำดับ cluster เปลี่ยน → hash เปลี่ยน → เทรน ANN ใหม่"""
    h = hashlib.sha256()
    h.update(",".join(FEATURES).encode())
    h.update(np.ascontiguousarray(X.to_numpy(dtype=float).round(4)).tobytes())
    h.update(np.asarray(y, dtype=np.int64).tobytes())
    return h.hexdigest()[:16]

SERVING_MAP = [
    # [FIX — DEV_LOG Entry 31] กฎเฉพาะที่ต้องมาก่อน — ชื่ออังกฤษพวกนี้มีคำว่า
    # "sauce"/"dip" ที่จะถูกจับเป็นน้ำจิ้ม 80g ผิดๆ (เช่น "Steamed fish with soy
    # sauce", "Doughnut, honey dip", "Chicken with Teriyaki Sauce")
    (["steamed fish","steamed squid","chicken with chili paste","braised pork"], 150, "stirfry_side"),
    (["omelet","scrambled","egg, hen, steamed","steam egg","egg cup","steamed crab",
      "teriyaki sauce","baked, with sauce","sweet pork"], 100, "protein_side"),
    (["spicy raw shrimp"], 150, "salad_yum"),
    (["sweet brown sauce"], 200, "curry_soup"),
    (["doughnut","dipped with egg"], 80, "dessert_snack"),
    # [FIX — DEV_LOG Entry 13] เดิม 400g เทียบกับ dish จริง (ข้าวมันไก่,
    # ข้าวผัด, ข้าวราดแกง) แล้วสูงไปหน่อย (เฉลี่ย 620 kcal/จาน เทียบกับที่
    # มักอ้างกันทั่วไป ~500-600 kcal/จาน) ลดเป็น 350g ให้ใกล้เคียงขึ้น
    (["rice topped","fried rice","rice with","rice cooked",
      "rice and glutinous","rice boiled with coconut","brown rice topped"], 350, "rice_dish"),
    (["noodles","noodle","suki","wonton"], 400, "noodle_soup"),
    (["round rice noodles"], 350, "khanom_jeen"),
    (["curry","soup","stew","tom-kha","gaeng","kang"], 200, "curry_soup"),
    (["salad","spicy minced","spicy beef","spicy rice","papaya",
      "spicy vegetable","budu","spirulina"], 150, "salad_yum"),
    (["stir-fried","fried","stir fry"], 150, "stirfry_side"),
    (["grilled","canned","steamed tuna","steamed saba","steamed sardine",
      "dried shredded","sausage"], 100, "protein_side"),
    (["sauce","paste","dip","nam-prik","namprik"], 80, "dip_sauce"),
    # ── [FIX — DEV_LOG Entry 31] sync keyword ที่เพิ่มใน Model3_v3_fixed.ipynb
    # (cell 9) ซึ่งไม่เคยถูกย้ายมา production — เดิม 38% ของ dish ตก "other"
    # 300g เท่ากันหมด (ขนม/ซีฟู้ด/ฟาสต์ฟู้ด) ลำดับเดียวกับ notebook ─────────
    (["fish","mackerel","tuna","sardine","cockle","clam",
      "shrimp","seasoned","flavors"], 100, "protein_side"),
    (["chopped beef","chopped pork","minced"], 150, "salad_yum"),
    (["ice cream","cake","cookie","cookies","pudding","pie",
      "toffee","tiramisu","jelly","thong-yodd","ka-nom",
      "ka-la-mae","crepe","mochi","biscuit"], 80, "dessert_snack"),
    (["roast","roasted","roasting","satay","baked","chicken pop"], 100, "protein_side"),
    (["risotto","khao-niao","glutinous rice, steamed"], 300, "rice_dish"),
    (["sherbet","nata de coco","sangkhaya","custard","thong-yip",
      "tao-suan","tong-muan","luk chup","donut","rhombic",
      "khao-maak","coconut milk with syrup"], 80, "dessert_snack"),
    (["pizza","burger","sandwich","sandwiches","gyoza","french fries"], 250, "fastfood"),
    (["congee","ramen"], 400, "noodle_soup"),
    (["deep fry","ground,","crumbles","chicken paper","tender,"], 100, "protein_side"),
    (["roti","poached","pan bread","salapao"], 100, "protein_side"),
    # ── [DEV_LOG Entry 31] เพิ่มเติมจากที่ยังตก "other" หลัง sync ──────────
    (["khao soi","guay-teaw","kuay-teaw"], 400, "noodle_soup"),
    (["tom-leud"], 200, "curry_soup"),
    (["in coconut milk","in sweet coconut milk","syrup","added sugar","mock jackfruit",
      "sa-rim","kluay-buad","kra-ya-sart","snack bar","crispy, original"], 80, "dessert_snack"),
    (["miang"], 100, "salad_yum"),
    (["hot dog","kebab","big mac","mcdonald","bun"], 200, "fastfood"),
    (["chicken, breast","pork, fresh","spareribs","cooked, braised","loin"], 100, "protein_side"),
    (["vegetarian"], 150, "stirfry_side"),
]
DEFAULT_SERVING_G = 300

# [DEV_LOG Entry 58] ขนาดต่อมื้อ/หมวดกำหนดตาม food_id (ชนะกฎจากชื่อ) — 1 จาน = ปริมาณที่กินจริง
SERVING_OVERRIDE_BY_ID = {
    90100: (100, "dessert_snack"),   # ปอเปี๊ยะทอด ~4 ชิ้น (ของว่าง/กับแกล้ม ไม่บวกข้าว)
    90104: (100, "dessert_snack"),   # เกี๊ยวทอด ~8 ชิ้น
    90106: (150, "protein_side"),    # หอยนางรมสด 1 จาน (~6 ตัว + น้ำจิ้ม) ไม่บวกข้าว
    # [Entry 59] ชื่ออังกฤษจับหมวดผิด
    22449: (350, "rice_dish"),       # คัตสึด้ง (ข้าวหน้าหมูทอด) — เดิม "fried" → กับข้าว 150 g + ข้าวซ้ำ
    11230: (150, "protein_side"),    # หมี่กึงรวม (เจ) = กลูเตน ไม่ใช่เส้น — เดิมก๋วยเตี๋ยวน้ำ 400 g
    11209: (100, "dessert_snack"),   # เกี๊ยวทอด (เจ) — เดิมก๋วยเตี๋ยวน้ำ 400 g = 788 kcal
    # [Entry 70] เครื่องดื่ม 1 แก้ว (~16 oz รวมน้ำแข็ง) — หมวดของว่าง: ไม่แนะนำเป็นมื้อหลัก ไม่บวกข้าว
    90200: (325, "dessert_snack"),   # ชาไทยเย็น ~204 kcal
    90201: (300, "dessert_snack"),   # ชาไทยเย็น หวานน้อย ~114 kcal
    90202: (325, "dessert_snack"),   # ชาดำเย็น ~100 kcal
    90203: (325, "dessert_snack"),   # ชาเขียวนมเย็น ~204 kcal
    90204: (325, "dessert_snack"),   # กาแฟเย็น ~203 kcal
    90205: (300, "dessert_snack"),   # กาแฟเย็น หวานน้อย ~113 kcal
    90206: (325, "dessert_snack"),   # โอเลี้ยง ~99 kcal
    90207: (290, "dessert_snack"),   # นมเย็น ~246 kcal
    # [Entry 74] ของที่กินเป็น "ชิ้น/ฟอง/จาน" ไม่ใช่ 100 g (ทดสอบจริง: พิมพ์/ถ่ายรูปข้าวสวย = 100 g,
    # ไข่ดาว 1 ฟอง = 150 g + ข้าว 553 kcal) — วัตถุดิบในรายการนี้ไม่ใช้กติกา 100 g ด้านล่าง
    21783: (160, "ingredient_portion"),  # ข้าวสวย 1 จาน (~2 ทัพพีครึ่ง) ~208 kcal
    20005: (160, "ingredient_portion"),  # ข้าวกล้องสุก 1 จาน
    20010: (100, "ingredient_portion"),  # ข้าวเหนียวนึ่ง 1 ห่อเล็ก
    21944: (50, "ingredient_portion"),   # ไข่ต้ม 1 ฟอง
    21092: (50, "ingredient_portion"),   # ไข่ไก่ต้ม 1 ฟอง
    22068: (60, "protein_side"),         # ไข่ดาว 1 ฟอง ~117 kcal
    21091: (70, "protein_side"),         # ไข่เจียว 1 ฟอง (ทอดน้ำมัน) ~253 kcal
}

# [FIX — DEV_LOG Entry 10] "กับข้าวอย่างเดียว" (side_only) เช่น ผัดกะเพรา/
# แกง/ไก่ย่าง/น้ำพริก ไม่มีข้าวรวมอยู่ในจาน แต่คนกินจริงจะตักข้าวคู่กันเสมอ
# ถ้าปล่อยให้โมเดลเห็นแค่ค่าโภชนาการของกับอย่างเดียว จะได้ carb/energy ต่ำ
# กว่าที่กินจริงมาก (รูปแบบเดียวกับบั๊กพลังงานขาดใน Entry 5) — หมวดที่ถือว่า
# "มีข้าว/แป้งหลักรวมอยู่แล้ว" (rice_dish, noodle_soup, khanom_jeen) และ
# "other" (มักเป็นของสำเร็จรูปเอง เช่น แซนวิช/พิซซ่า/เค้ก) ไม่ต้องบวกข้าวเพิ่ม
#
# [FIX — DEV_LOG Entry 14] บวกข้าวเฉพาะ "โครงสร้างเป็นของคู่ข้าว" จริงๆ
# (dip_sauce/stirfry_side/curry_soup — กินเดี่ยวๆ ไม่ได้ตามธรรมชาติของจาน)
# ตัด protein_side (ไก่ย่าง/ปลาทอด ฯลฯ) กับ salad_yum (ยำ) ออก เพราะกลุ่มนี้
# กินเป็นมื้อโปรตีนล้วน/สลัดเดี่ยวๆ ได้จริงบ่อย โดยเฉพาะกลุ่มเป้าหมาย NCD ที่
# หมอมักแนะนำให้ลดข้าวเพิ่มโปรตีน/ผัก — บวกข้าวอัตโนมัติให้ 2 กลุ่มนี้เสี่ยง
# over-estimate จนระบบตัดจานดีๆ ออกจากคำแนะนำทั้งที่ไม่ควรตัด (ผู้ใช้ตัดสินใจ
# เลือกทางนี้เอง หลังชั่งน้ำหนักกับความเสี่ยง under-estimate ที่กลับมาบางส่วน)
SIDE_ONLY_CATEGORIES = {"curry_soup", "stirfry_side", "dip_sauce"}
RICE_PORTION_G = 200  # ข้าวสวย 1 ทัพพีใหญ่ ~200g (ปริมาณมาตรฐานต่อมื้อ)
# อ้างอิง food_id 21783 "ข้าว, ขาว (ข้าวสวย)" (Rice, white, long-grain,
# regular, cooked) ในฐานข้อมูล — water_g/calcium_mg/magnesium_mg ไม่มีใน
# แหล่งข้อมูลนี้ ใช้ค่ามาตรฐานโภชนาการข้าวสุกทั่วไปแทน (USDA FoodData Central,
# white rice, cooked, per 100g)
NO_RICE_ADD_OVERRIDE_IDS = {
    # [FIX — DEV_LOG Entry 12] แถวเหล่านี้ถูก keyword classifier จัดเข้า
    # SIDE_ONLY_CATEGORIES ผิด (คำในชื่อจับ "fried"/"grilled"/"salad"/"dip"
    # แบบ substring แต่ตัวจานจริงๆ มีข้าว/แป้ง/ขนมปังรวมอยู่แล้ว หรือเป็น
    # ของว่าง/ของหวานที่ไม่ได้กินคู่ข้าว) เจอตอนตรวจสอบ carb_available_g
    # ที่สูงผิดปกติ (>25g/100g) สำหรับ category ที่ควรจะเป็น "กับอย่างเดียว"
    # — บวกข้าวให้แถวพวกนี้จะกลายเป็นนับซ้ำซ้อน (double count)

    # มีข้าว/แป้งเหนียวรวมอยู่ในจานแล้ว (ชื่อมีคำว่าข้าวโดยตรง)
    22150, 22149,  # ข้าวพองปลาหยอง (ข้าวพอง = rice snack)
    21576,         # ข้าวตัง (rice cracker, fried)
    11089,         # ข้าวเหนียวชุบไข่, ปิ้ง
    21587,         # ข้าวเหนียวปิ้ง, ไส้กล้วย
    21506,         # ขนมจาก (ข้าวเหนียวดำ+มะพร้าว ห่อใบตาล)
    22595,         # ข้าวไก่ผัดพริกแกง ("...on Rice")
    11165,         # ข้าวยำคลุก (rice salad — มีคำว่า "salad" แต่จริงๆ คือข้าวยำ)
    22766,         # ข้าวยำไก่แซ่บ (rice salad เช่นกัน)

    # ของทอด/ของว่าง/ของหวาน ไม่ใช่ "กับข้าว" ที่กินคู่ข้าวสวย
    22415, 21560, 21563,  # กล้วยทอด/กล้วย ทอด/กล้วยหอมทอดกรอบ (fried banana)
    22391, 21616,         # เผือก ทอด / เผือกชุบแป้งทอด
    21626,                 # มันเทศชุบแป้งทอด
    21613, 21614, 22459,   # ปาท่องโก๋ / ปาท่องโก๋ซาลาเปา / ซาลาเปาทอด (แป้ง/ขนมปังอยู่แล้ว)
    21334,                 # โดนัท ฮันนี่ดิพ ("honey dip" ไปจับคำว่า dip)
    11236,                 # ขนมกะหรี่ปั๊บ (curry puff — pastry ของว่าง ไม่ใช่แกงกินคู่ข้าว)

    # ขนมปัง/แซนวิช มีแป้งอยู่ในตัวเองแล้ว (ไปจับคำว่า "salad"/"sausage" ในชื่อ)
    22736,          # ขนมปังไส้กรอก อีซี่เบค (sausage BREAD)
    22200, 22439,   # แซนวิชไส้ปูอัด / แซนวิชไส้สลัดแซลมอน (sandwich)
    22709,          # โกลด์เบรด ขนมปังหมูหยองน้ำสลัด (bread)
}
RICE_REF_PER100G = {
    "energy_kcal": 130.0, "water_g": 68.4, "protein_g": 2.7, "fat_g": 0.3,
    "carb_available_g": 28.2, "sodium_mg": 1.0, "potassium_mg": 35.0,
    "calcium_mg": 10.0, "magnesium_mg": 12.0, "phosphorus_mg": 43.0,
}


# ════════════════════════════════════════════════════════════════════
# 1. BMR / TDEE / Macro  (ตรงจาก Cell 34, 36, 38 v3)
# ════════════════════════════════════════════════════════════════════

def calculate_bmr(age, gender, weight_kg, height_cm):
    g = gender.lower().strip()
    if g == "male":   return (10*weight_kg)+(6.25*height_cm)-(5*age)+5
    if g == "female": return (10*weight_kg)+(6.25*height_cm)-(5*age)-161
    raise ValueError("gender must be 'male' or 'female'")

def calculate_tdee(bmr, activity_level):
    af = {1:1.2, 2:1.375, 3:1.55, 4:1.725, 5:1.9}
    if activity_level not in af: raise ValueError("activity_level 1-5")
    return bmr * af[activity_level]

def calculate_bmi(weight_kg, height_cm):
    h_m = height_cm / 100
    return weight_kg / (h_m ** 2)

def bmi_category(bmi):
    """
    ใช้เกณฑ์ Asian-Pacific BMI cutoff (WHO Western Pacific Region) แทน
    เกณฑ์สากล เพราะเหมาะกับประชากรไทย/เอเชียมากกว่า (คนเอเชียมีความเสี่ยง
    โรค NCD สูงขึ้นตั้งแต่ BMI ต่ำกว่าเกณฑ์สากล)
    """
    if bmi < 18.5: return "underweight"
    if bmi < 23:   return "normal"
    if bmi < 25:   return "overweight"
    return "obese"

# ลดพลังงาน 500 kcal/วัน เมื่อ BMI เข้าเกณฑ์ overweight ขึ้นไป — อ้างอิงแนวทาง
# เดียวกับที่ใช้ใน rag/ncd_knowledge.py (ob_001: "ลดพลังงาน 500-750 กิโลแคลอรี
# ต่อวัน เพื่อลดน้ำหนัก 0.5-1 กก./สัปดาห์ อย่างปลอดภัย") เลือกใช้ค่าต่ำสุดของ
# ช่วงเพื่อความปลอดภัย ไม่ต้องคำนวณซับซ้อนเกินความจำเป็นของแชทบอท
BMI_DEFICIT_KCAL      = 500
MIN_SAFE_ENERGY_KCAL  = 1200   # พื้นปลอดภัย ไม่ให้พลังงานเป้าหมายต่ำเกินไปไม่ว่ากรณีใด

def apply_bmi_deficit(tdee: float, weight_kg: float, height_cm: float):
    """
    คืน (target_energy, bmi, bmi_category)
    BMI >= 23 (overweight/obese ตามเกณฑ์เอเชีย) → หัก deficit
    BMI ปกติหรือต่ำกว่า → ไม่ deficit ไม่ว่า goal ที่ผู้ใช้เลือกจะเป็นอะไร
    (ยึด BMI จริงเป็นหลัก ไม่ยึดความต้องการ/self-report)
    """
    bmi = calculate_bmi(weight_kg, height_cm)
    cat = bmi_category(bmi)
    if cat in ("overweight", "obese"):
        target = max(tdee - BMI_DEFICIT_KCAL, MIN_SAFE_ENERGY_KCAL)
    else:
        target = tdee
    return round(target, 2), round(bmi, 1), cat


def calculate_micronutrients_basic(age, gender):
    g = gender.lower().strip()
    sodium_mg    = 2000
    potassium_mg = 3400 if g == "male" else 2600
    calcium_mg   = (1200 if g == "female" else 1000) if age >= 51 else 1000
    magnesium_mg = (400 if age<=30 else 420) if g=="male" else (310 if age<=30 else 320)
    # [FIX — Entry 15] ค่าเริ่มต้นทั่วไปสำหรับผู้ใหญ่ (RDA ทั่วไป ~700mg/วัน)
    # ไม่แยกตามอายุ/เพศเหมือนตัวอื่นเพราะความต้องการฟอสฟอรัสของผู้ใหญ่ทั่วไป
    # ไม่ต่างกันมากนัก — ค่านี้จะถูกจำกัดแคบลงถ้าเป็น CKD ใน
    # adjust_features_by_disease
    phosphorus_mg = 700
    return sodium_mg, potassium_mg, calcium_mg, magnesium_mg, phosphorus_mg

def build_feature_vector(age, gender, weight_kg, height_cm, activity_level,
                         carb_ratio=0.50, protein_ratio=0.20, fat_ratio=0.30):
    bmr  = calculate_bmr(age, gender, weight_kg, height_cm)
    tdee = calculate_tdee(bmr, activity_level)
    # [BMI deficit] พลังงานเป้าหมายจริงคำนวณจาก BMI ไม่ใช่ TDEE ตรงๆ —
    # ถ้า BMI เข้าเกณฑ์ overweight/obese จะหัก deficit ให้อัตโนมัติ ไม่ว่า
    # ผู้ใช้จะติ๊กโรคอ้วนไว้หรือเลือก goal อะไรก็ตาม (ดู apply_bmi_deficit)
    target_energy, bmi, bmi_cat = apply_bmi_deficit(tdee, weight_kg, height_cm)
    carb    = (target_energy*carb_ratio)/4
    protein = (target_energy*protein_ratio)/4
    fat     = (target_energy*fat_ratio)/9
    na, k, ca, mg, ph = calculate_micronutrients_basic(age, gender)
    return bmr, tdee, bmi, bmi_cat, {
        "energy_kcal": round(target_energy,2), "water_g": round(weight_kg*35,2),
        "protein_g": round(protein,2), "fat_g": round(fat,2),
        "carb_available_g": round(carb,2),
        "sodium_mg": float(na), "potassium_mg": float(k),
        "calcium_mg": float(ca), "magnesium_mg": float(mg),
        "phosphorus_mg": float(ph),
    }

def ideal_body_weight(height_cm, gender):
    """[Entry 50] น้ำหนักอุดมคติ (กก.) ตามแนวทางไทย — None ถ้าไม่รู้ส่วนสูง"""
    if not height_cm:
        return None
    return max(float(height_cm) - (100 if str(gender).lower().startswith("m") else 105), 30.0)


def adjust_features_by_disease(features_dict, diseases, weight_kg, age, gender, height_cm=None):
    """
    หมายเหตุ: เดิมมี `if "obesity" in diseases: e*=0.90` ตรงนี้ — ย้ายออกแล้ว
    เพราะ deficit ควรมาจาก BMI จริง (คำนวณใน build_feature_vector ก่อนหน้า
    ผ่าน apply_bmi_deficit) ไม่ใช่จากการที่ผู้ใช้ติ๊กเลือกโรคอ้วนเอง
    ฟังก์ชันนี้ทำหน้าที่ปรับสัดส่วนสารอาหาร (macro ratio) ตามโรคเท่านั้น
    ไม่ยุ่งกับพลังงานรวมอีกต่อไป
    """
    e=float(features_dict["energy_kcal"]); na=float(features_dict["sodium_mg"])
    k=float(features_dict["potassium_mg"]); ca=float(features_dict["calcium_mg"])
    mg=float(features_dict["magnesium_mg"]); cr,pr,fr=0.50,0.20,0.30
    # [FIX — DEV_LOG Entry 15] phosphorus_mg เป็นฟิลด์ใหม่ ใช้ .get เพื่อ
    # backward-compat กับ caller เก่าที่อาจยังไม่ส่งค่านี้มา (default RDA ~700mg)
    ph = float(features_dict.get("phosphorus_mg", 700))
    if "diabetes" in diseases:
        # [Entry 50] แนวทางเวชปฏิบัติเบาหวาน 2566: โปรตีน 10-15% (≥1 g/กก.) และ ~20% เมื่อ
        # ต้องลดน้ำหนัก — เดิม 25% สูงกว่าแนวทาง ใช้ 20% (คาร์บ 45% ไขมัน 35%)
        cr=min(cr,0.45); pr=max(pr,0.20); fr=1.0-cr-pr
    if "heart" in diseases:
        fr=min(fr,0.28); pr=max(pr,0.22); cr=1.0-pr-fr; na=min(na,1500)
    if "hypertension" in diseases:
        na=min(na,1500)
        if "ckd" not in diseases: k=max(k,3500)
    if "ckd" in diseases:
        na=min(na,1500); k=min(k,2000); pr=min(pr,0.18)
        rem=1.0-pr; cr=min(cr,0.52); fr=rem-cr
        if fr<0.20: fr=0.20; cr=rem-fr
        # [FIX — DEV_LOG Entry 15] CKD ต้องจำกัดฟอสฟอรัส (ทั่วไป ~800-1000mg/วัน
        # ตามแนวทาง CKD diet) — ลดจากค่าเริ่มต้น 700 ถ้าสูงกว่านี้ ให้เป็น ceiling
        ph = min(ph, 1000)
        # [FIX — DEV_LOG Entry 46] โปรตีน CKD (ยังไม่ฟอกไต) ตามแนวทาง KDOQI 2020
        # และสมาคมโรคไตฯ = 0.6-0.8 g/กก./วัน (ตรงกับเอกสาร RAG) — เดิมใช้ 18%
        # ของพลังงาน ซึ่งคนน้ำหนัก 70 กก. กิน 1,800 kcal ได้ ~81 g (1.16 g/กก.)
        # ใช้ขอบบน 0.8 g/กก. พลังงานที่ลดจากโปรตีนย้ายไปคาร์บ/ไขมัน (พลังงานรวมคงเดิม)
        # [Entry 50] น้ำหนักอุดมคติตามแนวทางไทย (CKD 2565 ข้อ 10.2, DM CPG 2566):
        # ชาย = ส่วนสูง(ซม.) − 100, หญิง = ส่วนสูง − 105 (เดิมใช้ BMI 22 × ส่วนสูง²)
        ibw = ideal_body_weight(height_cm, gender) or weight_kg
        g_per_kg = CKD_DM_PROTEIN_G_PER_KG if "diabetes" in diseases else CKD_PROTEIN_G_PER_KG
        pr = min(pr, g_per_kg * ibw * 4 / max(e, 1))
        rem = 1.0 - pr
        # ไขมัน 20-35% ของพลังงาน (เบาหวานร่วม: ยอมไขมันถึง 40% เพื่อไม่ให้คาร์บพุ่ง)
        fat_max = 0.40 if "diabetes" in diseases else 0.35
        cr = min(rem - 0.20, max(cr, rem - fat_max))
        fr = rem - cr
    water = max(float(features_dict["water_g"]), weight_kg*30)
    return {
        "energy_kcal": round(e,2), "water_g": round(water,2),
        "protein_g": round((e*pr)/4,2), "fat_g": round((e*fr)/9,2),
        "carb_available_g": round((e*cr)/4,2),
        "sodium_mg": round(na,2), "potassium_mg": round(k,2),
        "calcium_mg": round(ca,2), "magnesium_mg": round(mg,2),
        "phosphorus_mg": round(ph,2),
    }

def features_to_list(fd):
    return [fd[f] for f in FEATURES]


# ════════════════════════════════════════════════════════════════════
# 2. Cluster → Disease mapping  (Cell 40 v3)
# ════════════════════════════════════════════════════════════════════

def get_cluster_profiles(df):
    return df.groupby("clusters")["energy_kcal"].mean().to_dict()

def map_cluster_for_disease(pred_cluster, diseases, df):
    low_cal = {"diabetes","obesity","ckd","heart"}
    if not diseases.intersection(low_cal):
        return pred_cluster, "no override"
    profiles    = get_cluster_profiles(df)
    low_cluster = min(profiles, key=profiles.get)
    if pred_cluster == low_cluster:
        return pred_cluster, f"already low-cal cluster {pred_cluster}"
    reason = f"override {pred_cluster}→{low_cluster} (diseases: {diseases & low_cal})"
    return low_cluster, reason


# ════════════════════════════════════════════════════════════════════
# 3. Serving size
# ════════════════════════════════════════════════════════════════════

import re as _re

# [FIX — DEV_LOG Entry 38] กฎจากชื่อไทย (เช็คก่อนชื่ออังกฤษ) — ชื่ออังกฤษหลาย
# แถวจับหมวดผิด เช่น "ข้าวผัดกะเพราไก่ ไข่ลวก" (มีคำว่า fried → กับข้าว 150g แล้ว
# ยังบวกข้าวซ้ำ), "ผัดไทยกุ้งสด" (มีคำว่า shrimp → 100g), "ยำวุ้นเส้น" (มีคำว่า
# noodle → ก๋วยเตี๋ยวน้ำ 400g)
_TH_RICE_EXCLUDE = ("ข้าวเกรียบ", "ข้าวโพด", "ข้าวตัง", "ข้าวแต๋น", "ข้าวเหนียวมูน",
                    "ข้าวเหนียวมูล", "ข้าวเหนียวมะม่วง", "ข้าวต้มมัด", "ข้าวเหนียวปิ้ง",
                    "ข้าวพอง", "ข้าวซอย", "ข้าวหลาม", "ข้าวเม่า", "ข้าว,", "ข้าวกล้อง,",
                    "ข้าวเหนียวชุบไข่", "ข้าวหมาก")
_TH_NOODLE_WORDS = ("ก๋วยเตี๋ยว", "เส้น", "บะหมี่", "หมี่", "วุ้นเส้น", "ยากิโซบะ", "ราเมน",
                    "สุกี้", "ผัดซีอิ๊ว", "อุด้ง", "อูด้ง", "สปาเก็ตตี้")


def _is_noodle(th: str) -> bool:
    return any(w in th for w in _TH_NOODLE_WORDS) and "หมี่กึง" not in th


# [DEV_LOG Entry 59] กลุ่มเส้น: เดิมทุกจานที่ชื่ออังกฤษมี "noodle" = ก๋วยเตี๋ยวน้ำ 400 g หมด ทั้ง
# แบบแห้ง/ผัด (ผัดซีอิ๊ว 400 g = 792 kcal, ก๋วยเตี๋ยวแห้ง 400 g = 1,084 kcal, หมี่กรอบ 400 g = 2,020 kcal)
# ปริมาณต่อจานที่ใช้ (ประมาณจากจานขายทั่วไป): น้ำ 400 g, แห้ง 250 g, ผัด/อบ 300 g, ขนมจีน 300 g,
# หมี่กรอบ (ของว่าง/กับแกล้ม) 100 g
SERVING_MAP_TH = [
    (lambda th: th.startswith("ข้าว") and not th.startswith(_TH_RICE_EXCLUDE), 350, "rice_dish"),
    (lambda th: "หมี่กรอบ" in th and "ราดหน้า" not in th, 100, "dessert_snack"),
    (lambda th: "ผัดไทย" in th, 300, "noodle_dish"),
    (lambda th: th.startswith("ยำ"), 150, "salad_yum"),
    (lambda th: _is_noodle(th) and "แห้ง" in th, 250, "noodle_dish"),
    (lambda th: _is_noodle(th) and any(w in th for w in ("ผัด", "คั่ว", "อบ")), 300, "noodle_dish"),
    (lambda th: _is_noodle(th) and "กะทิ" in th and "น้ำ" not in th, 300, "noodle_dish"),  # หมี่กะทิ
    (lambda th: th.startswith("ขนมจีน"), 300, "noodle_soup"),
]


def get_serving_g(food_name_en, food_name_th=None):
    if isinstance(food_name_th, str):
        th = food_name_th.strip()
        for rule, sg, cat in SERVING_MAP_TH:
            if rule(th):
                return sg, cat
    if not isinstance(food_name_en, str): return DEFAULT_SERVING_G, "other"
    nl = food_name_en.lower()
    for kws, sg, cat in SERVING_MAP:
        if any(k in nl for k in kws): return sg, cat
    return DEFAULT_SERVING_G, "other"


# ════════════════════════════════════════════════════════════════════
# 4. Dynamic budget helper  (ใหม่)
# ════════════════════════════════════════════════════════════════════

def compute_meal_limit(daily_limit, daily_used, meals_remaining):
    """
    meal_limit = (daily_limit - daily_used) / meals_remaining
    แก้ปัญหา limit เท่ากันทุกมื้อ
    """
    if meals_remaining <= 0: return {k: 0.0 for k in daily_limit}
    return {
        k: round(max((daily_limit.get(k,0) - daily_used.get(k,0)) / meals_remaining, 0), 4)
        for k in daily_limit
    }


# ════════════════════════════════════════════════════════════════════
# 5. NCDModel
# ════════════════════════════════════════════════════════════════════

class NCDModel:
    """
    โหลดครั้งเดียวตอน app start
    methods เป็น sync — เรียกจาก async ด้วย asyncio.to_thread()
    """

    def __init__(self, csv_path=None, model_save_path="models/ann_model.keras"):
        self.df = None
        self.scaler_full = None
        self.kmeans = None
        self.ann_final = None
        self.model_save_path = model_save_path
        self._ready = False
        if csv_path and os.path.exists(csv_path):
            self._prepare_and_train(pd.read_csv(csv_path))

    # ── init ──────────────────────────────────────────────────────

    def _prepare_and_train(self, df: pd.DataFrame):
        """serving normalize → scaler_full → KMeans → ANN  [FIX v3]"""
        from sklearn.cluster import KMeans
        import tensorflow as tf
        from tensorflow.keras.models import Sequential
        from tensorflow.keras.layers import Dense, Dropout
        from tensorflow.keras.callbacks import EarlyStopping

        # [FIX — DEV_LOG Entry 22] จำแถวที่ไม่มีข้อมูลแร่ธาตุ CKD จริงไว้ก่อน
        # เติม median (บรรทัดถัดไป) — ไม่งั้นแถวพวกนี้จะได้ค่า median ไปแล้ว
        # "ดูเหมือนมีข้อมูล" ทำให้ fail-safe ใช้ไม่ได้
        mineral_missing = {
            c: df[c].isna() if c in df.columns else pd.Series(False, index=df.index)
            for c in CKD_MINERAL_MARGIN_PER100G
        }
        # [FIX — DEV_LOG Entry 26] โซเดียมที่ไม่มีข้อมูลจริง (รวม 0 ปลอมจาก
        # calforlife ที่แปลงเป็น NaN แล้ว) — ใช้ทำ fail-safe ให้โรคที่ต้องคุม
        # โซเดียม (ดู SODIUM_STRICT_DISEASES)
        df["_sodium_missing"] = (
            df["sodium_mg"].isna() if "sodium_mg" in df.columns
            else pd.Series(False, index=df.index)
        )
        df[FEATURES] = df[FEATURES].fillna(df[FEATURES].median())

        # [FIX — DEV_LOG Entry 17] sugar_risk (1-5, ยิ่งมากยิ่งไม่เหมาะกับ
        # เบาหวาน) — คำนวณจาก carb_available_g quintile + keyword ชื่ออาหาร
        # (ดู scripts/compute_sugar_risk.py) ปกติ CSV/DB ที่ใช้จริง
        # (foods_master_v2.csv) จะมีคอลัมน์นี้คำนวณไว้แล้ว แต่เช็คไว้เผื่อ
        # โหลด CSV/DB เก่าที่ยังไม่มีคอลัมน์นี้ (backward-compat) — ยังไม่ได้
        # เอาไปใช้บังคับ hard-filter ในรอบนี้ เก็บไว้เป็นข้อมูลประกอบ (เช่น
        # ให้ LLM/Bandit ใช้ในอนาคต) เท่านั้น
        if "sugar_risk" not in df.columns and "carb_available_g" in df.columns:
            try:
                from scripts.compute_sugar_risk import compute_sugar_risk
                df["sugar_risk"] = compute_sugar_risk(df)
            except Exception as e:
                log.warning(f"sugar_risk fallback คำนวณไม่ได้: {e}")

        # [DEV_LOG Entry 46] น้ำตาลอิสระจากชื่อ (ของหวาน/เครื่องดื่มหวาน) — ใช้แทน
        # sugar_risk>=5 ในการกรองเบาหวาน (sugar_risk 5 ส่วนใหญ่มาจาก carb/100g สูง
        # เช่น แซนวิช ผัดหมี่ ซึ่งเพดานคาร์บต่อมื้อคุมอยู่แล้ว)
        try:
            from scripts.compute_sugar_risk import free_sugar_flag
            df["_free_sugar"] = free_sugar_flag(df)
        except Exception as e:
            log.warning(f"free_sugar_flag คำนวณไม่ได้ (ใช้ sugar_risk แทน): {e}")

        # rename DB columns ให้ตรงกับ FEATURES
        if "carb_g" in df.columns and "carb_available_g" not in df.columns:
            df = df.rename(columns={"carb_g": "carb_available_g"})

        # per-100g → per-serving (ถ้าไม่มี _serving_g แสดงว่ายังไม่ได้แปลง)
        if "_serving_g" not in df.columns:
            th_col = df["food_name_th"] if "food_name_th" in df.columns else pd.Series(None, index=df.index)
            df[["_serving_g","_food_category"]] = pd.DataFrame(
                [get_serving_g(en, th) for en, th in zip(df["food_name_en"], th_col)],
                index=df.index,
            )
            # [DEV_LOG Entry 58] เมนูที่ชื่อจับหมวดผิด (เช่น "spring rolls ... noodles" → ก๋วยเตี๋ยว
            # 400 g, "dipping sauce" → น้ำจิ้ม 80 g + ข้าว) — กำหนดขนาด/หมวดตาม food_id ตรงๆ
            if "food_id" in df.columns:
                for fid, (sg, cat) in SERVING_OVERRIDE_BY_ID.items():
                    m_ov = df["food_id"] == fid
                    df.loc[m_ov, "_serving_g"] = sg
                    df.loc[m_ov, "_food_category"] = cat
            # [FIX — DEV_LOG Entry 34] วัตถุดิบ/ของเดี่ยว (ผลไม้ ไข่ดิบ ฯลฯ) ไม่มี
            # "ขนาดจาน" — เดิมได้ค่า default 300g (ทดสอบจริง: "กินกล้วยได้ไหม"
            # → บอทตอบ "กล้วย 300 กรัม 300 kcal") ใช้ 100g แทน ตรงกับหน่วยใน
            # ตารางโภชนาการ (ไม่กระทบการแนะนำเมนู เพราะแนะนำเฉพาะ dish)
            if "food_type" in df.columns:
                ing = (df["food_type"] == "ingredient") & ~df["food_id"].isin(list(SERVING_OVERRIDE_BY_ID))
                df.loc[ing, "_serving_g"] = 100
                df.loc[ing, "_food_category"] = "ingredient_100g"
            sf = df["_serving_g"] / 100.0
            for col in FEATURES:
                if col+"_per100g" not in df.columns:
                    df[col+"_per100g"] = df[col]
                df[col] = df[col+"_per100g"] * sf

            # [FIX — Entry 10] เก็บค่าของ "กับอย่างเดียว" (ไม่รวมข้าว) ไว้ก่อน
            # บวกข้าว ให้ search_food() (ถามแคลอรี่จานเดียว) ใช้ค่าที่ไม่ปนข้าว
            for col in FEATURES:
                df["_dishonly_"+col] = df[col]
            df["_dishonly_serving_g"] = df["_serving_g"]

            is_side_only = df["_food_category"].isin(SIDE_ONLY_CATEGORIES)
            # [FIX — Entry 12] ยกเว้นแถวที่ keyword classifier จัดหมวดผิด
            # (มีข้าว/แป้งรวมอยู่แล้ว หรือเป็นของว่าง/ของหวาน ไม่ใช่กับข้าว)
            # กันไม่ให้บวกข้าวซ้ำซ้อน — เช็คว่าคอลัมน์ food_id มีอยู่ก่อน
            # เพื่อ backward-compat
            if "food_id" in df.columns:
                is_side_only = is_side_only & ~df["food_id"].isin(NO_RICE_ADD_OVERRIDE_IDS)
            df["_includes_rice"] = is_side_only
            rice_sf = RICE_PORTION_G / 100.0
            for col in FEATURES:
                df.loc[is_side_only, col] = (
                    df.loc[is_side_only, col] + RICE_REF_PER100G[col] * rice_sf
                )
            df.loc[is_side_only, "_serving_g"] = (
                df.loc[is_side_only, "_serving_g"] + RICE_PORTION_G
            )

        # [FIX — DEV_LOG Entry 22] คำนวณคอลัมน์ conservative หลังแปลงเป็น
        # ต่อมื้อ+บวกข้าวแล้วเท่านั้น (ทับค่าที่อาจติดมาจาก CSV/DB เก่า)
        add_ckd_conservative_columns(df, mineral_missing)

        # [FIX] เทรน scaler_full/KMeans/ANN เฉพาะเมนูที่กินเป็นมื้อได้จริง
        # (food_type == 'dish') กันไม่ให้วัตถุดิบดิบ (เช่น เกลือ/น้ำมัน/
        # เครื่องปรุง ที่มีค่าพลังงานสุดโต่งทั้งสูงและต่ำ) มาบิดเบือนขอบเขต
        # cluster — ก่อนหน้านี้เทรนบนข้อมูลทั้งหมดรวมวัตถุดิบ ทำให้ cluster
        # "พลังงานต่ำ" ครอบคลุมเมนูถึง ~83% ของทั้งหมด (เทียบกับ ~42% ถ้า
        # เทรนเฉพาะ dish) ทำให้กลไก Disease Override แทบไม่มีผลจริง เพราะ
        # เมนูส่วนใหญ่ถูกจัดเป็น "low-cal" อยู่แล้วไม่ว่า override หรือไม่
        # — self.df ยังคงเป็นข้อมูลเต็ม (dish+ingredient) เหมือนเดิม เพื่อให้
        # search_food() ยังค้นหาวัตถุดิบดิบได้ (เช่น ตอบคำถาม "ไข่ไก่ดิบกี่แคล")
        if "food_type" in df.columns:
            train_mask = (df["food_type"] == "dish")
        else:
            train_mask = pd.Series(True, index=df.index)
        df_train = df[train_mask]

        # scaler_full — fit เฉพาะบน dish subset  [FIX]
        self.scaler_full = StandardScaler()
        X_train_scaled = self.scaler_full.fit_transform(df_train[FEATURES])

        # KMeans — fit เฉพาะ dish subset แล้ว predict cluster ให้ทุกแถว
        # (รวมวัตถุดิบ) ด้วย scaler/kmeans ตัวเดียวกัน เพื่อให้ df['clusters']
        # มีค่าครบทุกแถวเหมือนเดิม ไม่ทำให้โค้ดส่วนอื่นที่อ้างอิง column นี้พัง
        self.kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
        self.kmeans.fit(X_train_scaled)
        X_full_scaled = self.scaler_full.transform(df[FEATURES])
        # [FIX — DEV_LOG Entry 27] เลข cluster ดิบของ KMeans สุ่มตามลำดับ
        # จุดเริ่มต้น สลับได้ทุกครั้งที่ข้อมูลเปลี่ยน → จัดเลขใหม่ตามพลังงาน
        # เฉลี่ยของ centroid ให้ตรงกับรายงาน (ตาราง 4.2) เสมอ
        self.cluster_relabel = relabel_clusters_by_energy(self.kmeans)
        df["clusters"] = pd.Series(self.kmeans.predict(X_full_scaled), index=df.index).map(self.cluster_relabel)

        # ANN (โหลดจาก file หรือ train ใหม่) — เทรนเฉพาะ dish subset เช่นกัน
        #
        # [FIX — DEV_LOG Entry 26] เดิมโหลดไฟล์ ANN เก่าเสมอถ้ามีอยู่ ทั้งที่
        # scaler/KMeans ถูก fit ใหม่ทุกครั้งที่เปิดแอป — พอข้อมูลเปลี่ยน
        # (เพิ่มเมนู/เติมแร่ธาตุ) เลข cluster ของ KMeans สลับ/ขอบเขตเปลี่ยน แต่
        # ANN ยังทายตาม label ชุดเก่า (วัดได้ ANN ตรงกับ KMeans แค่ 6.7%)
        # ตอนนี้: เก็บ fingerprint ของข้อมูลที่ใช้เทรนไว้คู่กับไฟล์โมเดล
        # (<model>.meta.json) ถ้าไม่ตรง → เทรนใหม่อัตโนมัติ และกันอีกชั้นด้วย
        # การเช็คว่า ANN ที่โหลดมาทายตรงกับ label KMeans ปัจจุบัน ≥ 90%
        os.makedirs(os.path.dirname(self.model_save_path) or ".", exist_ok=True)
        y_train = df.loc[train_mask, "clusters"].values
        fingerprint = _training_fingerprint(df_train[FEATURES], y_train)
        meta_path = os.path.splitext(self.model_save_path)[0] + ".meta.json"

        self.ann_final = None
        if os.path.exists(self.model_save_path) and os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("fingerprint") == fingerprint:
                    log.info(f"Loading ANN from {self.model_save_path}")
                    model = tf.keras.models.load_model(self.model_save_path)
                    pred = model.predict(X_train_scaled, verbose=0).argmax(axis=1)
                    agree = float((pred == y_train).mean())
                    if agree >= ANN_MIN_AGREEMENT:
                        self.ann_final = model
                    else:
                        log.warning(f"ANN ที่โหลดมาตรงกับ KMeans แค่ {agree:.1%} → เทรนใหม่")
                else:
                    log.info("ข้อมูลเปลี่ยนจากตอนเทรน ANN ครั้งก่อน → เทรนใหม่")
            except Exception as e:
                log.warning(f"โหลด ANN/meta ไม่สำเร็จ ({e}) → เทรนใหม่")
        elif os.path.exists(self.model_save_path):
            log.info("ไฟล์ ANN เก่าไม่มี meta (ไม่รู้ว่าเทรนจากข้อมูลชุดไหน) → เทรนใหม่")

        if self.ann_final is None:
            log.info("Training ANN (first run ~30s)...")
            self.ann_final = Sequential([
                Dense(64, activation="relu", input_shape=(len(FEATURES),)),
                Dropout(0.2),
                Dense(32, activation="relu"),
                Dense(3, activation="softmax"),
            ])
            self.ann_final.compile(
                optimizer="adam",
                loss="sparse_categorical_crossentropy",
                metrics=["accuracy"],
            )
            self.ann_final.fit(
                X_train_scaled, y_train, epochs=50, batch_size=16,
                # [FIX — DEV_LOG Entry 39] ค่าเริ่มต้น monitor="val_loss" แต่ไม่ได้
                # แบ่ง validation → EarlyStopping ไม่เคยทำงาน (log เตือนทุกครั้ง)
                callbacks=[EarlyStopping(monitor="loss", patience=10, restore_best_weights=True)],
                verbose=0,
            )
            self.ann_final.save(self.model_save_path)
            pred = self.ann_final.predict(X_train_scaled, verbose=0).argmax(axis=1)
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({
                    "fingerprint": fingerprint,
                    "n_train": int(len(y_train)),
                    "train_agreement": round(float((pred == y_train).mean()), 4),
                    "features": FEATURES,
                }, f, ensure_ascii=False, indent=2)
            log.info(f"ANN saved → {self.model_save_path} (+ {meta_path})")

        self.df     = df.reset_index(drop=True)
        self._ready = True
        log.info(f"NCDModel ready — {len(df)} foods")

    async def init_from_db(self):
        """โหลด food data จาก foods table (เรียกตอน app startup)"""
        from db.database import get_all_foods_df
        log.info("Loading foods from DB...")
        df = await get_all_foods_df()
        if df.empty:
            log.warning("foods table ว่าง — ต้อง import CSV ก่อน")
            return
        await asyncio.to_thread(self._prepare_and_train, df)

    # ── public API ────────────────────────────────────────────────

    def compute_user_targets(self, profile: dict) -> dict:
        """profile dict จาก DB → targets dict"""
        diseases = set(profile.get("diseases") or [])
        bmr, tdee, bmi, bmi_cat, base = build_feature_vector(
            profile["age"], profile["gender"],
            profile["weight_kg"], profile["height_cm"],
            profile["activity_level"],
        )
        adj      = adjust_features_by_disease(base, diseases,
                                               profile["weight_kg"],
                                               profile["age"], profile["gender"],
                                               profile.get("height_cm"))
        per_meal = {k: round(v/3, 4) for k, v in adj.items()}
        return {
            "bmr": round(bmr,1), "tdee": round(tdee,1),
            "bmi": bmi, "bmi_category": bmi_cat,
            "daily_limit": adj, "meal_limit": per_meal,
            "diseases": diseases,
        }

    def predict_cluster(self, per_meal_features: dict, diseases: set):
        """คืน (raw_cluster, final_cluster, reason)"""
        user_sc  = self.scaler_full.transform(pd.DataFrame([features_to_list(per_meal_features)], columns=FEATURES))
        raw_c    = int(self.ann_final.predict(user_sc, verbose=0).argmax(axis=1)[0])
        final_c, reason = map_cluster_for_disease(raw_c, diseases, self.df)
        return raw_c, final_c, reason

    def recommend_3_meals(self, profile: dict, meal_history: list,
                          n_suggest: int = 3) -> dict:
        """
        แนะนำ 3 มื้อพร้อม dynamic budget
        meal_history: list ชื่ออาหารที่กินมาใน 3 วัน (จาก DB)
        """
        assert self._ready, "NCDModel ยังไม่พร้อม"
        targets     = self.compute_user_targets(profile)
        diseases    = targets["diseases"]
        daily_limit = targets["daily_limit"]
        per_meal    = targets["meal_limit"]

        raw_c, final_c, reason = self.predict_cluster(per_meal, diseases)
        user_sc = self.scaler_full.transform(pd.DataFrame([features_to_list(per_meal)], columns=FEATURES))

        daily_used   = {col: 0.0 for col in NCOLS}
        chosen_meals = []
        history_now  = list(meal_history)

        for meal_no in range(1, 4):
            meals_left = 4 - meal_no  # รวมมื้อนี้

            # [NEW] Dynamic limit — แบ่ง budget ที่เหลือหารด้วยมื้อที่เหลือ
            meal_lim = compute_meal_limit(daily_limit, daily_used, meals_left)

            cands = self._knn_mmr(final_c, user_sc, meal_lim, history_now, n_suggest, diseases=diseases)
            if cands.empty:
                log.warning(f"มื้อที่ {meal_no}: ไม่พบเมนู")
                continue

            chosen = cands.iloc[0]
            history_now.append(chosen["food_name_th"])
            for col in NCOLS:
                daily_used[col] = daily_used.get(col, 0) + float(chosen.get(col, 0))

            chosen_meals.append({
                "meal_no":          meal_no,
                "meal_label":       ["เช้า","กลางวัน","เย็น"][meal_no-1],
                "food_name_th":     str(chosen.get("food_name_th","")),
                "food_name_en":     str(chosen.get("food_name_en","")),
                "food_id":          int(chosen["food_id"]) if "food_id" in chosen.index and pd.notna(chosen["food_id"]) else None,
                "energy_kcal":      round(float(chosen.get("energy_kcal",0)),1),
                "carb_available_g": round(float(chosen.get("carb_available_g",0)),1),
                "protein_g":        round(float(chosen.get("protein_g",0)),1),
                "fat_g":            round(float(chosen.get("fat_g",0)),1),
                "sodium_mg":        round(float(chosen.get("sodium_mg",0)),1),
                "_serving_g":       int(chosen.get("_serving_g",300)),
                "_includes_rice":   bool(chosen.get("_includes_rice", False)),
                "_portion":         str(chosen.get("_portion", "normal")),  # [Entry 31]
                "meal_limit":       {k: round(meal_lim.get(k,0),1) for k in NCOLS},
            })

        return {
            "meals":        chosen_meals,
            "targets":      targets,
            "cluster_info": {"raw": raw_c, "final": final_c, "reason": reason},
            "daily_used":   {k: round(v,1) for k,v in daily_used.items()},
        }

    def recommend_next_meal(self, profile: dict, meal_history: list,
                            today_used: dict, n_suggest: int = 3,
                            main_meal: bool = True, n_candidates: int | None = None) -> dict:
        """
        แนะนำมื้อถัดไป โดยรับ today_used จาก DB มาด้วย
        ใช้เมื่อ user กินไปบางมื้อแล้ว
        today_used: dict จาก get_today_summary() — key เป็น total_energy_kcal ฯลฯ
        """
        assert self._ready
        targets     = self.compute_user_targets(profile)
        diseases    = targets["diseases"]
        daily_limit = targets["daily_limit"]
        per_meal    = targets["meal_limit"]

        # แปลง DB format → NCOLS format
        used = {
            "energy_kcal":      float(today_used.get("total_energy_kcal") or 0),
            "carb_available_g": float(today_used.get("total_carb_g") or 0),
            "protein_g":        float(today_used.get("total_protein_g") or 0),
            "fat_g":            float(today_used.get("total_fat_g") or 0),
            "sodium_mg":        float(today_used.get("total_sodium_mg") or 0),
            # [FIX — DEV_LOG Entry 36] เดิมไม่หัก K/P ที่กินไปแล้ว — งบต่อมื้อของ
            # ผู้ป่วยไตเลยไม่ลดตามที่กินจริง (food_logs เก็บ phosphorus แล้ว)
            "potassium_mg":     float(today_used.get("total_potassium_mg") or 0),
            "phosphorus_mg":    float(today_used.get("total_phosphorus_mg") or 0),
        }
        meals_eaten = int(today_used.get("meal_count", 0))
        meals_left  = max(3 - meals_eaten, 1)

        # dynamic limit
        meal_lim = compute_meal_limit(daily_limit, used, meals_left)

        raw_c, final_c, reason = self.predict_cluster(per_meal, diseases)
        user_sc = self.scaler_full.transform(pd.DataFrame([features_to_list(per_meal)], columns=FEATURES))

        # [DEV_LOG Entry 44] n_candidates: คืน pool ผู้สมัครทั้งหมดที่ผ่าน
        # hard filter + KNN/MMR + history (เรียงตามอันดับ KNN/MMR) ให้ Bandit
        # เลือกต่อ — ทุกตัวใน pool ผ่านเกณฑ์ความปลอดภัยแล้ว (Disease Override
        # ทำงานก่อน Bandit เสมอ ตามที่ตกลงไว้ใน CLAUDE.md)
        cands = self._knn_mmr(final_c, user_sc, meal_lim, meal_history, n_suggest,
                              diseases=diseases, main_meal=main_meal,
                              n_return=max(n_candidates or 0, n_suggest))
        all_meals = []
        for rank, (_, row) in enumerate(cands.iterrows()):
            all_meals.append({
                "food_name_th":     str(row.get("food_name_th","")),
                "food_name_en":     str(row.get("food_name_en","")),
                "food_id":          int(row["food_id"]) if "food_id" in row.index and pd.notna(row["food_id"]) else None,
                "energy_kcal":      round(float(row.get("energy_kcal",0)),1),
                "carb_available_g": round(float(row.get("carb_available_g",0)),1),
                "protein_g":        round(float(row.get("protein_g",0)),1),
                "fat_g":            round(float(row.get("fat_g",0)),1),
                "sodium_mg":        round(float(row.get("sodium_mg",0)),1),
                "_serving_g":       int(row.get("_serving_g",300)),
                "_includes_rice":   bool(row.get("_includes_rice", False)),
                "_portion":         str(row.get("_portion", "normal")),  # [Entry 31]
                "_food_category":   str(row.get("_food_category", "other")),
                "_cluster":         int(row["clusters"]) if pd.notna(row.get("clusters")) else -1,
                "_knn_rank":        rank,
                "potassium_mg":     round(float(row.get("potassium_mg", 0) or 0), 1),
                "phosphorus_mg":    round(float(row.get("phosphorus_mg", 0) or 0), 1),
                "sugar_risk":       int(row["sugar_risk"]) if "sugar_risk" in row.index and pd.notna(row.get("sugar_risk")) else None,
            })
        meals = all_meals[:n_suggest]

        return {
            "meals":       meals,
            "candidates":  all_meals,
            "meal_limit":  {k: round(meal_lim.get(k,0),1) for k in NCOLS},
            "daily_used":  used,
            "daily_limit": {k: round(daily_limit.get(k,0),1) for k in NCOLS},
            "meals_eaten": meals_eaten,
            "meals_left":  meals_left,
            "cluster_info":{"raw": raw_c, "final": final_c, "reason": reason},
            "targets":     targets,
        }

    def search_food(self, keyword: str, top_n: int = 5) -> list:
        """
        ค้นหาอาหารจากชื่อไทย/อังกฤษ (Feature 3)

        [FIX — Entry 10] ใช้คอลัมน์ _dishonly_* (ค่าก่อนบวกข้าวสวยให้กลุ่ม
        side_only) เสมอ — ฟีเจอร์นี้คือ "ถามแคลอรี่ของจานนี้เท่าไหร่" ผู้ใช้
        ถามถึงจานที่ระบุ ไม่ได้ถามถึง "จานนี้ + ข้าว" เหมือนตอนแนะนำเป็นมื้อ
        อาหาร จึงต้องไม่ปนตัวบวกข้าวเข้ามาในคำตอบนี้ (fallback ไปใช้คอลัมน์
        ปกติถ้าเป็น DB/CSV เก่าที่ยังไม่มีคอลัมน์ _dishonly_*)
        """
        assert self._ready
        # [FIX — DEV_LOG Entry 29] เดิมใช้ str.contains แบบ regex แล้วหยิบแถว
        # แรกตามลำดับในไฟล์: (1) ชื่อที่มี ( ) + ค้นตัวเองไม่เจอ / input ที่มี
        # "(" ทำ error (2) keyword ว่าง match ทุกแถว (3) "หมูกรอบ" ได้ "ข้าวราด
        # ผัดคะน้าหมูกรอบ" ก่อน "หมูกรอบ" — ตอนนี้: ค้นแบบตัวอักษรตรงๆ
        # (regex=False) เทียบชื่อแบบตัดช่องว่าง/จุลภาค ("ไส้กรอกอีสาน" เจอ
        # "ไส้กรอก, อีสาน") และเรียงผล: ตรงเป๊ะ > ขึ้นต้นด้วย > มีอยู่ในชื่อ
        # (ไทยก่อนอังกฤษ) แล้วชื่อสั้นก่อน
        kw = _norm_name(keyword)
        if not kw:
            return []
        # [DEV_LOG Entry 58] ชื่อเรียกอื่นที่กำหนดไว้ (food_aliases.csv) เช่น ก๋วยเตี๋ยวเรือ = ก๋วยเตี๋ยวน้ำตก
        # → ได้จานเดียวกับที่ CNN ใช้ (cnn_label_food_mapping.csv) ไม่ว่าจะพิมพ์หรือส่งรูป
        alias_fid = _food_aliases().get(kw)
        if alias_fid is not None and (self.df["food_id"] == alias_fid).any():
            d = self._row_to_food_dict(self.df[self.df["food_id"] == alias_fid].iloc[0])
            d["_match"] = "full"
            rest = [x for x in self._search_by_name(keyword, kw, top_n) if x.get("food_id") != alias_fid]
            return ([d] + rest)[:top_n]
        return self._search_by_name(keyword, kw, top_n)

    def _search_by_name(self, keyword: str, kw: str, top_n: int) -> list:
        th = self.df["food_name_th"].map(_norm_name)
        en = self.df["food_name_en"].map(_norm_name)
        rank = pd.Series(np.nan, index=self.df.index)
        rank[en.str.contains(kw, regex=False, na=False)] = 4
        rank[th.str.contains(kw, regex=False, na=False)] = 2
        rank[th.str.startswith(kw, na=False)] = 1
        rank[(th == kw) | (en == kw)] = 0
        rank[self.df["food_name_th"].astype(str).str.strip() == str(keyword).strip()] = -1
        # [FIX — DEV_LOG Entry 55] "ก๋วยเตี๋ยวเรือ" ได้ "ขนมรูปน่องไก่ รสก๋วยเตี๋ยวเรือ" — ชื่อที่มี
        # คำค้นเป็นแค่ "รส..." (ขนม/บะหมี่กึ่งฯ) ให้อยู่หลังจานจริง
        flavor = th.str.contains("รส" + kw, regex=False, na=False) & (rank == 2)
        rank[flavor] = 3.8
        hits = rank.dropna()
        if hits.empty and len(kw) >= 5:
            # [FIX — DEV_LOG Entry 44] ชื่อที่ผู้ใช้พิมพ์ติดกันแต่ในฐานข้อมูลแยก
            # หรือสลับคำ (ทดสอบ eval/food_search: "ลาบหมู" vs "ลาบคั่ว, หมู",
            # "น้ำตกหมู" vs "หมูน้ำตก") — ลองแบ่ง query เป็น 2 ส่วน (ส่วนละ ≥2 ตัว)
            # แล้วหาชื่อที่มีทั้ง 2 ส่วน; ส่วนแรกยาวกว่าได้ก่อน (เป็นคำหลักของจาน)
            for i in range(len(kw) - 3, 2, -1):   # [Entry 67] แต่ละส่วน ≥3 ตัว ("ชา"+"ไทย" เคยได้ "โยเกิร์ต ไทยเดนมาร์ค ธรรมชาติ")
                a, b = kw[:i], kw[i:]
                m2 = th.str.contains(a, regex=False, na=False) & th.str.contains(b, regex=False, na=False)
                if m2.any():
                    rank[m2] = 3
                    # [Entry 75] สลับคำล้วนๆ ("ตับไก่" = "ไก่, ตับ") → ถือว่าตรงตัว ไม่ใช่เมนูใกล้เคียง
                    rank[m2 & (th.str.len() == len(kw))] = 0.5
                    break
            hits = rank.dropna()
        if (hits.empty or hits.min() >= 3.8) and len(kw) >= 6:
            # [FIX — DEV_LOG Entry 55] eval_meal_parse: LLM ส่งชื่อละเอียดกว่าที่มีในฐาน
            # ("กะเพราไก่ไข่ดาว", "ผัดซีอิ๊วหมู", "เกาเหลาเลือดหมู", "ไก่ย่างส้มตำ") แล้วหาไม่เจอ
            # → ตัดท้ายทีละตัวจนเจอชื่อที่ "ขึ้นต้นด้วย/มี" ส่วนหน้า (≥4 ตัวอักษร) — ผู้ใช้ยังเห็น
            # ชื่อจานที่จะบันทึกและกดยืนยัน/ยกเลิกเองก่อนเสมอ
            for i in range(len(kw) - 1, 3, -1):
                pre = kw[:i]
                m3 = (th.str.contains(pre, regex=False, na=False)
                      & ~th.str.contains("รส" + pre, regex=False, na=False))
                if m3.any():
                    rank[m3] = 3.5
                    rank[m3 & th.str.startswith(pre, na=False)] = 3.4
                    break
            hits = rank.dropna()
        if hits.empty:
            return []
        # [FIX — DEV_LOG Entry 38] ลำดับเท่ากัน → จาน (dish) ก่อนวัตถุดิบ
        # (ทดสอบจริง: "ก๋วยจั๊บญวน" ได้ "ก๋วยจั๊บญวน, เส้น, ต้มสุก" ซึ่งเป็นแค่เส้น)
        is_ing = (self.df.loc[hits.index, "food_type"].eq("ingredient").astype(int)
                  if "food_type" in self.df.columns else pd.Series(0, index=hits.index))
        order = (pd.DataFrame({"rank": hits, "ing": is_ing, "len": th[hits.index].str.len()})
                 .sort_values(["rank", "ing", "len"], kind="stable").index[:top_n])
        out = []
        for i in order:
            d = self._row_to_food_dict(self.df.loc[i])
            # [Entry 55] partial = ไม่เจอชื่อที่มีคำค้นครบ ใช้จานที่ใกล้เคียงแทน (แอปจะบอกผู้ใช้)
            d["_match"] = "partial" if hits[i] >= 3 else "full"
            out.append(d)
        return out

    def search_meal(self, keyword: str) -> list:
        """[DEV_LOG Entry 76] ค้นสำหรับ "บันทึกการกิน" — ถ้าหาจานตรงตัวไม่เจอและชื่อขึ้นต้นด้วย
        ข้าวราด/ราดข้าว/ข้าว ลองหา "กับ" ส่วนที่เหลือแล้วบวกข้าวสวย (แบบเดียวกับการ์ดแนะนำ)
        ทดสอบจริง: "ราดข้าวผัดพริกแกงไก่" → LLM ส่ง "ข้าวผัดพริกแกงไก่" → ได้ "ข้าวผัดหมู" (ผู้ใช้กดยืนยันไปแล้ว)
        เลือกผลที่ชื่อใกล้คำค้นกว่า (สัดส่วนตัวอักษรที่ตรงกัน)"""
        res = self.search_food(keyword, 1)
        if res and res[0].get("_match") == "full":
            return res
        kw = _norm_name(keyword)

        def sim(a, b):
            a, b = set(_norm_name(a)), set(_norm_name(b))
            return len(a & b) / max(1, len(a | b))

        best, best_s = (res[0] if res else None), (sim(kw, res[0]["food_name_th"]) if res else -1)
        for pre in ("ข้าวราด", "ราดข้าว", "ข้าว"):
            tail = kw[len(pre):]
            if not kw.startswith(pre) or len(tail) < 3:
                continue
            side = self.search_food(tail, 1)
            if not side or side[0].get("food_type") != "dish" or not side[0].get("food_id"):
                continue
            s = sim(tail, side[0]["food_name_th"])
            if s > best_s:
                d = self.get_food_by_id(side[0]["food_id"], with_rice=True) or side[0]
                d["_match"] = side[0].get("_match", "partial")
                best, best_s = d, s
            break
        return [best] if best else []

    def get_food_by_id(self, food_id: int, with_rice: bool = False):
        """
        [FIX — DEV_LOG Entry 29] ดึงอาหารด้วย food_id ตรงๆ (ใช้กับปุ่ม "กิน
        มื้อนี้" ที่รู้ food_id อยู่แล้ว) — with_rice=True คืนค่าต่อมื้อแบบ
        เดียวกับที่โชว์บนการ์ดแนะนำเมนู (รวมข้าวสวยถ้าเป็นกับข้าว) ให้ค่าที่
        บันทึกตรงกับที่ผู้ใช้เห็น คืน None ถ้าไม่พบ
        """
        assert self._ready
        m = self.df["food_id"] == food_id
        if not m.any():
            return None
        return self._row_to_food_dict(self.df[m].iloc[0], with_rice=with_rice)

    def _row_to_food_dict(self, row, with_rice: bool = False) -> dict:
        def _v(row, col):
            if with_rice:
                return row.get(col, 0)
            dcol = "_dishonly_" + col
            return row[dcol] if dcol in row.index and pd.notna(row[dcol]) else row.get(col, 0)

        def _ckd(row, col):
            # ถ้าคอลัมน์ conservative มีอยู่ ใช้ตัวนั้นเท่านั้น (NaN = ไม่มีข้อมูล
            # จริง → None ให้ fail-safe ทำงาน ห้าม fallback ไปค่าอื่น)
            cands = ((col + CKD_MINERAL_CONSERVATIVE_SUFFIX,) if with_rice else
                     ("_dishonly_" + col + CKD_MINERAL_CONSERVATIVE_SUFFIX,
                      col + CKD_MINERAL_CONSERVATIVE_SUFFIX))
            for c in cands:
                if c in row.index:
                    v = row[c]
                    return round(float(v), 1) if pd.notna(v) else None
            return None

        if with_rice:
            serving = int(row.get("_serving_g", 300))
        else:
            serving = (int(row["_dishonly_serving_g"]) if "_dishonly_serving_g" in row.index
                       and pd.notna(row["_dishonly_serving_g"]) else int(row.get("_serving_g", 300)))
        return {
                "food_name_th":     str(row.get("food_name_th","")),
                "food_name_en":     str(row.get("food_name_en","")),
                "food_id":          int(row["food_id"]) if "food_id" in row.index and pd.notna(row.get("food_id")) else None,
                "energy_kcal":      round(float(_v(row,"energy_kcal")),1),
                "carb_available_g": round(float(_v(row,"carb_available_g")),1),
                "protein_g":        round(float(_v(row,"protein_g")),1),
                "fat_g":            round(float(_v(row,"fat_g")),1),
                "sodium_mg":        round(float(_v(row,"sodium_mg")),1),
                "potassium_mg":     round(float(_v(row,"potassium_mg")),1),
                # [FIX — DEV_LOG Entry 18] เพิ่ม phosphorus_mg/sugar_risk ให้
                # search_food() คืนมาด้วย — evaluate_food_limits() ต้องใช้
                # phosphorus_mg เช็คเกณฑ์ CKD และ sugar_risk เป็นข้อมูล
                # ประกอบสำหรับเบาหวาน sugar_risk ไม่ใช่ FEATURES ที่ผ่านการ
                # บวกข้าว/normalize ต่อ serving เหมือนตัวอื่น จึงอ่านจาก
                # คอลัมน์ปกติตรงๆ ไม่ต้องผ่าน _v()
                "phosphorus_mg":    round(float(_v(row,"phosphorus_mg")),1),
                # [FIX — DEV_LOG Entry 20] ส่งค่า conservative (ประมาณ+margin)
                # ไปด้วย ให้ evaluate_food_limits() เช็คเพดาน CKD ด้วยเกณฑ์
                # เดียวกับ _hard_filter เป๊ะๆ — None ถ้าไม่มีคอลัมน์นี้ (DB/CSV
                # เก่า) หรือแถวนั้นไม่มีข้อมูลเลย (ไม่ผ่าน regression ได้)
                # [FIX — Entry 22] ใช้ค่า _dishonly_ (ต่อมื้อ ไม่รวมข้าว) ให้
                # สอดคล้องกับค่าอื่นใน search_food — None = ไม่มีข้อมูลจริง
                "potassium_mg_ckd_conservative": _ckd(row, "potassium_mg"),
                "phosphorus_mg_ckd_conservative": _ckd(row, "phosphorus_mg"),
                # [FIX — Entry 26] โซเดียมไม่มีข้อมูลจริง (ค่าที่เห็นคือ median)
                "sodium_missing": bool(row.get("_sodium_missing", False)),
                "sugar_risk":       int(row["sugar_risk"]) if "sugar_risk" in row.index and pd.notna(row.get("sugar_risk")) else None,
                "free_sugar":       bool(row["_free_sugar"]) if "_free_sugar" in row.index else None,
                "_serving_g":       serving,
                "_includes_rice":   bool(with_rice and row.get("_includes_rice", False)),
                "food_type":        str(row.get("food_type", "dish")),  # [Entry 38]
            }

    def budget_summary(self, daily_limit: dict, today_used: dict) -> dict:
        """
        สรุป budget สำหรับส่งให้ LINE  (Feature สรุปวันนี้)
        รองรับทั้ง DB format (total_energy_kcal) และ NCOLS format (energy_kcal)
        """
        used = {
            "energy_kcal":      float(today_used.get("energy_kcal") or today_used.get("total_energy_kcal",0)),
            "carb_available_g": float(today_used.get("carb_available_g") or today_used.get("total_carb_g",0)),
            "protein_g":        float(today_used.get("protein_g") or today_used.get("total_protein_g",0)),
            "fat_g":            float(today_used.get("fat_g") or today_used.get("total_fat_g",0)),
            "sodium_mg":        float(today_used.get("sodium_mg") or today_used.get("total_sodium_mg",0)),
            "potassium_mg":     float(today_used.get("potassium_mg") or today_used.get("total_potassium_mg",0) or 0),
            "phosphorus_mg":    float(today_used.get("phosphorus_mg") or today_used.get("total_phosphorus_mg",0) or 0),
        }
        out = {}
        for col in NCOLS:
            lim = daily_limit.get(col, 1)
            u   = used.get(col, 0)
            out[col] = {
                "used":      round(u, 1),
                "limit":     round(lim, 1),
                "remaining": round(lim - u, 1),
                "pct":       round(u / lim * 100, 1) if lim else 0,
                "over":      (lim - u) < 0,
                "unit":      UNITS.get(col, ""),
            }
        return out

    # ── private ───────────────────────────────────────────────────

    def _hard_filter(self, df_in, meal_lim, tol=1.10, energy_lo=0.70, diseases=None):
        """
        กรองเมนูที่เกิน budget ต่อมื้อ (upper bound, เหมือนเดิม) สำหรับ
        energy/carb/fat/sodium — [FIX] เพิ่มขอบล่างเฉพาะ energy_kcal
        (ต้อง >= energy_lo ของ budget ต่อมื้อ) กันไม่ให้ระบบเลือกจานที่
        แคลน้อยเกินไปจนกิน 3 มื้อรวมกันไม่ถึงเป้าพลังงานต่อวัน (พบจริงจาก
        การทดสอบ: กิน 3 มื้อครบ ได้แค่ 58% ของเป้า เพราะจานที่แนะนำแคล
        ต่ำกว่า budget ต่อมื้อมาก) ใช้ขอบล่างเฉพาะ energy เท่านั้น ไม่ใช้กับ
        carb/fat/sodium เพราะ 3 ตัวนั้นคือค่าที่ควร "ไม่เกิน" ไม่ใช่ค่าที่
        ต้อง "ให้ถึง" เหมือน energy

        [FIX] เพิ่มกรอง food_type == 'dish' เมื่อคอลัมน์นี้มีอยู่ในข้อมูล —
        กันไม่ให้ระบบแนะนำวัตถุดิบดิบ (เช่น "ข้าวกล้อง, งอก, ดิบ",
        เครื่องปรุง, ผลไม้เดี่ยวๆ) เป็น "มื้ออาหาร" ทั้งที่กินแบบนั้นตรงๆ
        ไม่ได้จริง — เช็คว่าคอลัมน์มีอยู่ก่อนเพื่อ backward-compat กับ DB/CSV
        เก่าที่ยังไม่มี food_type (ดู DEV_LOG Entry 8)

        [FIX — DEV_LOG Entry 15] เพิ่ม hard ceiling สำหรับ potassium_mg และ
        phosphorus_mg เฉพาะเมื่อผู้ใช้เป็น CKD เท่านั้น — ห้ามใช้เป็น ceiling
        แบบไม่มีเงื่อนไข เพราะ potassium สำหรับผู้ป่วยความดันสูง (ไม่มี CKD)
        คือ "floor" (ต้องกินให้ถึง ตาม DASH diet) ไม่ใช่ ceiling — ถ้าบังคับ
        ceiling ทั่วไปจะขัดกับ logic เดิมใน adjust_features_by_disease ทันที

        [FIX — DEV_LOG Entry 16] เพิ่ม absolute cap คาร์บต่อมื้อ (≤
        DIABETES_MAX_CARB_G_PER_MEAL) เฉพาะเบาหวาน — ทำงานเสริมจาก carb
        ceiling แบบ dynamic (meal_lim["carb_available_g"]) ที่มีอยู่แล้ว
        ด้านบน ไม่ได้แทนที่กัน ใช้ min ของสองค่าจริง (mask AND กันเอง)
        """
        diseases = diseases or set()
        mask = pd.Series(True, index=df_in.index)
        if "food_type" in df_in.columns:
            mask &= (df_in["food_type"] == "dish")
        for col in ["energy_kcal","carb_available_g","fat_g","sodium_mg"]:
            if col in df_in.columns and meal_lim.get(col, 0) > 0:
                mask &= ~(df_in[col] > meal_lim[col]*tol).fillna(False)
        if "ckd" in diseases:
            for col in ["potassium_mg", "phosphorus_mg"]:
                if col in df_in.columns and meal_lim.get(col, 0) > 0:
                    # [FIX — DEV_LOG Entry 20] ใช้คอลัมน์ conservative (ค่า
                    # ประมาณ + margin) แทนค่าตรงๆ ถ้ามี เพื่อกันจานที่ประมาณ
                    # ค่าต่ำกว่าความจริงหลุดผ่านเพดาน — fallback เป็นคอลัมน์
                    # ปกติถ้าเป็น DB/CSV เก่าที่ยังไม่มีคอลัมน์นี้
                    ckd_col = col + CKD_MINERAL_CONSERVATIVE_SUFFIX
                    check_col = ckd_col if ckd_col in df_in.columns else col
                    # fail-safe: ไม่มีข้อมูลเลย (NaN) → ถือว่า "เกินเพดาน"
                    # (กรองออก) แทนการปล่อยผ่านแบบเดิม เพราะไม่สามารถยืนยัน
                    # ความปลอดภัยให้ผู้ป่วย CKD ได้
                    mask &= (
                        df_in[check_col].notna()
                        & ~(df_in[check_col] > meal_lim[col]*tol)
                    )
        if "ckd" in diseases and {"potassium_estimated", "food_name_th"} <= set(df_in.columns):
            # [FIX — DEV_LOG Entry 35] ค่าโพแทสเซียมที่มาจาก regression (R²≈0.06)
            # ไม่รู้จัก "ชนิด" อาหาร — ทดสอบเจอ "กล้วย, อบ" ได้ K ประมาณ 205mg/100g
            # (จริงๆ กล้วยอบแห้ง ~1,000+ mg) แล้วถูกแนะนำให้ผู้ป่วยไต ถ้า K เป็น
            # ค่าประมาณและชื่ออยู่ในกลุ่มอาหารโพแทสเซียมสูงที่รู้กันทั่วไป
            # (ตรงกับเอกสาร ckd_002 ใน RAG) ให้ถือว่าเกินเพดานไว้ก่อน
            est = df_in["potassium_estimated"].astype(str).str.lower().isin(["true", "1"])
            name = df_in["food_name_th"].astype(str)
            high_k = (name.str.contains(CKD_HIGH_K_NAME_PATTERN, regex=True, na=False)
                      & ~name.str.contains(CKD_HIGH_K_EXCEPT_PATTERN, regex=True, na=False))
            mask &= ~(est & high_k)
        if "ckd" in diseases and "protein_g" in df_in.columns and meal_lim.get("protein_g", 0) > 0:
            mask &= ~(df_in["protein_g"] > meal_lim["protein_g"] * CKD_PROTEIN_MEAL_TOL).fillna(False)
        if "heart" in diseases and "food_name_th" in df_in.columns:
            name = df_in["food_name_th"].astype(str)
            mask &= ~(name.str.contains(HEART_HIGH_SATFAT_NAME_PATTERN, regex=True, na=False)
                      & ~name.str.contains(HEART_SATFAT_EXCEPT_PATTERN, regex=True, na=False))
        if "diabetes" in diseases and "carb_available_g" in df_in.columns:
            mask &= ~(df_in["carb_available_g"] > DIABETES_MAX_CARB_G_PER_MEAL*tol).fillna(False)
        if "diabetes" in diseases and "_free_sugar" in df_in.columns:
            mask &= ~df_in["_free_sugar"].fillna(False).astype(bool)
        elif "diabetes" in diseases and "sugar_risk" in df_in.columns:
            mask &= ~(df_in["sugar_risk"] >= DIABETES_SUGAR_RISK_HARD_LIMIT).fillna(False)
        # [FIX — DEV_LOG Entry 26] fail-safe โซเดียม: โรคที่ต้องคุมโซเดียมเข้ม
        # ไม่แนะนำจานที่ไม่มีข้อมูลโซเดียมจริง (เดิมถูกเติม median แล้วผ่าน)
        if diseases & SODIUM_STRICT_DISEASES and "_sodium_missing" in df_in.columns:
            mask &= ~df_in["_sodium_missing"].fillna(False).astype(bool)
        if "energy_kcal" in df_in.columns and meal_lim.get("energy_kcal", 0) > 0:
            mask &= (df_in["energy_kcal"] >= meal_lim["energy_kcal"]*energy_lo).fillna(False)
        return df_in[mask].copy().reset_index(drop=True)

    def evaluate_food_limits(self, food: dict, diseases: set, meal_lim: dict,
                              tol: float = 1.10) -> dict:
        """
        [FIX — DEV_LOG Entry 18] เช็คจานเดียว (ไม่ใช่กรองทั้ง pool แบบ
        _hard_filter) เทียบกับเกณฑ์ชุดเดียวกันเป๊ะๆ ที่ _hard_filter ใช้
        กรองตอน "แนะนำเมนู" — สร้างไว้ให้ตอนผู้ใช้ถามชื่อจานตรงๆ
        (ask_calorie/"กินได้ไหม") ใช้เช็คได้ ไม่ต้องเดาเอง กันปัญหาคำตอบ
        ขัดแย้งกันเองระหว่าง 2 ทาง (แนะนำเมนูกรองออกไปแล้ว แต่ถ้าถามตรงๆ
        กลับตอบว่ากินได้ เพราะ LLM ไม่มีเกณฑ์ตัวเลขอ้างอิง)

        ไม่ใช้ energy floor (`energy_lo`) ตรงนี้ เพราะนั่นคือกันไม่ให้ระบบ
        "แนะนำ" จานแคลน้อยเกินไป ไม่ใช่ความเสี่ยงด้านสุขภาพของจานที่ถามถึง
        ตรงๆ (จานแคลน้อยไม่ใช่อันตราย แค่ไม่พอเป้าหมายพลังงาน)

        return: {"exceeds": [ {nutrient, value, limit, unit, note?} ... ],
                 "ok": bool}
        """
        diseases = diseases or set()
        exceeds = []

        def _check(col, unit, limit, note=None):
            val = food.get(col)
            if val is None or limit is None or limit <= 0:
                return
            if val > limit * tol:
                item = {"nutrient": col, "value": round(float(val), 1),
                        "limit": round(float(limit), 1), "unit": unit}
                if note:
                    item["note"] = note
                exceeds.append(item)

        _check("energy_kcal", "kcal", meal_lim.get("energy_kcal"))
        _check("carb_available_g", "g", meal_lim.get("carb_available_g"))
        _check("fat_g", "g", meal_lim.get("fat_g"))
        # [FIX — DEV_LOG Entry 26] fail-safe โซเดียม ให้ตรงกับ _hard_filter
        if food.get("sodium_missing") and diseases & SODIUM_STRICT_DISEASES:
            exceeds.append({"nutrient": "sodium_mg", "value": None,
                            "limit": round(float(meal_lim.get("sodium_mg", 0)), 1), "unit": "mg",
                            "note": "ไม่มีข้อมูลโซเดียม — เพื่อความปลอดภัยของโรคที่ต้องคุมเกลือ ถือว่าเสี่ยงเกินเพดาน"})
        elif not food.get("sodium_missing"):
            _check("sodium_mg", "mg", meal_lim.get("sodium_mg"))

        if "ckd" in diseases:
            # [FIX — DEV_LOG Entry 22] เดิม (Entry 20/21) คำนวณ k_val/p_val แต่
            # ตอนเช็คจริงกลับเรียก _check() ที่อ่านค่าดิบ ไม่ได้ใช้ค่า
            # conservative เลย และถ้า conservative เป็น None ก็ fallback ไป
            # ค่าดิบ (ซึ่งถูกเติม median ไว้แล้ว) ทำให้ fail-safe ไม่เคยทำงาน
            # — ตอนนี้: ถ้า dict มี key conservative (search_food ใส่มาเสมอ)
            # ใช้ค่านั้นเท่านั้น None = ไม่มีข้อมูลจริง → ถือว่าเกิน;
            # ไม่มี key เลย (caller เก่า) ค่อย fallback เป็นค่าดิบ
            for col, name_th in (("potassium_mg", "โพแทสเซียม"),
                                 ("phosphorus_mg", "ฟอสฟอรัส")):
                limit = meal_lim.get(col)
                if limit is None or limit <= 0:
                    continue
                ckey = col + CKD_MINERAL_CONSERVATIVE_SUFFIX
                val = food.get(ckey) if ckey in food else food.get(col)
                if val is None:
                    exceeds.append({"nutrient": col, "value": None,
                                    "limit": round(float(limit), 1), "unit": "mg",
                                    "note": f"ไม่มีข้อมูล{name_th} — เพื่อความปลอดภัยของผู้ป่วย CKD ถือว่าเสี่ยงเกินเพดาน"})
                elif val > limit * tol:
                    exceeds.append({"nutrient": col, "value": round(float(val), 1),
                                    "limit": round(float(limit), 1), "unit": "mg",
                                    "note": f"เพดาน{name_th}สำหรับ CKD (รวมค่าเผื่อความคลาดเคลื่อนถ้าเป็นค่าประมาณ)"})

        if "ckd" in diseases and meal_lim.get("protein_g"):
            if (food.get("protein_g") or 0) > meal_lim["protein_g"] * CKD_PROTEIN_MEAL_TOL:
                exceeds.append({"nutrient": "protein_g", "value": round(float(food["protein_g"]), 1),
                                "limit": round(float(meal_lim["protein_g"]), 1), "unit": "g",
                                "note": f"ผู้ป่วยไตควรจำกัดโปรตีน ~{CKD_PROTEIN_G_PER_KG} g/กก./วัน"})
        if "heart" in diseases:
            import re as _re2
            nm = str(food.get("food_name_th", ""))
            if _re2.search(HEART_HIGH_SATFAT_NAME_PATTERN, nm) and not _re2.search(HEART_SATFAT_EXCEPT_PATTERN, nm):
                exceeds.append({"nutrient": "saturated_fat", "value": None, "limit": None, "unit": "",
                                "note": "เมนูไขมันสูง (กะทิ/มันหมู/หนัง/เนย/ของทอด) ควรจำกัดสำหรับโรคหัวใจ"})
        if "diabetes" in diseases:
            _check("carb_available_g", "g", DIABETES_MAX_CARB_G_PER_MEAL,
                   note="เพดานคาร์บต่อมื้อสำหรับเบาหวาน")
            # [FIX — DEV_LOG Entry 20] sugar_risk=5 เป็น hard limit แล้ว (เดิม
            # เป็นแค่ advisory) ให้ตรงกับ _hard_filter
            sr = food.get("sugar_risk")
            fs = food.get("free_sugar")
            if fs is True:
                exceeds.append({"nutrient": "sugar_risk", "value": sr,
                                 "limit": DIABETES_SUGAR_RISK_HARD_LIMIT - 1, "unit": "level",
                                 "note": "เป็นของหวาน/เครื่องดื่มหวาน (น้ำตาลอิสระสูง) ไม่เหมาะกับผู้ป่วยเบาหวาน"})
            elif fs is None and sr is not None and sr >= DIABETES_SUGAR_RISK_HARD_LIMIT:
                exceeds.append({"nutrient": "sugar_risk", "value": sr,
                                 "limit": DIABETES_SUGAR_RISK_HARD_LIMIT - 1, "unit": "level",
                                 "note": "ระดับความเสี่ยงน้ำตาลสูงสุด ไม่เหมาะกับผู้ป่วยเบาหวาน"})

        result = {"exceeds": exceeds, "ok": len(exceeds) == 0}

        # sugar_risk แนบไปให้ LLM ใช้พูดประกอบเสมอ (แม้ผ่านเกณฑ์ hard limit
        # ด้านบน) เฉพาะกรณีเป็นเบาหวาน
        if "diabetes" in diseases and food.get("sugar_risk") is not None:
            result["sugar_risk"] = int(food["sugar_risk"])

        return result

    def _portion_filter(self, meal_lim, energy_lo=0.70, diseases=None):
        """
        [FIX — DEV_LOG Entry 31] ให้ระบบเลือกขนาดจานได้ (เล็ก ×0.75 / ปกติ /
        ใหญ่ ×1.35 — ตัวคูณเดียวกับ PORTION_MUL ใน db/database.py ที่ใช้ตอน
        บันทึกการกิน) เดิมแนะนำได้แค่ปริมาณตายตัว จานต้องมีพลังงาน 70-110%
        ของงบต่อมื้อพอดีถึงจะผ่าน (คนทั่วไปผ่านแค่ ~52 จาก 736)

        วิธี: ทำสำเนาค่าโภชนาการ 3 ขนาด → กรองทุกขนาดด้วย _hard_filter ชุด
        เดิม (เพดานทุกตัวเช็คกับค่าหลังคูณ ปลอดภัยเท่าเดิม) → แต่ละจานเก็บ
        ขนาดที่ผ่านและพลังงานใกล้ 90% ของงบมื้อมากที่สุด (ถ้าเท่ากันเลือก
        ขนาดปกติก่อน) — คอลัมน์ `_portion` บอกขนาดที่เลือก
        """
        if not ENABLE_PORTION_SCALING:
            out = self._hard_filter(self.df, meal_lim, energy_lo=energy_lo, diseases=diseases)
            out["_portion"] = "normal"
            return out
        base = self.df[self.df["food_type"] == "dish"] if "food_type" in self.df.columns else self.df
        scale_cols = [c for c in PORTION_SCALE_COLS if c in base.columns]
        parts = []
        for name, mul in PORTION_MULTIPLIERS.items():
            p = base.copy()
            p[scale_cols] = p[scale_cols] * mul
            p["_portion"] = name
            p["_portion_pref"] = 0 if name == "normal" else 1
            parts.append(p)
        allp = pd.concat(parts, ignore_index=True)
        ok = self._hard_filter(allp, meal_lim, energy_lo=energy_lo, diseases=diseases)
        if ok.empty:
            return ok
        target = meal_lim.get("energy_kcal", 0) * 0.9
        ok["_gap"] = (ok["energy_kcal"] - target).abs()
        ok = (ok.sort_values(["_gap", "_portion_pref"])
                .drop_duplicates("food_id", keep="first")
                .drop(columns=["_gap", "_portion_pref"]))
        return ok.reset_index(drop=True)

    def _knn_mmr(self, pred_cluster, user_sc, meal_lim, history,
                 n_suggest=3, top_k=20, lmbda=0.6, hist_win=9, diseases=None,
                 main_meal=True, n_return=None):
        diseases = diseases or set()
        def _pool(lo=0.70, allow_snacks=not main_meal):
            p = self._portion_filter(meal_lim, energy_lo=lo, diseases=diseases)
            # [DEV_LOG Entry 35] มื้อหลักไม่แนะนำขนม/ของว่าง (ทดสอบจริง: ผู้ป่วยไต
            # ได้ "กาละแม", "มันเทศชุบแป้งทอด", "ปาท่องโก๋" เป็นมื้อเช้า เพราะ
            # จานคาวตกเพดานโซเดียม/K/P หมด) — ยังแนะนำได้ตอนเป็น "ของว่าง"
            if not allow_snacks and not p.empty:
                snack = p.get("_food_category", pd.Series("", index=p.index)).eq("dessert_snack")
                snack |= p["food_name_th"].astype(str).str.contains(SNACK_NAME_PATTERN, regex=True, na=False)
                p = p[~snack]
            return p

        df_f = _pool()
        if len(df_f) < n_suggest:
            # [FIX] budget ต่อมื้อต่ำมาก (เช่นมื้อสุดท้ายที่เหลือ budget น้อย
            # เพราะมื้อก่อนหน้ากินไปเยอะแล้ว) จนไม่มีจานไหนผ่านขอบล่างเลย
            # ผ่อนขอบล่างลงเรื่อยๆ แทนที่จะคืนค่าว่างไปเลย
            # [FIX — DEV_LOG Entry 35] เดิมผ่อนเฉพาะตอนว่างเปล่า — ทดสอบจริง
            # ผู้ใช้ความดัน+ไต ได้การ์ดแค่ 1 ตัวเลือก ตอนนี้ผ่อนจนได้ครบ n_suggest
            # (ผ่อนเฉพาะขอบล่างพลังงาน เพดานความปลอดภัยทุกตัวคงเดิม)
            for relaxed_lo in (0.5, 0.3, 0.0):
                df_r = _pool(relaxed_lo)
                if len(df_r) > len(df_f):
                    df_f = df_r
                if len(df_f) >= n_suggest:
                    break
            if len(df_f) < n_suggest and main_meal:
                # จานคาวที่ผ่านเกณฑ์ไม่พอจริงๆ (เช่นผู้ป่วยหลายโรค) → ยอมให้มี
                # ของว่างปนมาเติมให้ครบ ดีกว่าให้ตัวเลือกไม่ครบ
                df_r = _pool(0.0, allow_snacks=True)
                if len(df_r) > len(df_f):
                    df_f = df_r
        mask  = df_f["clusters"] == pred_cluster
        # ใช้เฉพาะ cluster ที่ทำนายได้ถ้ามีจานพอให้เลือก ไม่งั้นใช้ทั้ง pool ที่ผ่าน
        # hard filter (ยังปลอดภัยตามเพดานเดิม แค่ไม่จำกัด cluster)
        # [FIX — DEV_LOG Entry 53] นับเฉพาะจานที่ "ยังไม่เพิ่งโชว์/กิน" — eval_diversity เจอ
        # 14/72 โปรไฟล์ที่ cluster มีแค่ 3-8 จาน กด "แนะนำใหม่" 2-3 รอบแล้วเจอจานซ้ำ ทั้งที่
        # pool ปลอดภัยทั้งหมดยังมีจานที่ไม่เคยเห็นอีกเยอะ
        recent_names = set(history[-hist_win:])
        fresh = mask & ~df_f["food_name_th"].isin(recent_names)
        foods = df_f[mask].copy() if fresh.sum() >= n_suggest else df_f.copy()
        if foods.empty: return pd.DataFrame()

        # [FIX v3] ใช้ scaler_full เสมอ
        fvecs = self.scaler_full.transform(foods[FEATURES])
        k     = min(top_k, len(foods))
        nn    = NearestNeighbors(n_neighbors=k, metric="euclidean")
        nn.fit(fvecs)
        dist, ind = nn.kneighbors(user_sc)
        cands = foods.iloc[ind[0]].copy()
        cands["_dist"] = dist[0]
        cands["_fvec"] = list(fvecs[ind[0]])
        cands = cands.reset_index(drop=True)

        # MMR rerank
        uv  = user_sc[0]
        fv  = np.array(cands["_fvec"].tolist())
        sel, rem = [], list(range(len(cands)))
        while len(sel) < top_k and rem:
            scores = [lmbda*(-np.linalg.norm(fv[i]-uv))
                      -(1-lmbda)*max((-np.linalg.norm(fv[i]-fv[j]) for j in sel), default=0)
                      for i in rem]
            best = rem[int(np.argmax(scores))]
            sel.append(best); rem.remove(best)
        mmr = cands.iloc[sel].reset_index(drop=True)

        # History filter
        recent   = set(history[-hist_win:])
        filtered = mmr[~mmr["food_name_th"].isin(recent)].reset_index(drop=True)
        if len(filtered) < n_suggest:
            used = set(filtered["food_name_th"])
            fb   = mmr[~mmr["food_name_th"].isin(used)].head(n_suggest-len(filtered))
            filtered = pd.concat([filtered, fb], ignore_index=True)

        return filtered.head(n_return or n_suggest)
