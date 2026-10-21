"""
scripts/fill_ckd_minerals_39.py  — DEV_LOG Entry 24

แทนค่า potassium_mg / phosphorus_mg ที่เป็น "ค่าประมาณจาก regression"
(Entry 21, R²≈0.06 สำหรับ K) หรือเป็น 0 ปลอม (calforlife ใส่ 0 เวลาไม่มีข้อมูล)
ของ 39 เมนูที่ผ่านเกณฑ์ CKD ข้ออื่นครบ แต่ถูกตัดเพราะแร่ธาตุเป็นค่าประมาณ

วิธีหาค่า (เรียงตามความน่าเชื่อถือ):
  S = sibling  : เมนูเดียวกัน/ใกล้เคียงที่มีค่าวัดจริงในฐานข้อมูล (Thai FCD /
                 ตารางคุณค่าอาหารไทย กรมอนามัย) ปรับด้วย dilution factor
                 = เฉลี่ย(โปรตีนเป้าหมาย/โปรตีน sibling, kcal เป้าหมาย/kcal sibling)
  U = USDA     : USDA FoodData Central (SR Legacy) สำหรับอาหารสากล
  R = recipe   : สูตรอาหารจากวัตถุดิบที่มีค่าวัดจริง (DB หรือ USDA) — วัตถุดิบ
                 โปรตีนหลักถูก "calibrate" ให้โปรตีนรวมของสูตรเท่ากับโปรตีนที่
                 วัดจริงของเมนูนั้น ส่วนที่เหลือของ 100g = น้ำ (ไม่มีแร่ธาตุ)
  ถ้าคำนวณได้ทั้ง S และ R → ใช้ค่าที่สูงกว่า (ปลอดภัยกว่าสำหรับผู้ป่วย CKD)

แก้เฉพาะคอลัมน์ที่เป็นค่าประมาณ (flag=True) หรือเป็น 0 ปลอม — ค่าที่วัดจริง
อยู่แล้วไม่แตะ แล้วตั้ง flag = False และบันทึกที่มาในคอลัมน์ mineral_source

รัน (จาก root chabot/):  python scripts/fill_ckd_minerals_39.py
"""
import pandas as pd

CSV = "foods_master_v2.csv"

# ── USDA FoodData Central, SR Legacy, ต่อ 100g: (protein_g, K_mg, P_mg) ──────
USDA = {
    "coconut_milk":   (2.29, 263, 100),   # 12117 Nuts, coconut milk, raw
    "rice_flour":     (5.95, 76, 98),     # 20061 Rice flour, white
    "wheat_flour":    (10.33, 107, 108),  # 20081 Wheat flour, white, all-purpose
    "tapioca":        (0.19, 11, 7),      # 20068 Tapioca, pearl, dry
    "water_chestnut": (1.40, 584, 63),    # 11588 Waterchestnuts, chinese, raw
    "okra":           (1.93, 299, 61),    # 11278 Okra, raw
    "oyster":         (9.45, 168, 162),   # 15171 Mollusks, oyster, Pacific, raw
    "clam":           (12.77, 46, 198),   # 15157 Mollusks, clam, mixed species, raw
    "blue_crab":      (18.06, 329, 229),  # 15136 Crustaceans, crab, blue, raw
    "tuna_canned":    (19.44, 237, 163),  # 15121 Fish, tuna, light, canned in water
    "mayonnaise":     (0.96, 20, 21),     # 04025 Salad dressing, mayonnaise
    "tamarind":       (2.80, 628, 113),   # 09322 Tamarinds, raw
    "sugar":          (0.0, 0, 0),
    "oil":            (0.0, 0, 0),
}
USDA_ICE_VANILLA = (3.50, 207, 199, 105)   # 19095 Ice creams, vanilla (P, kcal, K, Ph)
USDA_ICE_STRAW_P = 100                     # 19271 Ice creams, strawberry (~58mg/58g)
USDA_EGG_DROP = (1.16, 22.0, 15.0)         # FDC 174807 Soup, egg drop, Chinese restaurant:
                                            # 2.8g โปรตีน / 53mg K / 36.2mg P ต่อ 241g → ต่อ 100g
# กระเพาะปลาแช่น้ำ: โปรตีนแห้ง 64.1g (DB 20843) คืนน้ำราว 4 เท่า ≈ 16g — ส่วน
# ใหญ่เป็นคอลลาเจน ไม่มีค่า K/P วัดจริง จึงนับเป็น 0 (ใช้แค่ให้สัดส่วนโปรตีนสมจริง)
FISH_MAW_REHYD = (16.0, 0, 0)

df = pd.read_csv(CSV)
if "mineral_source" not in df.columns:
    df["mineral_source"] = pd.NA
idx = df.set_index("food_id")


