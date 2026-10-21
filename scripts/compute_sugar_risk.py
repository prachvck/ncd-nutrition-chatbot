# -*- coding: utf-8 -*-
"""
scripts/compute_sugar_risk.py

[FIX — DEV_LOG Entry 17] เพิ่มคอลัมน์ sugar_risk (1-5, ยิ่งมากยิ่งไม่เหมาะกับ
เบาหวาน) ให้ foods_master.csv โดยไม่มีข้อมูล sugar_g จริงในแหล่งข้อมูลไหนเลย
(ยืนยันแล้วใน Entry ก่อนหน้าว่า sugar_risk เป็นคอลัมน์ตายในสคีมา DB ไม่เคย
ถูก populate จากแหล่งข้อมูลไหนเลย) เจ้าของโปรเจกต์ตัดสินใจให้ใช้ carb_
available_g เป็น proxy หลักแทน (จากที่คุยกันว่า "ไม่ค่อยมีข้อมูลน้ำตาล เลย
เลือกมองเรื่อง carb เยอะ/ไม่เหมาะสำหรับเบาหวาน")

วิธีคำนวณ (heuristic, ไม่ใช่ค่าจากแล็บจริง):
  1) carb_available_g ต่อ 100g -> quintile พื้นฐาน (1=carb น้อยสุด ของทั้ง
     dataset, 5=carb มากสุด)
  2) คำสำคัญในชื่ออาหาร (ไทย/อังกฤษ) สำหรับของหวาน/เครื่องดื่มหวาน/ผลไม้
     น้ำตาลสูง/น้ำเชื่อม -> บังคับ override เป็น 5 เสมอ แม้ carb quintile
     จะไม่ถึง 5 (เช่นไอศกรีมนมที่เจือจางจนคาร์บต่อ 100g ไม่สูงมาก แต่
     glycemic impact จริงสูงเพราะเป็นน้ำตาลอิสระ ไม่ใช่แป้งเชิงซ้อน)
  3) ยกเว้นการ override ถ้าชื่อบอกชัดว่าไม่หวาน/คีโต/เป็นน้ำมัน (เช่น
     "น้ำมัน, องุ่น" = grapeseed oil ไม่ใช่ผลไม้หวาน, "เค้กช็อคคีโต" =
     คีโตทำมาให้คาร์บ/น้ำตาลต่ำแล้ว) กรณีเหล่านี้ปล่อยให้ carb quintile
     ตัดสินตามจริงแทนที่จะบังคับ 5 ทับ

ข้อจำกัดที่รู้อยู่แล้ว: เป็น heuristic ล้วนๆ ไม่ใช่ค่าวัดจริง คำสำคัญอาจมี
false positive/negative หลุดบ้าง (ตรวจสอบด้วยมือแล้วรอบหนึ่งตอนพัฒนา พบ
และแก้ 2 กลุ่มปัญหา: (ก) EN "cake" ชนกับ "fish cake/rice cake" ที่เป็นของ
คาว แก้โดยใช้ "เค้ก" (ไทย) แทน "cake" (อังกฤษ) เพราะอาหารคาวมักไม่ใช้คำว่า
เค้กทับศัพท์ (ข) "ขนุน"/"พาย" เป็น substring ที่ชนกับคำอื่นได้ง่าย (แกงขนุน
อ่อน, ผักพาย) แก้ด้วยเงื่อนไขเพิ่มเติมหรือตัดออกจากลิสต์)

รัน: python scripts/compute_sugar_risk.py   (รันจาก root ของ chabot/)
ผลลัพธ์: สร้างไฟล์ foods_master_v2.csv (ไม่แก้ foods_master.csv เดิม)
"""
import pandas as pd

SRC = "data/intermediate/foods_master.csv"
OUT = "foods_master_v2.csv"

# คำสำคัญ "ของหวาน/เครื่องดื่มหวาน/ผลไม้น้ำตาลสูง" -> บังคับ sugar_risk = 5
# ตั้งใจไม่ใช้คำกว้างเกินไปอย่าง "ขนม" เฉยๆ เพราะจะชนกับ "ขนมจีน" (เส้น
# ก๋วยเตี๋ยว ไม่ใช่ของหวาน)
HIGH_SUGAR_KEYWORDS_TH = [
    "ทองหยิบ", "ทองหยอด", "ฝอยทอง", "บัวลอย", "ลอดช่อง", "เชื่อม",
    "ขนมหวาน", "ครองแครง", "ขนมเปียกปูน", "กล้วยบวชชี", "ข้าวเหนียวมูน",
    "สังขยา", "คัสตาร์ด", "เค้ก", "คุกกี้", "ไอศกรีม", "ลูกอม", "ทอฟฟี่",
    "ช็อกโกแลต", "แยม", "น้ำผึ้ง", "น้ำเชื่อม", "โดนัท", "พุดดิ้ง",
    "วุ้นหวาน", "ทองม้วน", "ข้าวเหนียวแดง", "หม้อแกง", "ตะโก้", "ซาหริ่ม",
    "น้ำอัดลม", "น้ำหวาน", "ชานมไข่มุก", "ชานม", "น้ำผลไม้กล่อง",
    # [Entry 70] เครื่องดื่มชง/เย็นใส่น้ำตาล (scripts/add_drinks.py)
    "ชาไทยเย็น", "ชาดำเย็น", "ชาเขียวนมเย็น", "กาแฟเย็น", "โอเลี้ยง", "นมเย็น",
    "ทุเรียน", "ลำไย", "องุ่น", "มะม่วงสุก", "กล้วยหอม", "ลิ้นจี่",
    "น้อยหน่า", "มะขามหวาน", "ลูกตาล",
]
HIGH_SUGAR_KEYWORDS_EN = [
    "cookie", "candy", "chocolate", "ice cream", "donut",
    "honey", "jam ", "pudding", "soda", "soft drink",
    "durian", "longan", " grape", "ripe mango", "lychee",
    "sweet tamarind", "toffee", "caramel", "bubble tea", "milk tea",
]

