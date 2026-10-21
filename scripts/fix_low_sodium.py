"""
scripts/fix_low_sodium.py  — DEV_LOG Entry 37

แก้ค่าโซเดียมที่ต่ำผิดปกติของจานคาวที่ปรุงด้วยน้ำปลา/ซีอิ๊ว/กะปิ/พริกแกง
(เช่น แกงเลียง 3 mg/100g, แกงเหลืองสายบัว 58, หมูย่าง 55, เนื้อเป็ดเจ 53) —
จานพวกนี้ถูกแนะนำให้ผู้ป่วยความดัน/หัวใจ/ไตเพราะ "ดูเหมือนเค็มน้อย"

วิธีหา: ไล่ dish คาว (ไม่ใช่ขนม/ของหวาน) ที่ Na < 120 mg/100g แล้วคัดด้วยมือ
- ไม่แก้: เนื้อสัตว์สุกไม่ปรุงรส (อกไก่, สเต็ก, หมูต้ม ฯลฯ — ค่าต่ำจริง), สลัดผัก,
  ขนม, และค่าที่ 2 แหล่งข้อมูลตรงกัน (ก๋วยเตี๋ยวหมี่หมูตุ๋นแห้ง ~106)
- แก้ 14 จาน ด้วย sibling (เมนูเดียวกัน/ใกล้เคียงที่มีค่าวัดจริง — ใช้ค่าตรงๆ
  ไม่ปรับตามพลังงาน เพราะความเค็มของน้ำแกง/น้ำซุปมาจากเครื่องปรุง ไม่ใช่เนื้อ)
  หรือสูตร (วัตถุดิบหลักในสัดส่วนสูตรทั่วไป + เครื่องปรุงที่มีค่าวัดจริงใน DB)

รัน (จาก root chabot/): python scripts/fix_low_sodium.py   (รันซ้ำได้)
"""
import pandas as pd

CSV = "foods_master_v2.csv"
df = pd.read_csv(CSV)
idx = df.set_index("food_id")
Na = lambda fid: float(idx.loc[fid, "sodium_mg"])

FISH_SAUCE, SOY, DARK_SOY, OYSTER, KAPI = Na(21284), Na(21268), Na(21271), Na(21264), Na(21250)
SALTED_EGG, EGG, SQUID, PORK, CHICKEN = Na(21098), Na(21095), Na(20959), Na(20771), Na(20708)
SALT = 38758          # เกลือป่น (NaCl ~39.3% Na) mg/100g
SHRIMP_USDA = 119     # USDA 15270 Crustaceans, shrimp, raw (K/P ไม่ใช้ตรงนี้)
SALMON_USDA = 44      # USDA 15076 Fish, salmon, Atlantic, wild, raw
OKRA_USDA = 7         # USDA 11278 Okra, raw

FIX = {
    11101: (.02 * KAPI + .02 * FISH_SAUCE + .08 * SHRIMP_USDA,
            "recipe: ผัก 75% + กุ้ง 8% + กะปิ 2% + น้ำปลา 2% (เดิม 3 mg)"),
    11246: (891.7 / 2.41,
            "USDA FDC 174807 Soup, egg drop (891.7mg/241g)"),
    11238: (.41 * SHRIMP_USDA + .04 * FISH_SAUCE,
            "recipe: กุ้ง 41% + น้ำปลา 4% ในซอสมะขาม"),
    22582: (.50 * SQUID + .10 * SALTED_EGG + .04 * OYSTER,
            "recipe: ปลาหมึก 50% + ไข่เค็ม 10% + ซอสหอยนางรม 4%"),
    22600: (.99 * SALMON_USDA + .008 * SALT,
            "recipe: แซลมอน (USDA) + เกลือ 0.8%"),
    11217: (.04 * SOY + .02 * DARK_SOY + .02 * OYSTER,
            "recipe: กลูเตนตุ๋นซีอิ๊ว 4% + ซีอิ๊วดำ 2% + ซอสหอยนางรม 2%"),
    22345: (.60 * OKRA_USDA + .32 * EGG + .05 * OYSTER + .01 * FISH_SAUCE,
            "recipe: กระเจี๊ยบ 60% + ไข่ 32% + ซอสหอยนางรม 5% + น้ำปลา 1%"),
    22662: (.90 * PORK + .03 * SOY + .02 * FISH_SAUCE,
            "recipe: หมู 90% หมักซีอิ๊ว 3% + น้ำปลา 2%"),
    22244: ((Na(11158) + Na(21377)) / 2,
            "sibling: แกงเหลืองใส่ปลา(11158) + แกงเหลืองไก่(21377)"),
    11241: (Na(11242), "sibling: เกาเหลาเนื้อ(11242)"),
    22403: (Na(11149), "sibling: ห่อหมกปลาช่อน(11149)"),
    22241: (.15 * PORK + .04 * FISH_SAUCE,
            "recipe: มะเขือยาว 65% + หมู/กุ้ง 15% + น้ำปลา 4% (น้ำยำ)"),
    11250: (Na(11088) * ((6.5 / 7.94) + (76.25 / 174)) / 2,
            "sibling: ข้าวหมูอบ(11088) ปรับตามโปรตีน/kcal (จานข้าวเจือจางด้วยข้าว)"),
    11057: (Na(11058) * ((5.06 / 8.15) + (210 / 236)) / 2,
            "sibling: ข้าวราดไข่เจียวหมูสับ(11058) ปรับตามโปรตีน/kcal"),
}

if "mineral_source" not in df.columns:
    df["mineral_source"] = pd.NA
for fid, (val, note) in FIX.items():
    i = df.index[df.food_id == fid]
    if not len(i):
        continue
    i = i[0]
    old = df.at[i, "sodium_mg"]
    if pd.notna(old) and old >= 120:      # แก้ไปแล้ว — ข้าม (รันซ้ำได้)
        continue
    df.at[i, "sodium_mg"] = round(val, 1)
    prev = df.at[i, "mineral_source"]
    tag = f"Na (Entry 37) {old}→{round(val)}: {note}"
    df.at[i, "mineral_source"] = tag if pd.isna(prev) else f"{prev} | {tag}"
    print(f"{fid} {df.at[i, 'food_name_th']:<28} Na {old} → {val:.0f}  ({note})")

df.to_csv(CSV, index=False)