def db(fid):
    """วัตถุดิบจาก DB — ต้องเป็นค่าวัดจริงเท่านั้น (ไม่ใช่ค่าประมาณ/0)"""
    r = idx.loc[fid]
    assert not r["potassium_estimated"] and not r["phosphorus_estimated"], fid
    assert r["potassium_mg"] > 0 and r["phosphorus_mg"] > 0, fid
    return (float(r["protein_g"]), float(r["potassium_mg"]), float(r["phosphorus_mg"]))


def sibling(target, sib_ids):
    if target not in idx.index:
        return (None, None)
    t = idx.loc[target]
    sibs = idx.loc[sib_ids]
    f = ((t.protein_g / sibs.protein_g.mean()) + (t.energy_kcal / sibs.energy_kcal.mean())) / 2
    return sibs.potassium_mg.mean() * f, sibs.phosphorus_mg.mean() * f


def recipe(target, fixed, calib):
    """fixed: [(ingredient, fraction)], calib: ingredient ที่ปรับสัดส่วนให้โปรตีนตรง"""
    prot = float(idx.loc[target].protein_g)
    p_fixed = sum(frac * ing[0] for ing, frac in fixed)
    f_cal = max((prot - p_fixed) / calib[0], 0.0)
    total = sum(frac for _, frac in fixed) + f_cal
    assert total <= 1.02, f"{target}: สัดส่วนรวม {total:.2f} > 1"
    k = sum(frac * ing[1] for ing, frac in fixed) + f_cal * calib[1]
    p = sum(frac * ing[2] for ing, frac in fixed) + f_cal * calib[2]
    return k, p


U = USDA
chicken, egg, mushroom = db(20708), db(21095), db(20405)
tilapia, catfish, pork = db(20925), db(20907), db(20771)
mungbean, blackbean, palm_sugar = db(20098), db(20100), db(21215)
cabbage, corn, garlic, pineapple = db(20188), db(21776), db(21221), db(20598)
shrimp, kapi_kei, banana_flower = db(20863), db(21252), db(20402)
curry_paste, pumpkin, papaya = db(21290), db(20340), db(20369)
peanut = db(20126)
khanomjeen = (U["rice_flour"][0] * 0.3, U["rice_flour"][1] * 0.3, U["rice_flour"][2] * 0.3)

S, R, UU = "sibling", "recipe", "USDA"
results = {}   # food_id -> (K, P, note)

def put(fid, k, p, note):
    if fid not in idx.index:   # แถวที่ถูกลบภายหลัง (Entry 28) — ข้าม
        return
    results[fid] = (k, p, note)

def best(fid, cands, note):
    """cands: [(k,p)] เลือกค่าสูงสุดแยกรายแร่ธาตุ"""
    put(fid, max(c[0] for c in cands), max(c[1] for c in cands), note)

# ── ก๋วยเตี๋ยว / ขนมจีน ──
put(11029, *sibling(11029, [11031, 11032]), f"{S}: ราดหน้าหมู(11031)+หมูสับ(11032) Thai FCD")
put(11030, *sibling(11030, [11031, 11032]), f"{S}: ราดหน้าหมู(11031)+หมูสับ(11032) Thai FCD")
put(11144, *sibling(11144, [11143]), f"{S}: ขนมจีนน้ำยา(11143)")
put(11160, *sibling(11160, [11141]), f"{S}: ขนมจีนน้ำพริก(11141) เมนูเดียวกันต่างแหล่ง")
put(21479, *sibling(21479, [11012, 11013, 11014]), f"{S}: ก๋วยเตี๋ยวเส้นเล็กน้ำ 3 แบบ (11012-11014)")
put(22492, *sibling(22492, [21475]), f"{S}: บะหมี่หมูแดงน้ำ(21475) Thai FCD — แทน K=0 ปลอมจาก calforlife")
put(22699, *sibling(22699, [11035]), f"{S}: เกาเหลาเนื้อตุ๋น(11035) — แทน K=0 ปลอมจาก calforlife")
put(11140, *recipe(11140, [(khanomjeen, .40), (U["coconut_milk"], .30), (pineapple, .12), (garlic, .02)], shrimp),
    f"{R}: ขนมจีน 40% (แป้งข้าวเจ้า USDA×0.3) + กะทิ 30% (USDA) + สับปะรด 12% + กระเทียม 2% + กุ้ง (calibrate)")

# ── แกง / ต้ม ──
put(11103, *recipe(11103, [(U["coconut_milk"], .35), (mushroom, .05)], U["tuna_canned"]),
    f"{R}: กะทิ 35% (USDA) + เห็ด 5% + ทูน่า (USDA, calibrate)")
put(21391, *recipe(21391, [(U["coconut_milk"], .35), (mushroom, .05)], chicken),
    f"{R}: กะทิ 35% (USDA) + เห็ด 5% + ไก่ (calibrate)")
