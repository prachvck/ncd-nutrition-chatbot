"""
scripts/fix_calforlife_zeros.py  — DEV_LOG Entry 26

calforlife.com (แถว food_id 22000-22999) ใส่ 0 แทน "ไม่มีข้อมูล" ใน
sodium_mg / potassium_mg / phosphorus_mg / calcium_mg (ยืนยันจาก
calforlife_foods_raw.csv: แถวที่เว็บไม่แสดงแร่ธาตุ จะเป็น 0.0 ทั้งชุด) เช่น
"เกาเหลาเนื้อ K=0", "บะหมี่แห้งหมู Na=0" ซึ่งเป็นไปไม่ได้ — ค่า 0 ปลอมทำให้
จานผ่านเพดานโซเดียม/โพแทสเซียมได้ทุกกรณี (อันตรายกับผู้ป่วยความดัน/หัวใจ/ไต)

สคริปต์นี้แปลง 0 พวกนี้เป็น NaN (= ไม่มีข้อมูล) แล้วให้ pipeline จัดการ
แบบ fail-safe แทน (ดู _hard_filter: โรคที่ต้องคุมโซเดียม/แร่ธาตุจะไม่ได้รับ
แนะนำจานที่ไม่มีข้อมูลตัวนั้น)

รัน (จาก root chabot/): python scripts/fix_calforlife_zeros.py   (รันซ้ำได้)
"""
import pandas as pd

CSV = "foods_master_v2.csv"
COLS = ["sodium_mg", "potassium_mg", "phosphorus_mg", "calcium_mg"]

df = pd.read_csv(CSV)
cal = (df.food_id // 1000) == 22
summary = {}
for c in COLS:
    hit = cal & (df[c] == 0)
    summary[c] = int(hit.sum())
    df.loc[hit, c] = pd.NA
    flag = c.replace("_mg", "") + "_estimated"
    if flag in df.columns:
        df.loc[hit, flag] = False   # ไม่ใช่ค่าประมาณ แต่ "ไม่มีข้อมูล"
df.to_csv(CSV, index=False)
print("แปลง 0 ปลอม → NaN (เฉพาะแถว calforlife):", summary)
