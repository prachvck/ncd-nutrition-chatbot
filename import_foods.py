# import_foods.py — นำเข้า foods_master_v2.csv → PostgreSQL table: foods
#
# วิธีใช้:
#   python import_foods.py                       # upsert ทุกแถว (เพิ่มเมนูใหม่/อัปเดตค่า)
#   python import_foods.py --prune               # + ลบแถวที่ไม่อยู่ใน CSV แล้ว
#
# [DEV_LOG Entry 48] ตัด --truncate ออก — TRUNCATE ... CASCADE ลบตารางที่อ้างอิง foods
# ทั้งหมดด้วย (food_logs ประวัติการกินของผู้ใช้หายเกลี้ยง) ใช้ --prune แทน: ลบเฉพาะ
# food_id ที่ไม่มีใน CSV แล้ว ด้วย DELETE ปกติ (food_logs.food_id → NULL ตาม FK
# ON DELETE SET NULL แต่ชื่อ/ค่าโภชนาการที่บันทึกไว้ยังอยู่ครบ)
#
# ตั้ง DATABASE_URL ก่อนรัน:
#   export DATABASE_URL="postgresql://user:password@host:5432/dbname"
#   หรือใส่ใน .env file

import argparse
import os
import sys

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# =============================================================================
# DDL — สร้างตาราง foods ถ้ายังไม่มี
# =============================================================================
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS foods (
    food_id              INTEGER PRIMARY KEY,
    food_name_th         TEXT,
    food_name_en         TEXT,

    -- per-100g (raw จาก CSV)
    energy_kcal          NUMERIC(8,2),
    water_g              NUMERIC(8,2),
    protein_g            NUMERIC(8,2),
    fat_g                NUMERIC(8,2),
    carb_available_g     NUMERIC(8,2),
    dietary_fiber_g      NUMERIC(8,2),
    ash_g                NUMERIC(8,2),

    -- minerals
    calcium_mg           NUMERIC(8,2),
    phosphorus_mg        NUMERIC(8,2),
    magnesium_mg         NUMERIC(8,2),
    sodium_mg            NUMERIC(8,2),
    potassium_mg         NUMERIC(8,2),
    iron_mg              NUMERIC(8,3),
    copper_mg            NUMERIC(8,3),
    zinc_mg              NUMERIC(8,3),
    iodine_ug            NUMERIC(8,2),

    -- vitamins
    betacarotene_ug      NUMERIC(8,2),
    retinol_ug           NUMERIC(8,2),
    vitamin_a_rae_ug     NUMERIC(8,2),
    thiamin_mg           NUMERIC(8,3),
    riboflavin_mg        NUMERIC(8,3),
    niacin_mg            NUMERIC(8,3),
    vitamin_c_mg         NUMERIC(8,2),
    vitamin_e_mg         NUMERIC(8,2),

    -- metadata จาก CSV
    multiplier           NUMERIC(4,1),
    -- [FIX — DEV_LOG Entry 17] เดิมนิยามเป็น VARCHAR(10) 'Low'|'Medium'|'High'
    -- แต่ไม่เคยถูก populate จากแหล่งข้อมูลไหนเลย (คอลัมน์ตาย) เปลี่ยนเป็น
    -- SMALLINT (1-5, ยิ่งมากยิ่งไม่เหมาะกับเบาหวาน) คำนวณจาก carb_available_g
    -- quintile + keyword ชื่ออาหาร ดู scripts/compute_sugar_risk.py
    sugar_risk           SMALLINT,      -- 1 (คาร์บ/น้ำตาลต่ำสุด) — 5 (สูงสุด)
    food_type            VARCHAR(20),   -- 'dish' | 'ingredient' (ดู DEV_LOG Entry 8)

    -- คำนวณโดย ML pipeline (อัปเดตภายหลังหลัง train)
    serving_g            NUMERIC(6,1),
    food_category        VARCHAR(50),
    cluster_id           SMALLINT,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# =============================================================================
# Serving size map (เหมือน notebook)
# =============================================================================
SERVING_MAP = [
    (['rice topped', 'fried rice', 'rice with', 'rice cooked',
      'rice and glutinous', 'rice boiled with coconut', 'brown rice topped'], 400, 'rice_dish'),
    (['noodles', 'noodle', 'suki', 'wonton'], 400, 'noodle_soup'),
    (['round rice noodles'], 350, 'khanom_jeen'),
    (['curry', 'soup', 'stew', 'tom-kha', 'gaeng', 'kang'], 200, 'curry_soup'),
    (['salad', 'spicy minced', 'spicy beef', 'spicy rice', 'papaya',
      'spicy vegetable', 'budu', 'spirulina'], 150, 'salad_yum'),
    (['stir-fried', 'fried', 'stir fry'], 150, 'stirfry_side'),
    (['grilled', 'canned', 'steamed tuna', 'steamed saba', 'steamed sardine',
      'dried shredded', 'sausage'], 100, 'protein_side'),
    (['sauce', 'paste', 'dip', 'nam-prik', 'namprik'], 80, 'dip_sauce'),
]
DEFAULT_SERVING_G = 300


def get_serving(name_en: str) -> tuple[float, str]:
    if not isinstance(name_en, str):
        return DEFAULT_SERVING_G, 'unknown'
    nl = name_en.lower()
    for kws, sg, lb in SERVING_MAP:
        if any(k in nl for k in kws):
            return sg, lb
    return DEFAULT_SERVING_G, 'other'


# =============================================================================
# Helper
# =============================================================================
def to_none(val):
    """pandas NaN / NaT → None (psycopg2 แปลง None เป็น NULL)"""
    if pd.isna(val):
        return None
    return val


# =============================================================================
# Main
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Import foods CSV to PostgreSQL")
    parser.add_argument("--csv",     default="foods_master_v2.csv", help="path to CSV file")
    parser.add_argument("--db-url",  default=None, help="override DATABASE_URL")
    parser.add_argument("--prune", action="store_true",
                        help="ลบ food_id ที่ไม่มีใน CSV แล้ว (หลัง upsert) — ไม่กระทบ food_logs")
    args = parser.parse_args()

    db_url = args.db_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: ตั้ง DATABASE_URL ก่อน หรือใช้ --db-url", file=sys.stderr)
        sys.exit(1)

    # ── โหลด CSV ──────────────────────────────────────────────────────────────
    print(f"Loading {args.csv} ...")
    df = pd.read_csv(args.csv)
    print(f"  {len(df)} rows, {len(df.columns)} columns")
    # [Entry 57] แถวที่ไม่มีชื่อไทย (foods.food_name_th NOT NULL) — ข้ามพร้อมเตือน แทนการล้มทั้งไฟล์
    bad = df["food_name_th"].isna() | (df["food_name_th"].astype(str).str.strip() == "")
    if bad.any():
        print(f"  [WARN] ข้าม {int(bad.sum())} แถวที่ไม่มี food_name_th: "
              f"{df.loc[bad, 'food_id'].tolist()[:10]}")
        df = df[~bad]

    # เพิ่ม serving_g และ food_category
    df[['serving_g', 'food_category']] = df['food_name_en'].apply(
        lambda x: pd.Series(get_serving(x))
    )

    # ── เชื่อม DB ──────────────────────────────────────────────────────────────
    print(f"Connecting to DB ...")
    conn = psycopg2.connect(db_url)
    cur  = conn.cursor()

    # สร้างตาราง
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    print("  Table 'foods' ready")

    # ถ้าตาราง foods มีอยู่แล้วจากรันครั้งก่อน (ก่อนเพิ่ม food_type เข้า schema)
    # CREATE TABLE IF NOT EXISTS จะไม่เพิ่มคอลัมน์ใหม่ให้ ต้อง ALTER เอง กัน
    # INSERT ล้มเพราะ "column food_type does not exist"
    cur.execute("ALTER TABLE foods ADD COLUMN IF NOT EXISTS food_type VARCHAR(20);")
    conn.commit()

    # [FIX — DEV_LOG Entry 17] ถ้าตาราง foods มีอยู่แล้วจากรันครั้งก่อน
    # sugar_risk อาจยังเป็น VARCHAR(10) เดิม (schema เก่า) — ยืนยันแล้วว่า
    # ไม่เคยมีข้อมูลจริงในคอลัมน์นี้เลยจากทุกแหล่ง (dead column) จึง drop
    # แล้วสร้างใหม่เป็น SMALLINT ได้อย่างปลอดภัย ไม่เสี่ยงข้อมูลหาย
    cur.execute("ALTER TABLE foods DROP COLUMN IF EXISTS sugar_risk;")
    cur.execute("ALTER TABLE foods ADD COLUMN IF NOT EXISTS sugar_risk SMALLINT;")
    conn.commit()


    # ── เตรียม rows — ใช้เฉพาะ column ที่มีใน CSV จริง ─────────────────────────
    ALL_POSSIBLE_COLS = [
        'food_id', 'food_name_th', 'food_name_en',
        'energy_kcal', 'water_g', 'protein_g', 'fat_g', 'carb_available_g',
        'dietary_fiber_g', 'ash_g',
        'calcium_mg', 'phosphorus_mg', 'magnesium_mg', 'sodium_mg', 'potassium_mg',
        'iron_mg', 'copper_mg', 'zinc_mg', 'iodine_ug',
        'betacarotene_ug', 'retinol_ug', 'vitamin_a_rae_ug',
        'thiamin_mg', 'riboflavin_mg', 'niacin_mg', 'vitamin_c_mg', 'vitamin_e_mg',
        'multiplier', 'sugar_risk', 'food_type',
        'serving_g', 'food_category',
    ]
    COLS = [c for c in ALL_POSSIBLE_COLS if c in df.columns]
    skipped = [c for c in ALL_POSSIBLE_COLS if c not in df.columns]
    if skipped:
        print(f"  [INFO] column ที่ไม่มีใน CSV (จะข้ามไป): {skipped}")

    rows = []
    for _, row in df.iterrows():
        rows.append(tuple(to_none(row[c]) for c in COLS))

    # ── Insert ──────────────────────────────────────────────────────────────────
    # สร้าง INSERT SQL จาก COLS จริงที่มีใน CSV (dynamic ไม่ hardcode)
    update_cols = [c for c in COLS if c != 'food_id']
    update_clause = ',\n            '.join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    INSERT_SQL = f"""
        INSERT INTO foods ({', '.join(COLS)})
        VALUES %s
        ON CONFLICT (food_id) DO UPDATE SET
            {update_clause}
    """

    print(f"Inserting {len(rows)} rows ...")
    execute_values(cur, INSERT_SQL, rows, page_size=100)
    conn.commit()

    if args.prune and 'food_id' in df.columns:
        ids = [int(x) for x in df['food_id'].dropna().unique()]
        cur.execute("DELETE FROM foods WHERE NOT (food_id = ANY(%s))", (ids,))
        print(f"  Pruned {cur.rowcount} rows ที่ไม่อยู่ใน CSV แล้ว")
        conn.commit()

    # ── Verify ─────────────────────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM foods")
    count = cur.fetchone()[0]
    print(f"  Done — {count} rows in foods table")

    cur.execute("""
        SELECT food_category, COUNT(*) as n
        FROM foods GROUP BY food_category ORDER BY n DESC
    """)
    print("\n  Breakdown by category:")
    for cat, n in cur.fetchall():
        print(f"    {cat:<20} {n}")

    cur.close()
    conn.close()
    print("\nImport complete!")


if __name__ == "__main__":
    main()
