"""
scripts/fix_suspicious_foods.py  — DEV_LOG Entry 28

แก้ข้อมูลอาหารที่ตัวเลขผิดปกติ (ส่วนใหญ่จาก calforlife ที่น่าจะเป็นค่า
"ต่อจาน"/ค่าผงสำเร็จรูป แต่ถูกเก็บเป็น "ต่อ 100g") + รวมชื่อซ้ำ + เติมชื่อ
อังกฤษที่หาย — ดูเหตุผลรายแถวในคอมเมนต์ของแต่ละส่วน

วิธีแก้ค่าใช้ recipe blend แบบเดียวกับ scripts/add_cnn_missing_dishes.py
(ผสมวัตถุดิบที่มีค่าวัดจริงใน DB ตามสัดส่วนสูตรต่อ 100g)

รัน (จาก root chabot/): python scripts/fix_suspicious_foods.py
(ออกแบบให้รันครั้งเดียว — รันซ้ำจะคำนวณค่าเดิมซ้ำ ไม่เสียหาย แต่แถวที่ลบ
ไปแล้วจะถูกข้าม)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.compute_sugar_risk import compute_sugar_risk  # noqa: E402

CSV = "foods_master_v2.csv"
NUM = ["energy_kcal", "water_g", "protein_g", "fat_g", "carb_available_g",
       "dietary_fiber_g", "ash_g", "calcium_mg", "phosphorus_mg", "magnesium_mg",
       "sodium_mg", "potassium_mg", "iron_mg", "copper_mg", "zinc_mg", "iodine_ug",
       "betacarotene_ug", "retinol_ug", "vitamin_a_rae_ug", "thiamin_mg",
       "riboflavin_mg", "niacin_mg", "vitamin_c_mg", "vitamin_e_mg"]

df = pd.read_csv(CSV)
idx = df.set_index("food_id")
log = []


def pseudo(known_only=False, **kw):
    s = pd.Series(np.nan if known_only else 0.0, index=NUM)
    for k, v in kw.items():
        s[k] = v
    return s


WATER = pseudo(water_g=100)
OIL = pseudo(energy_kcal=884, fat_g=100)
SUGAR = pseudo(energy_kcal=387, carb_available_g=100, sodium_mg=1, potassium_mg=2)
# USDA 12117 Nuts, coconut milk, raw (กะทิสด) — รู้เฉพาะค่าที่ระบุ
COCO = pseudo(known_only=True, energy_kcal=230, water_g=67.6, protein_g=2.29, fat_g=23.8,
              carb_available_g=3.3, dietary_fiber_g=2.2, calcium_mg=16, phosphorus_mg=100,
              magnesium_mg=37, sodium_mg=15, potassium_mg=263)


def db(fid):
    r = idx.loc[fid]
    s = r[NUM].astype(float).copy()
    if bool(r.get("potassium_estimated", False)):
        s["potassium_mg"] = np.nan
    if bool(r.get("phosphorus_estimated", False)):
        s["phosphorus_mg"] = np.nan
    return s


I = {"pork_minced": 20783, "pork": 20771, "pork_belly": 20786, "holy_basil": 21891,
     "bird_chili": 20324, "garlic": 21221, "shallot": 21245, "oyster_sauce": 21264,
     "fish_sauce": 21284, "soy_sauce": 21268, "dark_soy": 21271, "winged_bean": 20230,
     "shrimp_boiled": 20857, "chili_paste_roasted": 21296, "peanut": 20124, "lime": 21966,
     "egg": 21095, "palm_sugar": 21215, "sticky_rice": 20010, "long_bean": 20228,
     "red_curry_paste": 21290, "grilled_green_chili": 20331, "wheat_flour": 21839,
     "evap_milk": 21813, "chicken": 20708}


def ing(n):
    return {"WATER": WATER, "OIL": OIL, "SUGAR": SUGAR, "COCO": COCO}.get(n) if n in (
        "WATER", "OIL", "SUGAR", "COCO") else db(I[n])


def blend(parts):
    assert abs(sum(f for _, f in parts) - 1) < 1e-6
    out = {}
    for c in NUM:
        num = w = 0.0
        for n, f in parts:
            v = ing(n)[c]
            if pd.notna(v):
                num += f * v
                w += f
        out[c] = round(num / w, 2) if w >= 0.5 else np.nan
    # น้ำ = ส่วนที่เหลือ กันองค์ประกอบรวมเกิน 100g
    solids = sum(out[c] for c in ["protein_g", "fat_g", "carb_available_g", "dietary_fiber_g", "ash_g"]
                 if pd.notna(out[c]))
    if pd.notna(out["water_g"]) and out["water_g"] + solids > 100:
        out["water_g"] = round(max(100 - solids, 0), 2)
    return out


def replace_with_recipe(fid, parts, why, food_type=None):
    if fid not in idx.index:
        return
    i = df.index[df.food_id == fid][0]
    before = df.loc[i, ["energy_kcal", "protein_g", "fat_g", "sodium_mg"]].tolist()
    for c, v in blend(parts).items():
        df.at[i, c] = v
    df.at[i, "potassium_estimated"] = False
    df.at[i, "phosphorus_estimated"] = False
    df.at[i, "mineral_source"] = (f"recipe (Entry 28) แทนค่าเดิมที่ผิดปกติ ({why}): " +
                                  " + ".join(f"{n} {int(round(f * 100))}%" for n, f in parts))
    if food_type:
        df.at[i, "food_type"] = food_type
    after = df.loc[i, ["energy_kcal", "protein_g", "fat_g", "sodium_mg"]].tolist()
    log.append(f"[recipe] {fid} {df.at[i, 'food_name_th']}: kcal/P/F/Na {before} → {after} ({why})")


# ── 1) แทนค่าด้วยสูตร ──────────────────────────────────────────────────────
replace_with_recipe(22351, [("pork_minced", .50), ("holy_basil", .06), ("bird_chili", .03), ("garlic", .04),
                            ("oyster_sauce", .04), ("fish_sauce", .02), ("soy_sauce", .01), ("SUGAR", .02),
                            ("OIL", .08), ("WATER", .20)],
                    "โปรตีน 38g/100g สูงเกินจริงสำหรับผัดกะเพรา — label CNN ข้อ 51")
replace_with_recipe(22309, [("winged_bean", .45), ("shrimp_boiled", .12), ("COCO", .10),
                            ("chili_paste_roasted", .06), ("shallot", .05), ("peanut", .05), ("lime", .04),
                            ("fish_sauce", .03), ("SUGAR", .03), ("egg", .07)],
                    "โปรตีน 42g/100g, 335 kcal เป็นไปไม่ได้สำหรับยำผัก")
replace_with_recipe(22067, [("pork", .55), ("pork_belly", .15), ("palm_sugar", .12), ("soy_sauce", .04),
                            ("dark_soy", .02), ("shallot", .04), ("OIL", .04), ("WATER", .04)],
                    "ไขมัน 75g/100g, 807 kcal")
replace_with_recipe(22081, [("pork", .68), ("palm_sugar", .10), ("soy_sauce", .04), ("garlic", .04),
                            ("OIL", .12), ("SUGAR", .02)],
                    "ไขมัน 53g/100g")
replace_with_recipe(22313, [("sticky_rice", .60), ("pork", .25), ("COCO", .04), ("palm_sugar", .04),
                            ("garlic", .02), ("soy_sauce", .02), ("OIL", .03)],
                    "586 kcal/100g น่าจะเป็นค่าต่อชุด")
replace_with_recipe(22222, [("pork", .50), ("long_bean", .20), ("red_curry_paste", .05), ("OIL", .08),
                            ("SUGAR", .02), ("fish_sauce", .02), ("WATER", .13)],
                    "โปรตีน 31.7g/100g สูงเกินจริงสำหรับผัดที่มีผัก")
replace_with_recipe(22487, [("grilled_green_chili", .60), ("shallot", .15), ("garlic", .12),
                            ("fish_sauce", .05), ("lime", .03), ("SUGAR", .02), ("WATER", .03)],
                    "โปรตีน 36g/100g, Na/K ไม่มี — label CNN ข้อ 18", food_type="dish")
replace_with_recipe(22409, [("wheat_flour", .25), ("SUGAR", .28), ("egg", .15), ("OIL", .15),
                            ("evap_milk", .10), ("WATER", .07)],
                    "P+F+C รวม 122g ต่อ 100g เป็นไปไม่ได้")

# ── 2) แก้เฉพาะบางค่า ──────────────────────────────────────────────────────
def set_val(fid, col, val, why):
    if fid not in idx.index:
        return
    i = df.index[df.food_id == fid][0]
    old = df.at[i, col]
    df.at[i, col] = val
    log.append(f"[fix] {fid} {df.at[i, 'food_name_th']}: {col} {old} → {val} ({why})")

ck, fs, ss = db(20708), db(21284), db(21268)
set_val(22170, "sodium_mg", round(.85 * ck["sodium_mg"] + .03 * fs["sodium_mg"] + .02 * ss["sodium_mg"], 1),
        "Na 2,370mg สูงเกินจริงสำหรับไก่ย่าง — คำนวณจากไก่ 85% + น้ำปลา 3% + ซีอิ๊ว 2%")
r = idx.loc[21850]
set_val(21850, "energy_kcal", round(r.protein_g * 4 + r.fat_g * 9 + r.carb_available_g * 4),
        "kcal 137 ไม่สอดคล้องกับ macro — ใช้ Atwater (ตรงกับ USDA 19095 = 207)")
set_val(22453, "food_type", "ingredient", "เป็นผงซุปก่อนชง (Na 7,333mg/100g) ไม่ใช่จานพร้อมกิน")
set_val(20795, "food_type", "dish", "หมูกรอบจาก Thai FCD ใช้แทน 22059 ที่ข้อมูลผิดปกติ")

# ── 3) รวมชื่อซ้ำ: เก็บแถวที่ข้อมูลครบ/วัดจริงมากกว่า ลบแถวที่ด้อยกว่า ────────
DROP = {
    22059: "หมูกรอบ calforlife: ไขมัน 72g, Na 4,237mg — ใช้ 20795 (Thai FCD) แทน",
    11160: "ขนมจีนน้ำพริก ซ้ำกับ 11141 (11141 มี Na/K/P วัดจริงครบ)",
    11162: "ขนมจีนน้ำยาป่า ซ้ำ — ไม่มี Na, K/P เป็นค่าประมาณ (เก็บ 11145)",
    11195: "ขนมจีนน้ำยาป่า ซ้ำกับ 11145 (ข้อมูลครบเท่ากัน เก็บแถวแรก)",
    11251: "ข้าวหมูอบ ซ้ำกับ 11088 (11088 มี P วัดจริง)",
    11196: "ซุปหน่อไม้ ซ้ำกับ 11146 (11196 P = 0 ปลอม)",
    22718: "แซนด์วิชเลอแปง ซ้ำกับ 22735 (ค่าเดียวกัน 22735 มี K)",
}
for fid, why in DROP.items():
    if fid in set(df.food_id):
        log.append(f"[drop] {fid} {idx.loc[fid].food_name_th}: {why}")
df = df[~df.food_id.isin(DROP)].reset_index(drop=True)

# แกงหอยขม 2 แถวเป็นคนละสูตร: 11139 มีกะทิ (ไขมัน 10g) = แกงคั่วหอยขม — เปลี่ยนชื่อ
# ให้ชัด (ตรงกับ label CNN ข้อ 56 "แกงคั่วหอย") 11191 ไม่มีกะทิ คงชื่อเดิม
i = df.index[df.food_id == 11139]
if len(i) and df.at[i[0], "food_name_th"] == "แกงหอยขม":
    df.at[i[0], "food_name_th"] = "แกงคั่วหอยขม"
    df.at[i[0], "food_name_en"] = "Curry, river snail with coconut milk (Kaeng khua hoi khom)"
    log.append("[rename] 11139 แกงหอยขม → แกงคั่วหอยขม (สูตรกะทิ ไขมัน 10g ต่างจาก 11191)")

# ── 4) เติมชื่ออังกฤษที่หาย ───────────────────────────────────────────────
EN = {"ขนมจีนน้ำพริกปลาร้า": "Round rice noodles with fermented fish chili sauce (Khanom jeen nam prik pla ra)",
      "ลูกเดือยน้ำกะทิ": "Job's tears in coconut milk (dessert)"}
for th, en in EN.items():
    m = (df.food_name_th == th) & df.food_name_en.isna()
    if m.any():
        df.loc[m, "food_name_en"] = en
        log.append(f"[en] {th} → {en}")

# ── 5) น้ำของแถวสูตร Entry 20/25 ที่องค์ประกอบรวมเกิน 100g ──────────────────
solid_cols = ["protein_g", "fat_g", "carb_available_g", "dietary_fiber_g", "ash_g"]
m = df.food_id.between(90000, 90099)
tot = df.loc[m, "water_g"] + df.loc[m, solid_cols].fillna(0).sum(axis=1)
over = tot[tot > 100.5].index
for j in over:
    new_w = round(100 - df.loc[j, solid_cols].fillna(0).sum(), 2)
    log.append(f"[water] {df.at[j, 'food_id']} {df.at[j, 'food_name_th']}: water {df.at[j, 'water_g']} → {new_w}")
    df.at[j, "water_g"] = new_w

# sugar_risk ของแถวที่แก้ค่า (คำนวณวิธีเดียวกับทั้งฐาน)
sr = compute_sugar_risk(df)
changed = df.food_id.isin([22351, 22309, 22067, 22081, 22313, 22222, 22487, 22409, 21850])
df.loc[changed, "sugar_risk"] = sr[changed]
df["sugar_risk"] = df["sugar_risk"].astype(int)

df.to_csv(CSV, index=False)
print("\n".join(log))
print(f"\nรวม {len(df)} แถว | dish {int((df.food_type == 'dish').sum())}")
