"""
scripts/add_cnn_near_dishes.py — DEV_LOG Entry 58

ทำให้ 100 label ของ CNN (THFOOD-100) มีข้อมูลโภชนาการของ "จานนั้นจริง" ครบ — เดิม 10 label
map ไปเมนูใกล้เคียง (สถานะ "ใกล้เคียง" ใน cnn_label_food_mapping.csv):
  - ก๋วยเตี๋ยวเรือ (14): ผู้ใช้กำหนด ก๋วยเตี๋ยวเรือ = ก๋วยเตี๋ยวน้ำตก → ใช้ 11016 "ก๋วยเตี๋ยวเส้นเล็ก,
    หมู, น้ำตก" (Thai FCD ค่าวัดจริง) เป็นจานเดียวกัน + ชื่อเรียกอื่นใน food_aliases.csv
  - อีก 9 label: สร้างแถวใหม่ food_id 90100-90108 จากสูตรอาหาร (วิธีเดียวกับ Entry 20/25 —
    ถ่วงน้ำหนักวัตถุดิบที่มีค่าวัดจริงในฐาน ต่อ 100 g อาหารปรุงเสร็จ)

กติกา (เหมือน add_cnn_missing_dishes.py):
  - K/P ที่เป็นค่าประมาณ (flag *_estimated) และ 0 ปลอมจาก calforlife = ไม่มีข้อมูล
  - สารอาหารที่วัตถุดิบ < 50% โดยน้ำหนักไม่มีข้อมูล → NaN (ระบบ fail-safe จะไม่แนะนำให้ผู้ป่วยไต)
  - หอยนางรมสดไม่มีในฐานไทย → ใช้ USDA FoodData Central SR Legacy
    "Mollusks, oyster, Pacific, raw" (ต่อ 100 g)

ใช้ช่วง food_id 90100-90199 (add_cnn_missing_dishes.py ลบ/สร้างใหม่เฉพาะ 90010-90099 จึงไม่ชนกัน)
รัน (จาก root chabot/): python scripts/add_cnn_near_dishes.py   — รันซ้ำได้
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.compute_sugar_risk import compute_sugar_risk  # noqa: E402

CSV = "foods_master_v2.csv"
MAPPING = "cnn_label_food_mapping.csv"
ALIASES = "food_aliases.csv"
LO, HI = 90100, 90199
NUM = ["energy_kcal", "water_g", "protein_g", "fat_g", "carb_available_g",
       "dietary_fiber_g", "ash_g", "calcium_mg", "phosphorus_mg", "magnesium_mg",
       "sodium_mg", "potassium_mg", "iron_mg", "copper_mg", "zinc_mg", "iodine_ug",
       "betacarotene_ug", "retinol_ug", "vitamin_a_rae_ug", "thiamin_mg",
       "riboflavin_mg", "niacin_mg", "vitamin_c_mg", "vitamin_e_mg"]

cols = pd.read_csv(CSV, nrows=0).columns.tolist()
df = pd.read_csv(CSV)
df = df[~df.food_id.between(LO, HI)].reset_index(drop=True)
idx = df.set_index("food_id")


def pseudo(**kw):
    s = pd.Series(0.0, index=NUM)
    for k, v in kw.items():
        s[k] = v
    return s


WATER = pseudo(water_g=100)
OIL = pseudo(energy_kcal=884, fat_g=100)
SUGAR = pseudo(energy_kcal=387, carb_available_g=100, sodium_mg=1, potassium_mg=2)
# USDA FoodData Central, SR Legacy: Mollusks, oyster, Pacific, raw (ต่อ 100 g) — ค่าที่ไม่ระบุ = NaN
OYSTER = pd.Series(np.nan, index=NUM)
for k, v in dict(energy_kcal=81, water_g=82.06, protein_g=9.45, fat_g=2.30, carb_available_g=4.95,
                 calcium_mg=8, magnesium_mg=22, phosphorus_mg=162, potassium_mg=168, sodium_mg=106,
                 iron_mg=5.11, zinc_mg=16.62, dietary_fiber_g=0).items():
    OYSTER[k] = v


def db(fid):
    r = idx.loc[fid]
    s = r[NUM].astype(float).copy()
    if str(r.get("potassium_estimated", False)).lower() in ("true", "1"):
        s["potassium_mg"] = np.nan
    if str(r.get("phosphorus_estimated", False)).lower() in ("true", "1"):
        s["phosphorus_mg"] = np.nan
    if fid // 1000 == 22:
        for c in ("sodium_mg", "potassium_mg", "phosphorus_mg", "calcium_mg"):
            if s[c] == 0:
                s[c] = np.nan
    return s


def shrimp():
    """กุ้ง: กุ้งแชบ๊วยต้ม (K/P วัดจริง) เติมช่องที่ขาดด้วยกุ้งกุลาดำแช่แข็ง (Na วัดจริง) และกุลาดำสด"""
    return db(20862).combine_first(db(20859)).combine_first(db(20855))


I = {
    "flour": 21839, "egg": 21095, "glass_noodle": 20174, "cabbage": 20188, "carrot": 20208,
    "pork_minced": 20783, "pork_minced_boiled": 20784, "pork_liver_boiled": 20768,
    "crispy_pork": 20795, "kale": 20270, "egg_tofu": 21119, "spring_onion": 20215,
    "coriander": 20277, "coriander_root": 21233, "soy_sauce": 21268, "fish_sauce": 21284,
    "oyster_sauce": 21264, "garlic": 21221, "shallot": 21245, "bird_chili": 20324,
    "chili": 20327, "dried_chili": 21239, "lime": 21966, "mint": 21244, "krachai": 21219,
    "holy_basil": 21891, "seabass": 20876, "squid": 20959, "glutinous_rice_raw": 21779,
    "pad_thai": 21427,
}


def ing(name):
    special = {"WATER": WATER, "OIL": OIL, "SUGAR": SUGAR, "OYSTER": OYSTER}
    if name in special:
        return special[name]
    if name == "shrimp":
        return shrimp()
    return db(I[name])


def blend(parts):
    total = sum(f for _, f in parts)
    assert abs(total - 1.0) < 1e-6, f"สัดส่วนรวม {total}"
    out = {}
    for c in NUM:
        num = w = 0.0
        for name, f in parts:
            v = ing(name)[c]
            if pd.notna(v):
                num += f * v
                w += f
        out[c] = round(num / w, 2) if w >= 0.5 else np.nan
    return out


# (food_id, label dir, ชื่อไทย, ชื่ออังกฤษ, สูตร)
RECIPES = [
    (90100, "02", "ปอเปี๊ยะทอด", "Po Pia Thot, deep-fried spring rolls with glass noodles and pork",
     [("flour", .18), ("WATER", .07), ("glass_noodle", .20), ("cabbage", .17), ("carrot", .08),
      ("pork_minced", .10), ("OIL", .12), ("soy_sauce", .03), ("oyster_sauce", .03), ("garlic", .02)]),
    (90101, "13", "แกงจืดเต้าหู้หมูสับ", "Clear soup with egg tofu and minced pork (Kaeng Chued)",
     [("WATER", .61), ("egg_tofu", .15), ("pork_minced_boiled", .10), ("cabbage", .08),
      ("fish_sauce", .015), ("soy_sauce", .015), ("garlic", .01), ("spring_onion", .01), ("coriander", .01)]),
    (90102, "19", "ผัดไทยห่อไข่", "Phat Thai Ho Khai, pad thai wrapped in egg omelette",
     [("pad_thai", .75), ("egg", .20), ("OIL", .05)]),
    (90103, "26", "ผัดคะน้าหมูกรอบ", "Stir-fried Chinese kale with crispy pork (Phat Kana)",
     [("kale", .55), ("crispy_pork", .15), ("oyster_sauce", .05), ("OIL", .06), ("garlic", .03),
      ("soy_sauce", .02), ("SUGAR", .01), ("bird_chili", .01), ("WATER", .12)]),
    (90104, "32", "เกี๊ยวทอด", "Kiao Thot, deep-fried pork wontons",
     [("flour", .35), ("egg", .05), ("WATER", .12), ("pork_minced", .25), ("OIL", .18),
      ("soy_sauce", .02), ("garlic", .02), ("coriander_root", .01)]),
    (90105, "38", "กุ้งทอด", "Kung Thot, deep-fried battered shrimp",
     [("shrimp", .65), ("flour", .12), ("egg", .04), ("OIL", .14), ("WATER", .03),
      ("fish_sauce", .01), ("garlic", .01)]),
    (90106, "70", "หอยนางรมสด", "Hoi Nangrom, raw oysters with seafood dipping sauce and shallots",
     [("OYSTER", .80), ("fish_sauce", .03), ("lime", .04), ("garlic", .02), ("bird_chili", .01),
      ("SUGAR", .02), ("shallot", .04), ("OIL", .02), ("WATER", .02)]),
    (90107, "79", "ผัดฉ่าทะเล", "Phat Cha, spicy stir-fried seafood with wild ginger and holy basil",
     [("seabass", .45), ("squid", .15), ("krachai", .06), ("holy_basil", .03), ("chili", .04),
      ("garlic", .03), ("oyster_sauce", .04), ("fish_sauce", .02), ("SUGAR", .01), ("OIL", .08),
      ("WATER", .09)]),
    (90108, "88", "ลาบหมู", "Lap Mu, spicy minced pork salad with toasted rice",
     [("pork_minced_boiled", .55), ("pork_liver_boiled", .05), ("shallot", .08),
      ("glutinous_rice_raw", .04), ("fish_sauce", .03), ("lime", .05), ("dried_chili", .01),
      ("mint", .03), ("spring_onion", .03), ("coriander", .02), ("WATER", .11)]),
]

rows = []
for fid, _, th, en, parts in RECIPES:
    r = {"food_id": fid, "food_name_th": th, "food_name_en": en, "food_type": "dish"}
    r.update(blend(parts))
    r["potassium_estimated"] = False
    r["phosphorus_estimated"] = False
    src = " + ".join(f"{n} {round(f * 100, 1):g}%" for n, f in parts)
    if any(n == "OYSTER" for n, _ in parts):
        src += " | OYSTER = USDA FDC SR Legacy 'Mollusks, oyster, Pacific, raw'"
    r["mineral_source"] = "recipe (Entry 58): " + src
    rows.append(r)

out = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
sr = compute_sugar_risk(out)
m = out.food_id.between(LO, HI)
out.loc[m, "sugar_risk"] = sr[m]
out["sugar_risk"] = out["sugar_risk"].astype(int)
out = out[cols]
out.to_csv(CSV, index=False)

# ── อัปเดตสัญญา CNN label → food_id ──────────────────────────────────────
mp = pd.read_csv(MAPPING, dtype=str, encoding="utf-8-sig")
new = out.set_index("food_id")
for fid, d, th, *_ in RECIPES:
    i = mp.index[mp.Directory_Name == d][0]
    mp.loc[i, ["status", "food_id", "db_food_name_th", "food_type", "energy_kcal_per100g", "note"]] = [
        "ตรง", str(fid), th, "dish", f"{new.loc[fid, 'energy_kcal']:g}", "สูตรอาหาร (Entry 58)"]
i = mp.index[mp.Directory_Name == "14"][0]
mp.loc[i, ["status", "note"]] = ["ตรง", "ก๋วยเตี๋ยวเรือ = ก๋วยเตี๋ยวน้ำตก (ผู้ใช้กำหนด, Entry 58)"]
mp.to_csv(MAPPING, index=False, encoding="utf-8-sig")

# ── ชื่อเรียกอื่น (search_food ใช้ก่อนค้นด้วยชื่อ) ──────────────────────────
aliases = pd.DataFrame([
    ("ก๋วยเตี๋ยวเรือ", 11016, "ผู้ใช้กำหนด: ก๋วยเตี๋ยวเรือ = ก๋วยเตี๋ยวน้ำตก"),
    ("ก๋วยเตี๋ยวน้ำตก", 11016, "ผู้ใช้กำหนด: ก๋วยเตี๋ยวเรือ = ก๋วยเตี๋ยวน้ำตก"),
    ("ก๋วยเตี๋ยวเรือหมู", 11016, "ผู้ใช้กำหนด: ก๋วยเตี๋ยวเรือ = ก๋วยเตี๋ยวน้ำตก"),
    ("แกงจืด", 90101, "label CNN 13 — แกงจืดทั่วไป = เต้าหู้หมูสับ"),
    ("ผัดคะน้า", 90103, "label CNN 26"),
    ("ผัดฉ่า", 90107, "label CNN 79"),
    ("ลาบ", 90108, "label CNN 88 — ลาบอีสานทั่วไป = ลาบหมู"),
    ("หอยนางรม", 90106, "label CNN 70 — หอยนางรมสด"),
], columns=["alias", "food_id", "note"])
aliases.to_csv(ALIASES, index=False, encoding="utf-8-sig")

print(f"เพิ่ม {len(rows)} แถว → รวม {len(out)} แถว")
for r in out[m].itertuples():
    atw = r.protein_g * 4 + r.fat_g * 9 + r.carb_available_g * 4
    print(f"{r.food_id} {r.food_name_th:<20} {r.energy_kcal:6.0f} kcal (Atwater {atw:5.0f}) "
          f"P{r.protein_g:5.1f} F{r.fat_g:5.1f} C{r.carb_available_g:5.1f} Na{r.sodium_mg:6.0f} "
          f"K{r.potassium_mg:6.0f} Ph{r.phosphorus_mg:6.0f} sugar_risk={r.sugar_risk}")
print("\nสถานะ mapping:", mp.status.value_counts().to_dict())