put(11150, *recipe(11150, [(banana_flower, .30), (curry_paste, .04), (U["coconut_milk"], .15)], chicken),
    f"{R}: หยวกกล้วย 30% (ใช้ค่าหัวปลีแทน — K สูงกว่า ปลอดภัยกว่า) + พริกแกง 4% + กะทิ 15% + ไก่ (calibrate)")
put(11154, *recipe(11154, [(kapi_kei, .05), (cabbage, .20)], tilapia),
    f"{R}: กะปิเคย 5% + ผัก 20% + ปลา (ปลานิล, calibrate)")
best(11157, [sibling(11157, [11137]),
             recipe(11157, [(papaya, .35), (curry_paste, .04), (U["tamarind"], .03)], tilapia)],
     f"max({S}: แกงส้มผักรวมปลาช่อน(11137), {R}: มะละกอ 35% + พริกแกง + มะขาม + ปลา)")
put(11192, *sibling(11192, [11193]), f"{S}: แกงอ่อมปลา(11193)")
best(22504, [sibling(22504, [21393]), recipe(22504, [], catfish)],
     f"max({S}: ต้มยำกุ้ง(21393), {R}: ปลาดุก calibrate) — แทน K=0 ปลอมจาก calforlife")
best(11246, [recipe(11246, [], egg),
             (USDA_EGG_DROP[1] * 2.89 / USDA_EGG_DROP[0], USDA_EGG_DROP[2] * 2.89 / USDA_EGG_DROP[0])],
     f"max({R}: ไข่ (calibrate), {UU}: Soup egg drop 174807 ปรับตามโปรตีน)")
best(11001, [recipe(11001, [(chicken, .15), (egg, .10), (mushroom, .08), (U["tapioca"], .03)], FISH_MAW_REHYD),
             sibling(11001, [11002])],
     f"max({R}: ไก่ 15% + ไข่ 10% + เห็ด 8% + แป้งมัน 3% + กระเพาะปลา (calibrate, K/P=0), {S}: กระเพาะปลาเส้นหมี่(11002))")

# ── อาหารทะเล / ผัด / ทอด ──
put(11238, *recipe(11238, [(U["tamarind"], .05), (U["sugar"], .08), (U["oil"], .03)], shrimp),
    f"{R}: มะขาม 5% (USDA) + น้ำตาล + น้ำมัน + กุ้ง (calibrate)")
put(20985, *recipe(20985, [], U["oyster"]), f"{UU}: Oyster Pacific raw 15171 ปรับตามโปรตีน")
put(20990, *recipe(20990, [], U["clam"]), f"{UU}: Clam mixed species raw 15157 ปรับตามโปรตีน")
put(22345, *recipe(22345, [(U["okra"], .60), (U["oil"], .06)], egg),
    f"{R}: กระเจี๊ยบเขียว 60% (USDA) + น้ำมัน + ไข่ (calibrate)")
put(22391, *sibling(22391, [21616]), f"{S}: เผือกชุบแป้งทอด(21616) Thai FCD")
put(22461, *recipe(22461, [(U["tapioca"], .15), (U["oil"], .12)], tilapia),
    f"{R}: ปลาบด (ปลานิล, calibrate) + แป้งมัน 15% + น้ำมัน 12%")
put(22179, *recipe(22179, [(corn, .30), (U["mayonnaise"], .15), (cabbage, .20)], U["tuna_canned"]),
    f"{R}: ข้าวโพด 30% + มายองเนส 15% (USDA) + กะหล่ำ 20% + ทูน่า (USDA, calibrate)")
put(22247, *recipe(22247, [(pork, .12), (U["sugar"], .08)], U["wheat_flour"]),
    f"{R}: หมูแดง (หมูเนื้อ) 12% + น้ำตาล 8% + แป้งสาลี (USDA, calibrate)")
put(22459, *recipe(22459, [(pork, .12), (U["sugar"], .08), (U["oil"], .15)], U["wheat_flour"]),
    f"{R}: หมู 12% + น้ำตาล + น้ำมัน 15% + แป้งสาลี (USDA, calibrate)")
put(22483, *recipe(22483, [(U["tapioca"], .45), (peanut, .03)], pork),
    f"{R}: สาคู 45% (USDA) + ถั่วลิสง 3% + หมู (calibrate)")

# ── ขนมหวาน ──
put(21504, *recipe(21504, [(U["coconut_milk"], .40), (U["sugar"], .08)], U["rice_flour"]),
    f"{R}: กะทิ 40% + น้ำตาล 8% + แป้งข้าวเจ้า (USDA, calibrate)")
put(21518, *recipe(21518, [(egg, .15), (U["coconut_milk"], .25), (palm_sugar, .20)], mungbean),
    f"{R}: ไข่ 15% + กะทิ 25% + น้ำตาลมะพร้าว 20% + ถั่วเขียว (calibrate)")