# ยกเว้นไม่ override เป็น 5 ถ้าชื่อบอกชัดว่าไม่หวาน/คีโต/เป็นน้ำมัน
EXCLUDE_KEYWORDS = [
    "คีโต", "keto", "ไม่หวาน", "unsweetened", "sugar-free",
    "ไม่มีน้ำตาล", "zero sugar", "no sugar added", "น้ำมัน", " oil",
]


def has_keyword(name, keywords):
    if not isinstance(name, str):
        return False
    nl = name.lower()
    return any(k.lower() in nl for k in keywords)


def jackfruit_ripe_override(row):
    """ขนุน — บวกเฉพาะ 'สุก' (ripe) เท่านั้น ไม่ใช่แกง/อ่อน/ดิบ (savory/unripe)"""
    name = str(row.get("food_name_th", "")) + " " + str(row.get("food_name_en", ""))
    if "ขนุน" not in name and "jackfruit" not in name.lower():
        return False
    is_ripe = ("สุก" in name) or ("ripe" in name.lower())
    is_savory = (
        ("แกง" in name) or ("อ่อน" in name) or ("ดิบ" in name)
        or ("curry" in name.lower()) or ("unripe" in name.lower())
        or ("raw" in name.lower())
    )
    return is_ripe and not is_savory


def free_sugar_flag(df: pd.DataFrame) -> pd.Series:
    """[DEV_LOG Entry 46] True = ชื่อบอกว่าเป็นของหวาน/เครื่องดื่มหวาน/ผลไม้
    น้ำตาลสูง (น้ำตาลอิสระ) — แยกจากส่วน carb quintile ของ sugar_risk เพราะ
    เบาหวานควรตัดเฉพาะกลุ่มนี้ ส่วน "แป้งเยอะ" คุมด้วยเพดานคาร์บต่อมื้ออยู่แล้ว"""
    kw_hit = (df["food_name_th"].apply(lambda x: has_keyword(x, HIGH_SUGAR_KEYWORDS_TH))
              | df["food_name_en"].apply(lambda x: has_keyword(x, HIGH_SUGAR_KEYWORDS_EN))
              | df.apply(jackfruit_ripe_override, axis=1))
    is_excluded = (
        df["food_name_th"].apply(lambda x: has_keyword(x, EXCLUDE_KEYWORDS))
        | df["food_name_en"].apply(lambda x: has_keyword(x, EXCLUDE_KEYWORDS))
    )
    return (kw_hit & ~is_excluded).astype(bool)


def compute_sugar_risk(df: pd.DataFrame) -> pd.Series:
    """ใช้ซ้ำได้จากที่อื่น (เช่น ml/pipeline.py หรือ import_foods.py)"""
    carb = df["carb_available_g"].fillna(df["carb_available_g"].median())
    base = pd.qcut(carb, 5, labels=[1, 2, 3, 4, 5], duplicates="drop").astype(int)

    kw_hit_th = df["food_name_th"].apply(lambda x: has_keyword(x, HIGH_SUGAR_KEYWORDS_TH))
    kw_hit_en = df["food_name_en"].apply(lambda x: has_keyword(x, HIGH_SUGAR_KEYWORDS_EN))
    jackfruit_hit = df.apply(jackfruit_ripe_override, axis=1)
    kw_hit = kw_hit_th | kw_hit_en | jackfruit_hit

    is_excluded = (
        df["food_name_th"].apply(lambda x: has_keyword(x, EXCLUDE_KEYWORDS))
        | df["food_name_en"].apply(lambda x: has_keyword(x, EXCLUDE_KEYWORDS))
    )
    kw_hit = kw_hit & ~is_excluded

    sugar_risk = base.copy()
    sugar_risk[kw_hit] = 5
    return sugar_risk.astype(int)


def main():
    # [FIX — DEV_LOG Entry 46] เดิมเขียนทับ foods_master_v2.csv ตรงๆ จาก
    # foods_master.csv (ไฟล์ก่อนแก้ข้อมูล) — ถ้ารันซ้ำ งานเติม/แก้ข้อมูลทั้งหมด
    # ตั้งแต่ Entry 18 เป็นต้นมาจะหายเงียบๆ ตอนนี้ต้องใส่ --force ถึงจะยอมเขียนทับ
    import os, sys
    if os.path.exists(OUT) and "--force" not in sys.argv:
        print(f"{OUT} มีอยู่แล้ว และมีการแก้ข้อมูลหลังสคริปต์นี้หลายรอบ (ดู mineral_source) — "
              f"ไม่เขียนทับ ถ้าตั้งใจจริงให้รัน: python scripts/compute_sugar_risk.py --force")
        return
    df = pd.read_csv(SRC, encoding="utf-8-sig")
    n_before = len(df)

    df["sugar_risk"] = compute_sugar_risk(df)

    assert len(df) == n_before, "row count changed!"
    assert df["sugar_risk"].between(1, 5).all(), "sugar_risk out of range!"

    df.to_csv(OUT, index=False, encoding="utf-8-sig")

    print("=== distribution ===")
    print(df["sugar_risk"].value_counts().sort_index())
    print(f"\nkeyword-override count: {(df['sugar_risk'] == 5).sum()} rows scored 5")
    print(f"saved -> {OUT}")


if __name__ == "__main__":
    main()
