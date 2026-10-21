"""
scripts/fix_noodle_dishes.py — DEV_LOG Entry 59

ตรวจกลุ่มก๋วยเตี๋ยว/เส้น (114 จาน) แล้วแก้แถวที่ "ประเภท" ผิด (ไม่แตะค่าโภชนาการที่วัดจริง):
  - บะหมี่ผักโมโรเฮยะ 3 แถว (22661, 22646, 22332) และบะหมี่เย็น (22535): ค่าต่อ 100 g เป็นของ
    "เส้นแห้ง/ผลิตภัณฑ์" (320-336 kcal, คาร์บ 56-74 g, ไม่มีค่าน้ำ) ไม่ใช่ชามที่ปรุงเสร็จ → ingredient
    (เดิมเป็น dish → ระบบคิด 1 ชาม 400 g = 1,076-1,344 kcal)
  - 11221 ผัดยากิโซบะ (เจ): ชื่ออังกฤษผิดเป็น "preserved bamboo soup" → ระบบจัดเป็นแกง + บวกข้าว
    แก้ชื่ออังกฤษ
ขนาดต่อจานของกลุ่มเส้น (แห้ง/ผัด/ขนมจีน/หมี่กรอบ) แก้ที่กฎ SERVING_MAP_TH ใน ml/pipeline.py

รัน (จาก root chabot/): python scripts/fix_noodle_dishes.py — รันซ้ำได้
"""
import pandas as pd

CSV = "foods_master_v2.csv"
df = pd.read_csv(CSV, dtype=str, keep_default_na=False)
bom = open(CSV, "rb").read(3) == b"\xef\xbb\xbf"

TO_INGREDIENT = {22661, 22646, 22332, 22535}
EN_FIX = {11221: "Vegetarian stir-fried yakisoba noodles"}

fid = df["food_id"].astype(int)
for i in df.index[fid.isin(TO_INGREDIENT)]:
    if df.at[i, "food_type"] != "ingredient":
        print(f"  {df.at[i, 'food_id']} {df.at[i, 'food_name_th']}: food_type dish → ingredient")
        df.at[i, "food_type"] = "ingredient"
for f, en in EN_FIX.items():
    i = df.index[fid == f][0]
    if df.at[i, "food_name_en"] != en:
        print(f"  {f} {df.at[i, 'food_name_th']}: food_name_en '{df.at[i, 'food_name_en']}' → '{en}'")
        df.at[i, "food_name_en"] = en
df.to_csv(CSV, index=False, encoding="utf-8-sig" if bom else "utf-8")
print("done")
