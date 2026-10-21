"""
scripts/add_cnn_missing_dishes.py  — DEV_LOG Entry 25

เพิ่มข้อมูลโภชนาการให้ 18 label ของ CNN (THFOOD-100) ที่ไม่มีในฐานข้อมูล
(ดู cnn_label_food_mapping.csv สถานะ "ไม่มี") ด้วยวิธีเดียวกับ Entry 20:
ผสมวัตถุดิบที่มีอยู่ใน foods_master_v2.csv ถ่วงน้ำหนักตามสัดส่วนสูตรอาหาร
มาตรฐาน (ต่อ 100g ของอาหารที่ปรุงเสร็จ)

กติกา:
  - ใช้เฉพาะค่าวัดจริงของวัตถุดิบ — ค่า K/P ที่เป็นค่าประมาณจาก regression
    (flag *_estimated) และค่า 0 ปลอมจาก calforlife ถือเป็น "ไม่มีข้อมูล"
  - สารอาหารตัวไหนที่วัตถุดิบ < 50% โดยน้ำหนักไม่มีข้อมูล → ปล่อย NaN
    (ถ้ามี ≥ 50% ใช้ค่าเฉลี่ยถ่วงน้ำหนักเฉพาะส่วนที่มีข้อมูล)
  - น้ำมัน/น้ำตาล/น้ำเปล่า/ข้าวสวย ใช้ค่ามาตรฐาน (ข้าวสวยใช้ค่าเดียวกับ
    RICE_REF_PER100G ใน ml/pipeline.py — USDA white rice cooked)
  - sugar_risk คำนวณด้วย scripts/compute_sugar_risk.compute_sugar_risk
    (วิธีเดียวกับทั้งฐาน) — คำนวณใหม่ให้แถว 900xx ทั้งหมดรวม 9 แถวจาก Entry 20

รัน (จาก root chabot/): python scripts/add_cnn_missing_dishes.py
รันซ้ำได้ — ลบแถว food_id ในช่วง 90010-90099 ออกก่อนแล้วสร้างใหม่ทุกครั้ง
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
df = df[~df.food_id.between(90010, 90099)].reset_index(drop=True)
idx = df.set_index("food_id")


def pseudo(**kw):
    """วัตถุดิบมาตรฐาน — ค่าที่ไม่ระบุ = 0 (รู้แน่ว่าไม่มี) ยกเว้นระบุ NaN"""
    s = pd.Series(0.0, index=NUM)
    for k, v in kw.items():
        s[k] = v
    return s


WATER = pseudo(water_g=100)
OIL = pseudo(energy_kcal=884, fat_g=100)
SUGAR = pseudo(energy_kcal=387, carb_available_g=100, sodium_mg=1, potassium_mg=2)
RICE = pseudo(energy_kcal=130, water_g=68.4, protein_g=2.7, fat_g=0.3, carb_available_g=28.2,
              sodium_mg=1, potassium_mg=35, calcium_mg=10, magnesium_mg=12, phosphorus_mg=43)
for c in NUM:   # ข้าวสวย: รู้แค่ตัวที่ระบุ ที่เหลือ NaN
    if c not in ("energy_kcal", "water_g", "protein_g", "fat_g", "carb_available_g",
                 "sodium_mg", "potassium_mg", "calcium_mg", "magnesium_mg", "phosphorus_mg"):
        RICE[c] = np.nan


def db(fid):
    """แถววัตถุดิบจาก DB — ตัดค่าประมาณ/0 ปลอมทิ้ง (เป็น NaN)"""
    r = idx.loc[fid]
    s = r[NUM].astype(float).copy()
    if bool(r.get("potassium_estimated", False)):
        s["potassium_mg"] = np.nan
    if bool(r.get("phosphorus_estimated", False)):
        s["phosphorus_mg"] = np.nan
    if fid // 1000 == 22:  # calforlife ใส่ 0 เมื่อไม่มีข้อมูล
        for c in ("sodium_mg", "potassium_mg", "phosphorus_mg", "calcium_mg"):
            if s[c] == 0:
                s[c] = np.nan
    return s


def crab():
    """ปูม้า: รวม 2 แถวที่ต่างคนต่างมีค่าวัดจริงคนละตัว (22375 มี K, 20973 มี P)"""
    a, b = db(22375), db(20973)
    return a.combine_first(b)


I = {  # วัตถุดิบ (food_id ใน DB)
    "chicken": 20708, "chicken_thigh_fried": 20717, "pork": 20771, "pork_belly": 20786,
    "pork_belly_fried": 20788, "sausage_fried": 20824, "ham_fried": 20842, "egg": 21095,
    "seabass_steamed": 20878, "squid": 20959, "catfish_fried": 20910, "snakehead": 20897,
    "shredded_pork": 20835, "cashew": 20142, "onion": 20401, "bell_pepper": 20333,
    "chili": 20327, "bird_chili": 20324, "dried_chili": 21239, "garlic": 21221,
    "shallot": 21245, "ginger": 21229, "shiitake": 20437, "kale_sprout": 20203,
    "morning_glory": 20287, "long_bean": 20228, "green_mango": 20541, "celery": 21822,
    "carrot": 20208, "peas": 20231, "raisin": 22015, "lime": 21966, "peanut": 20124,
    "oyster_sauce": 21264, "soy_sauce": 21268, "dark_soy": 21271, "fish_sauce": 21284,
    "ketchup": 21261, "kapi": 21250, "curry_powder": 21845, "evap_milk": 21813,
    "wheat_flour": 21839, "tapioca_starch": 20084,
}


def ing(name):
    if name == "WATER": return WATER
    if name == "OIL": return OIL
    if name == "SUGAR": return SUGAR
    if name == "RICE": return RICE
    if name == "crab": return crab()
    return db(I[name])


def blend(parts):
    total = sum(f for _, f in parts)
    assert abs(total - 1.0) < 1e-6, f"สัดส่วนรวม {total}"
    out = {}
    for c in NUM:
        num = 0.0
        w = 0.0
        for name, f in parts:
            v = ing(name)[c]
            if pd.notna(v):
                num += f * v
                w += f
        out[c] = round(num / w, 2) if w >= 0.5 else np.nan
    return out


# (food_id, dir, ชื่อไทย = ชื่อ label CNN, ชื่ออังกฤษ, สูตร [(วัตถุดิบ, สัดส่วน)])
RECIPES = [
    (90010, "00", "ข้าวผัดอเมริกัน", "American fried rice with fried chicken, sausage and egg",
     [("RICE", .45), ("ketchup", .05), ("OIL", .06), ("chicken_thigh_fried", .14), ("sausage_fried", .08),
      ("ham_fried", .05), ("egg", .10), ("carrot", .02), ("peas", .02), ("raisin", .02), ("onion", .01)]),
    (90011, "01", "ข้าวหน้าไก่", "Rice topped with chicken in gravy (Khao Na Kai)",
     [("RICE", .55), ("chicken", .18), ("oyster_sauce", .03), ("soy_sauce", .02), ("SUGAR", .01),
      ("tapioca_starch", .02), ("shiitake", .03), ("garlic", .01), ("OIL", .02), ("WATER", .13)]),
    (90012, "07", "ไก่ผัดเม็ดมะม่วงหิมพานต์", "Stir-fried chicken with cashew nuts",
     [("chicken", .42), ("cashew", .12), ("onion", .12), ("bell_pepper", .08), ("dried_chili", .01),
      ("oyster_sauce", .05), ("soy_sauce", .01), ("SUGAR", .02), ("garlic", .02), ("wheat_flour", .04),
      ("OIL", .09), ("WATER", .02)]),
    (90013, "09", "ผัดพริกไทยดำ", "Stir-fried pork with black pepper",
     [("pork", .50), ("onion", .15), ("bell_pepper", .10), ("garlic", .04), ("oyster_sauce", .06),
      ("soy_sauce", .02), ("SUGAR", .01), ("OIL", .07), ("WATER", .05)]),
    (90014, "10", "ปลานึ่งซีอิ๊ว", "Steamed fish with soy sauce",
     [("seabass_steamed", .62), ("soy_sauce", .06), ("shiitake", .06), ("ginger", .04), ("SUGAR", .01),
      ("OIL", .01), ("WATER", .20)]),
    (90015, "11", "ผัดแขนง", "Stir-fried kale sprouts with oyster sauce",
     [("kale_sprout", .76), ("OIL", .07), ("oyster_sauce", .06), ("garlic", .04), ("fish_sauce", .01),
      ("SUGAR", .01), ("WATER", .05)]),
    (90016, "12", "ไข่กระทะ", "Pan-fried egg with minced pork and sausage (Khai Krata)",
     [("egg", .55), ("pork", .12), ("sausage_fried", .12), ("onion", .08), ("OIL", .05),
      ("soy_sauce", .02), ("WATER", .06)]),
    (90017, "17", "หมูฮ้อง", "Braised pork belly (Mu Hong)",
     [("pork_belly", .58), ("soy_sauce", .05), ("dark_soy", .03), ("SUGAR", .05), ("garlic", .04),
      ("WATER", .25)]),
    (90018, "22", "ข้าวแช่", "Rice with iced jasmine water and side dishes (Khao Chae)",
     [("RICE", .40), ("WATER", .25), ("kapi", .03), ("shredded_pork", .08), ("shallot", .05),
      ("snakehead", .05), ("egg", .04), ("OIL", .05), ("SUGAR", .03), ("bell_pepper", .02)]),
    (90019, "24", "ปลาหมึกทอด", "Deep-fried battered squid",
     [("squid", .65), ("wheat_flour", .14), ("egg", .04), ("OIL", .14), ("WATER", .03)]),
    (90020, "27", "ปลานึ่งมะนาว", "Steamed fish with lime and chili",
     [("seabass_steamed", .60), ("lime", .08), ("fish_sauce", .04), ("garlic", .05), ("bird_chili", .03),
      ("SUGAR", .03), ("celery", .02), ("WATER", .15)]),
    (90021, "34", "ผัดผักบุ้งไฟแดง", "Stir-fried morning glory",
     [("morning_glory", .76), ("OIL", .07), ("oyster_sauce", .05), ("soy_sauce", .02), ("garlic", .04),
      ("bird_chili", .01), ("SUGAR", .01), ("WATER", .04)]),
    (90022, "40", "ผัดพริกสด", "Stir-fried pork with fresh chili",
     [("pork", .45), ("chili", .15), ("onion", .12), ("garlic", .03), ("oyster_sauce", .05),
      ("fish_sauce", .02), ("SUGAR", .02), ("OIL", .07), ("WATER", .09)]),
    (90023, "47", "ผัดกะปิ", "Stir-fried pork and long beans with shrimp paste",
     [("pork", .40), ("long_bean", .20), ("kapi", .06), ("shallot", .06), ("garlic", .03),
      ("bird_chili", .02), ("SUGAR", .04), ("OIL", .07), ("WATER", .12)]),
    (90024, "49", "ยำปลาดุกฟู", "Crispy catfish salad with green mango",
     [("catfish_fried", .38), ("OIL", .10), ("green_mango", .25), ("shallot", .06), ("peanut", .05),
      ("fish_sauce", .04), ("SUGAR", .05), ("lime", .05), ("bird_chili", .02)]),
    (90025, "60", "คั่วพริกเกลือ", "Fried pork belly with chili and salt",
     [("pork_belly_fried", .70), ("garlic", .10), ("bird_chili", .04), ("dried_chili", .01),
      ("OIL", .08), ("fish_sauce", .02), ("SUGAR", .01), ("WATER", .04)]),
    (90026, "64", "ปลาหมึกนึ่งมะนาว", "Steamed squid with lime and chili",
     [("squid", .60), ("lime", .08), ("fish_sauce", .05), ("garlic", .06), ("bird_chili", .03),
      ("SUGAR", .03), ("celery", .02), ("WATER", .13)]),
    (90027, "76", "ปูผัดผงกะหรี่", "Stir-fried crab with curry powder",
     [("crab", .35), ("egg", .15), ("evap_milk", .08), ("onion", .10), ("celery", .05),
      ("bell_pepper", .03), ("curry_powder", .02), ("oyster_sauce", .04), ("SUGAR", .02),
      ("OIL", .08), ("WATER", .08)]),
]

new_rows = []
for fid, d, th, en, parts in RECIPES:
    row = {"food_id": fid, "food_name_th": th, "food_name_en": en, "food_type": "dish"}
    row.update(blend(parts))
    row["potassium_estimated"] = False
    row["phosphorus_estimated"] = False
    row["mineral_source"] = ("recipe (Entry 25): " +
                             " + ".join(f"{n} {int(round(f * 100))}%" for n, f in parts))
    new_rows.append(row)

out = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
sr = compute_sugar_risk(out)
mask900 = out.food_id.between(90000, 90099)
out.loc[mask900, "sugar_risk"] = sr[mask900]
out["sugar_risk"] = out["sugar_risk"].astype(int)
out = out[pd.read_csv(CSV, nrows=0).columns.tolist() if "mineral_source" in pd.read_csv(CSV, nrows=0).columns
          else out.columns]
out.to_csv(CSV, index=False)

show = out[out.food_id.between(90010, 90099)]
for r in show.itertuples():
    atw = r.protein_g * 4 + r.fat_g * 9 + r.carb_available_g * 4
    print(f"{r.food_id} {r.food_name_th:<24} {r.energy_kcal:6.0f} kcal (Atwater {atw:5.0f}) "
          f"P{r.protein_g:5.1f} F{r.fat_g:5.1f} C{r.carb_available_g:5.1f} "
          f"Na{r.sodium_mg:6.0f} K{r.potassium_mg:5.0f} Ph{r.phosphorus_mg:5.0f} sugar_risk={r.sugar_risk}")
print(f"\nเพิ่ม {len(show)} แถว → รวม {len(out)} แถว")