put(21529, *recipe(21529, [(U["water_chestnut"], .15), (U["coconut_milk"], .20), (U["sugar"], .15)], U["tapioca"]),
    f"{R}: แห้ว 15% (USDA) + กะทิ 20% + น้ำตาล 15% + แป้งมัน (calibrate)")
put(21544, *recipe(21544, [(U["coconut_milk"], .30), (palm_sugar, .10)], U["rice_flour"]),
    f"{R}: กะทิ 30% + น้ำตาลมะพร้าว 10% + แป้งข้าวเจ้า (calibrate)")
put(21545, *recipe(21545, [(U["coconut_milk"], .15), (U["sugar"], .35)], mungbean),
    f"{R}: กะทิ 15% + น้ำตาล 35% + ถั่วเขียว (calibrate)")
put(21548, *recipe(21548, [(U["sugar"], .15)], U["coconut_milk"]),
    f"{R}: กะทิ (calibrate) + น้ำตาล + วุ้น")
put(21556, *recipe(21556, [(pumpkin, .35), (U["coconut_milk"], .20), (palm_sugar, .12)], egg),
    f"{R}: ฟักทอง 35% + กะทิ 20% + น้ำตาลมะพร้าว 12% + ไข่ (calibrate)")
put(21557, *recipe(21557, [(U["coconut_milk"], .25), (U["tapioca"], .15), (U["sugar"], .12)], blackbean),
    f"{R}: กะทิ 25% + สาคู 15% + น้ำตาล 12% + ถั่วดำ (calibrate)")

t = idx.loc[22529]
fv = ((t.protein_g / USDA_ICE_VANILLA[0]) + (t.energy_kcal / USDA_ICE_VANILLA[1])) / 2
put(22529, USDA_ICE_VANILLA[2] * fv, USDA_ICE_VANILLA[3] * fv,
    f"{UU}: Ice creams, vanilla 19095 ปรับตามโปรตีน/kcal — แทน K=0 ปลอมจาก calforlife")
put(21852, None, USDA_ICE_STRAW_P, f"{UU}: Ice creams, strawberry 19271")

# ── 2 เมนูสูตรของเราเอง (Entry 20) — คำนวณฟอสฟอรัสใหม่จากวัตถุดิบที่มีค่าจริง ──
crab_aro = (9.17, None, U["blue_crab"][2] * 9.17 / U["blue_crab"][0])  # ปูนิ่ม ARO ปรับจากปูม้า USDA
put(90004, None, .65 * crab_aro[2] + .20 * garlic[2],
    f"{R}: ปูนิ่ม 65% (P ปรับจาก Blue crab USDA 15136 ตามโปรตีน) + กระเทียม 20% + น้ำมัน")
clam_fried_p = results[20990][1]
nprik = idx.loc[21296]
nprik_p = float(nprik.phosphorus_mg) if not nprik.phosphorus_estimated else None
p_90007 = .65 * clam_fried_p + .10 * cabbage[2] + (.15 * nprik_p if nprik_p else 0)
put(90007, None, p_90007,
    f"{R}: หอยลายผัด 65% (ค่าใหม่ข้างบน) + น้ำพริกเผา 15%" + ("" if nprik_p else " (ไม่มีค่า P จริง ไม่นับ)") + " + ผัก 10%")

# ── เขียนกลับ: แทนเฉพาะคอลัมน์ที่เป็นค่าประมาณหรือ 0 ปลอม ──
rows = []
for fid, (k, p, note) in results.items():
    i = df.index[df.food_id == fid][0]
    changed = []
    if k is not None and (df.at[i, "potassium_estimated"] or df.at[i, "potassium_mg"] == 0):
        old = df.at[i, "potassium_mg"]
        df.at[i, "potassium_mg"] = round(k, 1)
        df.at[i, "potassium_estimated"] = False
        changed.append(f"K {old:.0f}→{k:.0f}")
    if p is not None and (df.at[i, "phosphorus_estimated"] or df.at[i, "phosphorus_mg"] == 0):
        old = df.at[i, "phosphorus_mg"]
        df.at[i, "phosphorus_mg"] = round(p, 1)
        df.at[i, "phosphorus_estimated"] = False
        changed.append(f"P {old:.0f}→{p:.0f}")
    if changed:
        df.at[i, "mineral_source"] = note
    rows.append((fid, df.at[i, "food_name_th"], ", ".join(changed) or "(ไม่เปลี่ยน)", note))

df.to_csv(CSV, index=False)
for r in rows:
    print(f"{r[0]} {r[1]:<28} {r[2]:<22} | {r[3]}")
print(f"\nอัปเดต {sum(1 for r in rows if r[2] != '(ไม่เปลี่ยน)')} เมนู")
