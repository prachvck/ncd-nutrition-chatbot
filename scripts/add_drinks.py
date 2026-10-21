"""
scripts/add_drinks.py — DEV_LOG Entry 70

เพิ่มเครื่องดื่มไทยยอดนิยมที่ไม่มีในฐานข้อมูล (ทดสอบจริง: "ชาไทย" ค้นไม่เจอ / ได้โยเกิร์ต)
ด้วยวิธีเดียวกับ scripts/add_cnn_missing_dishes.py (Entry 25): ผสมวัตถุดิบที่มีค่าวัดจริง
ใน foods_master_v2.csv ถ่วงน้ำหนักตามสูตรมาตรฐานต่อ 1 แก้ว แล้วคิดเป็นค่าต่อ 100 g

วัตถุดิบ (Thai FCD / ฐานเดิม):
  นมข้นหวาน 21123 · นมข้นจืด (นมระเหย) 21813 · นมพาสเจอร์ไรส์รสธรรมชาติ 21156
  ชาที่ชงแล้ว ใช้ "ชาเขียว" 22603 (ชาชง ~2 kcal/100 g) · กาแฟดำ 21931
  น้ำตาลทราย = ค่ามาตรฐาน 387 kcal/100 g (USDA sucrose) · น้ำแข็ง = น้ำ
สูตรต่อแก้ว (~16 oz มีน้ำแข็ง) อ้างอิงสูตรร้านทั่วไป: นมข้นหวาน 2 ช้อนโต๊ะ (~30 g), นมข้นจืด 2 ช้อนโต๊ะ (~30 g),
น้ำตาล 1 ช้อนโต๊ะ (~15 g) — ตรวจเทียบ: กรมอนามัยระบุชาไทยเย็น 1 แก้วมีน้ำตาล ~53 g (~13 ช้อนชา)
ขึ้นกับสูตรร้าน → สูตรนี้ (~35 g น้ำตาล) อยู่ช่วงล่าง-กลาง; รุ่น "หวานน้อย" ตามคำแนะนำกรมอนามัย
(น้ำตาลเพิ่มไม่เกิน 2 ช้อนชา)

รัน (จาก root chabot/): python scripts/add_drinks.py
รันซ้ำได้ — ลบ food_id 90200-90299 แล้วสร้างใหม่ทุกครั้ง · แล้วรัน import_foods.py --prune
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
df = df[~df.food_id.between(90200, 90299)].reset_index(drop=True)
idx = df.set_index("food_id")


def pseudo(**kw):
    s = pd.Series(0.0, index=NUM)
    for k, v in kw.items():
        s[k] = v
    return s


WATER = pseudo(water_g=100)                       # น้ำแข็ง
SUGAR = pseudo(energy_kcal=387, carb_available_g=100, sodium_mg=1, potassium_mg=2)


def db(fid):
    r = idx.loc[fid]
    s = r[NUM].astype(float).copy()
    if bool(r.get("potassium_estimated", False)):
        s["potassium_mg"] = np.nan
    if bool(r.get("phosphorus_estimated", False)):
        s["phosphorus_mg"] = np.nan
    if fid // 1000 == 22:                          # calforlife ใส่ 0 เมื่อไม่มีข้อมูล
        for c in ("sodium_mg", "potassium_mg", "phosphorus_mg", "calcium_mg"):
            if s[c] == 0:
                s[c] = np.nan
    return s


I = {"scm": 21123, "evap": 21813, "milk": 21156, "tea": 22603, "coffee": 21931}


def ing(name):
    if name == "ICE": return WATER
    if name == "SUGAR": return SUGAR
    return db(I[name])


def blend(parts_g):
    """parts_g = [(วัตถุดิบ, กรัมต่อแก้ว)] → (ค่าต่อ 100 g, น้ำหนักทั้งแก้ว)"""
    total = sum(g for _, g in parts_g)
    out = {}
    for c in NUM:
        num = w = 0.0
        for name, g in parts_g:
            v = ing(name)[c]
            if pd.notna(v):
                num += g / total * v
                w += g / total
        out[c] = round(num / w, 2) if w >= 0.5 else np.nan
    return out, total


# (food_id, ชื่อไทย, ชื่ออังกฤษ, สูตรกรัมต่อแก้ว, คำอธิบายสูตร)
DRINKS = [
    (90200, "ชาไทยเย็น", "Thai iced milk tea",
     [("tea", 150), ("scm", 30), ("evap", 30), ("SUGAR", 15), ("ICE", 100)],
     "ชา 150 + นมข้นหวาน 30 + นมข้นจืด 30 + น้ำตาล 15 + น้ำแข็ง 100 g"),
    (90201, "ชาไทยเย็น หวานน้อย", "Thai iced milk tea, less sweet",
     [("tea", 150), ("scm", 15), ("evap", 30), ("SUGAR", 5), ("ICE", 100)],
     "ชา 150 + นมข้นหวาน 15 + นมข้นจืด 30 + น้ำตาล 5 + น้ำแข็ง 100 g"),
    (90202, "ชาดำเย็น", "Thai iced black tea, sweetened",
     [("tea", 200), ("SUGAR", 25), ("ICE", 100)],
     "ชา 200 + น้ำตาล 25 + น้ำแข็ง 100 g"),
    (90203, "ชาเขียวนมเย็น", "Iced green milk tea",
     [("tea", 150), ("scm", 30), ("evap", 30), ("SUGAR", 15), ("ICE", 100)],
     "ชาเขียว 150 + นมข้นหวาน 30 + นมข้นจืด 30 + น้ำตาล 15 + น้ำแข็ง 100 g"),
    (90204, "กาแฟเย็น", "Thai iced coffee with milk (kafae yen)",
     [("coffee", 150), ("scm", 30), ("evap", 30), ("SUGAR", 15), ("ICE", 100)],
     "กาแฟ 150 + นมข้นหวาน 30 + นมข้นจืด 30 + น้ำตาล 15 + น้ำแข็ง 100 g"),
    (90205, "กาแฟเย็น หวานน้อย", "Thai iced coffee with milk, less sweet",
     [("coffee", 150), ("scm", 15), ("evap", 30), ("SUGAR", 5), ("ICE", 100)],
     "กาแฟ 150 + นมข้นหวาน 15 + นมข้นจืด 30 + น้ำตาล 5 + น้ำแข็ง 100 g"),
    (90206, "โอเลี้ยง", "Thai iced black coffee, sweetened (oliang)",
     [("coffee", 200), ("SUGAR", 25), ("ICE", 100)],
     "กาแฟ 200 + น้ำตาล 25 + น้ำแข็ง 100 g"),
    (90207, "นมเย็น", "Thai iced pink milk (nom yen)",
     [("milk", 150), ("SUGAR", 20), ("scm", 20), ("ICE", 100)],
     "นมสด 150 + น้ำแดง (คิดเป็นน้ำตาล) 20 + นมข้นหวาน 20 + น้ำแข็ง 100 g"),
]

ALIASES = {
    90200: ["ชาไทย", "ชาเย็น", "ชานมเย็น", "ชาไทยนม", "ชาไทยเย็น"],
    90201: ["ชาเย็นหวานน้อย", "ชาไทยหวานน้อย"],
    90202: ["ชาดำ", "ชาดำเย็น", "ชาดำหวาน"],
    90203: ["ชาเขียวเย็น", "ชาเขียวนม", "ชาเขียวนมเย็น"],
    90204: ["กาแฟเย็น", "กาแฟโบราณ", "กาแฟนมเย็น", "กาแฟเย็นนม"],
    90205: ["กาแฟเย็นหวานน้อย"],
    90206: ["โอเลี้ยง", "กาแฟดำเย็น"],
    90207: ["นมเย็น", "นมชมพู", "นมแดง"],
}

rows, servings = [], {}
for fid, th, en, parts, note in DRINKS:
    vals, total = blend(parts)
    row = {"food_id": fid, "food_name_th": th, "food_name_en": en, "food_type": "dish", **vals,
           "potassium_estimated": False, "phosphorus_estimated": False,
           "mineral_source": f"recipe (Entry 70): {note} — Thai FCD นมข้นหวาน 21123/นมข้นจืด 21813/"
                             f"นมสด 21156, ชา 22603, กาแฟ 21931, น้ำตาล USDA"}
    rows.append(row)
    servings[fid] = total

new = pd.DataFrame(rows)
out = pd.concat([df, new], ignore_index=True)
# sugar_risk แบบ quintile คำนวณทั้งฐาน — คงค่าเดิมของแถวอื่นไว้ (กันขอบ quintile ขยับจากการเพิ่ม 8 แถว)
sr = compute_sugar_risk(out)
is_new = out.food_id.between(90200, 90299)
out.loc[is_new, "sugar_risk"] = sr[is_new]
out["sugar_risk"] = out["sugar_risk"].astype(int)
out.to_csv(CSV, index=False, encoding="utf-8")

# aliases
ap = "food_aliases.csv"
al = pd.read_csv(ap, encoding="utf-8-sig")
al = al[~al.food_id.between(90200, 90299)]
add = pd.DataFrame([{"alias": a, "food_id": fid, "note": "Entry 70 เครื่องดื่ม"} for fid, names in ALIASES.items()
                    for a in names])
pd.concat([al, add], ignore_index=True).to_csv(ap, index=False, encoding="utf-8-sig")

print("เพิ่มเครื่องดื่ม", len(new), "รายการ · serving (g/แก้ว) สำหรับ SERVING_OVERRIDE_BY_ID:")
for fid, th, *_ in DRINKS:
    r = new[new.food_id == fid].iloc[0]
    g = servings[fid]
    print(f"  {fid}: ({g}, \"dessert_snack\"),  # {th}  → {r.energy_kcal * g / 100:.0f} kcal, "
          f"carb {r.carb_available_g * g / 100:.0f} g, Na {r.sodium_mg * g / 100:.0f} mg / แก้ว")
