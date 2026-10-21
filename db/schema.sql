-- ══════════════════════════════════════════════════════════════════
-- NCD Food Recommendation Chatbot — Database Setup
-- รันไฟล์นี้ครั้งเดียว เพื่อสร้างทุกอย่างตั้งแต่ต้น
-- ══════════════════════════════════════════════════════════════════

-- ── 1. สร้าง Database (รันใน psql ในฐานะ superuser) ─────────────
--    ถ้ารันด้วย psql ให้ uncomment บรรทัดล่าง
--    หรือสร้างด้วย: createdb ncd_chatbot
-- CREATE DATABASE ncd_chatbot
--     ENCODING    = 'UTF8'
--     LC_COLLATE  = 'th_TH.UTF-8'
--     LC_CTYPE    = 'th_TH.UTF-8'
--     TEMPLATE    = template0;

-- เชื่อมต่อเข้า database (ถ้าใช้ psql)
-- \c ncd_chatbot

-- ══════════════════════════════════════════════════════════════════
-- 2. Extensions
-- ══════════════════════════════════════════════════════════════════
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- สำหรับ gen_random_uuid() ถ้าต้องการ


-- ══════════════════════════════════════════════════════════════════
-- 3. ENUM types
-- ══════════════════════════════════════════════════════════════════
DO $$ BEGIN
    CREATE TYPE gender_type   AS ENUM ('male', 'female');
    CREATE TYPE meal_type     AS ENUM ('breakfast', 'lunch', 'dinner', 'snack', 'unknown');
    CREATE TYPE portion_type  AS ENUM ('small', 'normal', 'large');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;


-- ══════════════════════════════════════════════════════════════════
-- 4. TABLE: users
--    เก็บ profile ผู้ใช้แต่ละคน (1 row = 1 LINE user)
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS users (
    line_user_id    TEXT            PRIMARY KEY,
    name            TEXT,
    age             INT             CHECK (age BETWEEN 5 AND 120),
    gender          gender_type,
    weight_kg       FLOAT           CHECK (weight_kg BETWEEN 20 AND 300),
    height_cm       FLOAT           CHECK (height_cm BETWEEN 100 AND 250),
    activity_level  INT             CHECK (activity_level BETWEEN 1 AND 5),
    -- diseases เก็บเป็น JSON array string เช่น '["diabetes","hypertension"]'
    -- เพื่อ compatibility กับ SQLite / ORM ทุกตัว
    diseases        TEXT            NOT NULL DEFAULT '[]',
    goal            TEXT            NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  users                 IS 'โปรไฟล์ผู้ใช้ LINE แต่ละคน';
COMMENT ON COLUMN users.line_user_id    IS 'LINE User ID จาก webhook event.source.userId';
COMMENT ON COLUMN users.activity_level IS '1=นั่งทำงาน 2=เบา 3=ปานกลาง 4=หนัก 5=หนักมาก';
COMMENT ON COLUMN users.diseases        IS 'JSON array: ["diabetes","hypertension","obesity","ckd","heart"]';
COMMENT ON COLUMN users.goal            IS 'เป้าหมาย เช่น ลดหวาน ลดเค็ม ลดน้ำหนัก';


-- ── auto-update updated_at ────────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ══════════════════════════════════════════════════════════════════
-- 5. TABLE: foods
--    ข้อมูลโภชนาการจาก nutritionaddsugar.csv
--    import ครั้งเดียว ไม่ต้องอ่าน CSV ทุกครั้ง
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS foods (
    food_id             SERIAL          PRIMARY KEY,
    food_name_th        TEXT            NOT NULL,
    food_name_en        TEXT,

    -- ── Macronutrients ──────────────────────────────────────────
    energy_kcal         FLOAT,
    water_g             FLOAT,
    protein_g           FLOAT,
    fat_g               FLOAT,
    carb_available_g    FLOAT,
    dietary_fiber_g     FLOAT,
    ash_g               FLOAT,

    -- ── Minerals ────────────────────────────────────────────────
    calcium_mg          FLOAT,
    phosphorus_mg       FLOAT,
    magnesium_mg        FLOAT,
    sodium_mg           FLOAT,
    potassium_mg        FLOAT,
    iron_mg             FLOAT,
    copper_mg           FLOAT,
    zinc_mg             FLOAT,
    iodine_ug           FLOAT,

    -- ── Vitamins ────────────────────────────────────────────────
    betacarotene_ug     FLOAT,
    retinol_ug          FLOAT,
    vitamin_a_rae_ug    FLOAT,
    thiamin_mg          FLOAT,
    riboflavin_mg       FLOAT,
    niacin_mg           FLOAT,
    vitamin_c_mg        FLOAT,
    vitamin_e_mg        FLOAT,

    -- ── Serving meta (เพิ่มจาก SERVING_MAP ใน ML pipeline) ────
    serving_g           INT             NOT NULL DEFAULT 300,
    food_category       TEXT,

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  foods                 IS 'ข้อมูลโภชนาการ import จาก nutritionaddsugar.csv (per serving)';
COMMENT ON COLUMN foods.serving_g       IS 'ปริมาณ 1 มื้อ (กรัม) คำนวณจาก SERVING_MAP';
COMMENT ON COLUMN foods.food_category   IS 'rice_dish | noodle_soup | curry_soup | stirfry_side | ...';

CREATE INDEX IF NOT EXISTS idx_foods_name_th  ON foods USING gin(to_tsvector('simple', food_name_th));
CREATE INDEX IF NOT EXISTS idx_foods_name_en  ON foods USING gin(to_tsvector('simple', COALESCE(food_name_en,'')));
CREATE INDEX IF NOT EXISTS idx_foods_category ON foods(food_category);


-- ══════════════════════════════════════════════════════════════════
-- 6. TABLE: recommendations
--    เก็บ session ที่ระบบคำนวณ BMR/TDEE และแนะนำอาหาร
--    1 row = 1 ครั้งที่ user ขอแนะนำ
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS recommendations (
    id                  SERIAL          PRIMARY KEY,
    line_user_id        TEXT            NOT NULL REFERENCES users(line_user_id) ON DELETE CASCADE,

    -- ── ค่าที่คำนวณได้จาก profile ──────────────────────────────
    bmr                 FLOAT           NOT NULL,
    tdee                FLOAT           NOT NULL,

    -- ── เป้าหมายสารอาหารต่อวัน ─────────────────────────────────
    target_energy       FLOAT,
    target_carb_g       FLOAT,
    target_protein_g    FLOAT,
    target_fat_g        FLOAT,
    target_sodium_mg    FLOAT,
    target_potassium_mg FLOAT,
    target_calcium_mg   FLOAT,
    target_magnesium_mg FLOAT,

    -- ── ML output ───────────────────────────────────────────────
    pred_cluster        INT             CHECK (pred_cluster IN (0, 1, 2)),

    -- ── snapshot โรคและ profile ณ เวลาที่แนะนำ ─────────────────
    -- (เพราะ user อาจแก้ไข profile ทีหลัง แต่เราต้องการข้อมูลเดิม)
    snapshot_age        INT,
    snapshot_weight_kg  FLOAT,
    snapshot_diseases   TEXT            DEFAULT '[]',

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  recommendations               IS 'แต่ละครั้งที่ระบบคำนวณ BMR/TDEE และแนะนำเมนู';
COMMENT ON COLUMN recommendations.pred_cluster  IS 'Cluster 0/1/2 จาก KMeans→ANN';
COMMENT ON COLUMN recommendations.snapshot_diseases IS 'snapshot โรคตอนที่แนะนำ เพื่อ audit';

CREATE INDEX IF NOT EXISTS idx_rec_user       ON recommendations(line_user_id);
CREATE INDEX IF NOT EXISTS idx_rec_created    ON recommendations(line_user_id, created_at DESC);


-- ══════════════════════════════════════════════════════════════════
-- 7. TABLE: food_logs
--    บันทึกอาหารที่ user กินแต่ละมื้อ
--    ใช้สำหรับ: สรุปวันนี้, กรอง history ใน ML, แสดง progress
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS food_logs (
    id                  SERIAL          PRIMARY KEY,
    line_user_id        TEXT            NOT NULL REFERENCES users(line_user_id) ON DELETE CASCADE,
    recommendation_id   INT             REFERENCES recommendations(id) ON DELETE SET NULL,
    food_id             INT             REFERENCES foods(food_id) ON DELETE SET NULL,

    -- ── ชื่ออาหาร (เก็บ snapshot ไว้ด้วยเผื่อ food ถูกลบ) ──────
    food_name_th        TEXT            NOT NULL,
    food_name_en        TEXT,

    -- ── มื้อและปริมาณ ────────────────────────────────────────────
    meal_type           meal_type       NOT NULL DEFAULT 'unknown',
    portion             portion_type    NOT NULL DEFAULT 'normal',
    portion_multiplier  FLOAT           NOT NULL DEFAULT 1.0,
    -- 0.75=small, 1.0=normal, 1.35=large (คำนวณไว้แล้วตอน save)

    -- ── สารอาหารจริงที่กิน (= food value × portion_multiplier) ──
    energy_kcal         FLOAT           NOT NULL DEFAULT 0,
    water_g             FLOAT           NOT NULL DEFAULT 0,
    protein_g           FLOAT           NOT NULL DEFAULT 0,
    fat_g               FLOAT           NOT NULL DEFAULT 0,
    carb_available_g    FLOAT           NOT NULL DEFAULT 0,
    sodium_mg           FLOAT           NOT NULL DEFAULT 0,
    potassium_mg        FLOAT           NOT NULL DEFAULT 0,
    calcium_mg          FLOAT           NOT NULL DEFAULT 0,
    magnesium_mg        FLOAT           NOT NULL DEFAULT 0,
    phosphorus_mg       FLOAT        NOT NULL DEFAULT 0,   -- [DEV_LOG Entry 36]

    -- ── timestamp ────────────────────────────────────────────────
    eaten_at            TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- ── ป้องกันบันทึกซ้ำภายใน 1 นาที (กันกด 2 ครั้ง) ───────────
    CONSTRAINT uq_food_log_dedup UNIQUE (line_user_id, food_name_th, eaten_at)
);

COMMENT ON TABLE  food_logs                     IS 'บันทึกอาหารที่ user กินแต่ละมื้อ';
COMMENT ON COLUMN food_logs.portion_multiplier  IS '0.75=small 1.0=normal 1.35=large';
COMMENT ON COLUMN food_logs.energy_kcal         IS 'ค่าจริงที่กิน = foods.energy_kcal × portion_multiplier';

CREATE INDEX IF NOT EXISTS idx_food_logs_user_date
    ON food_logs(line_user_id, eaten_at DESC);

-- [Entry 54] เดิมเป็น expression index ((eaten_at AT TIME ZONE ...)::date) ซึ่ง Postgres ไม่ยอม
-- (ฟังก์ชันไม่ immutable) → error ตอนรัน schema ใช้ index บน eaten_at ตรงๆ แทน
CREATE INDEX IF NOT EXISTS idx_food_logs_date ON food_logs(eaten_at);


-- ══════════════════════════════════════════════════════════════════
-- 8. VIEW: daily_nutrition_summary
--    query บ่อยมาก — สรุปสารอาหารรายวันของแต่ละ user
--    ใช้: SELECT * FROM daily_nutrition_summary
--         WHERE line_user_id = $1 AND log_date = CURRENT_DATE
-- ══════════════════════════════════════════════════════════════════
CREATE OR REPLACE VIEW daily_nutrition_summary AS
SELECT
    line_user_id,
    (eaten_at AT TIME ZONE 'Asia/Bangkok')::date   AS log_date,
    COUNT(*)                                        AS meal_count,
    ROUND(SUM(energy_kcal)::NUMERIC, 1)            AS total_energy_kcal,
    ROUND(SUM(carb_available_g)::NUMERIC, 1)       AS total_carb_g,
    ROUND(SUM(protein_g)::NUMERIC, 1)              AS total_protein_g,
    ROUND(SUM(fat_g)::NUMERIC, 1)                  AS total_fat_g,
    ROUND(SUM(sodium_mg)::NUMERIC, 1)              AS total_sodium_mg,
    ROUND(SUM(potassium_mg)::NUMERIC, 1)           AS total_potassium_mg,
    ROUND(SUM(calcium_mg)::NUMERIC, 1)             AS total_calcium_mg,
    ROUND(SUM(magnesium_mg)::NUMERIC, 1)           AS total_magnesium_mg,
    ROUND(SUM(phosphorus_mg)::NUMERIC, 1)          AS total_phosphorus_mg
FROM food_logs
GROUP BY line_user_id, (eaten_at AT TIME ZONE 'Asia/Bangkok')::date;

COMMENT ON VIEW daily_nutrition_summary IS 'สรุปสารอาหารรายวันแต่ละ user — ใช้กับ Feature สรุปวันนี้';


-- ══════════════════════════════════════════════════════════════════
-- 9. VIEW: recent_food_history
--    ดึงเมนูที่กินล่าสุด N วัน — ส่งให้ ML pipeline กรอง MMR
-- ══════════════════════════════════════════════════════════════════
CREATE OR REPLACE VIEW recent_food_history AS
SELECT
    line_user_id,
    food_name_th,
    MAX(eaten_at) AS last_eaten_at
FROM food_logs
WHERE eaten_at > NOW() - INTERVAL '3 days'
GROUP BY line_user_id, food_name_th
ORDER BY line_user_id, last_eaten_at DESC;

COMMENT ON VIEW recent_food_history IS '3 วันล่าสุด — ใช้กรอง history ใน KNN+MMR';


-- ══════════════════════════════════════════════════════════════════
-- 10. FUNCTION: import_foods_from_csv(path)
--     ใช้ import nutritionaddsugar.csv เข้า foods table ครั้งแรก
--     รัน: SELECT import_foods_csv('/absolute/path/to/nutritionaddsugar.csv');
-- ══════════════════════════════════════════════════════════════════
-- วิธีง่ายกว่า: ใช้ COPY โดยตรง (ต้องรันใน psql หรือ superuser)
-- COPY foods (food_name_th, food_name_en, energy_kcal, water_g, ...)
-- FROM '/path/to/nutritionaddsugar.csv'
-- WITH (FORMAT csv, HEADER true, NULL '');

-- หรือใช้ Python script (แนะนำ เพราะคำนวณ serving_g ด้วย):
-- python scripts/import_foods.py


-- ══════════════════════════════════════════════════════════════════
-- 11. ข้อมูลตัวอย่าง (สำหรับทดสอบ)
-- ══════════════════════════════════════════════════════════════════
INSERT INTO foods (
    food_name_th, food_name_en,
    energy_kcal, water_g, protein_g, fat_g, carb_available_g,
    sodium_mg, potassium_mg, calcium_mg, magnesium_mg,
    serving_g, food_category
) VALUES
    ('ข้าวผัดหมู', 'Fried rice with pork',
     700, 120, 22, 18, 95, 850, 280, 30, 22, 400, 'rice_dish'),
    ('ต้มยำกุ้ง', 'Tom yum goong',
     180, 200, 15, 8, 12, 1200, 380, 45, 28, 200, 'curry_soup'),
    ('ส้มตำไทย', 'Papaya salad Thai',
     120, 140, 3, 1, 22, 600, 320, 55, 20, 150, 'salad_yum'),
    ('ก๋วยเตี๋ยวหมูแดง', 'Noodle with red pork',
     420, 280, 20, 10, 60, 900, 240, 35, 18, 400, 'noodle_soup'),
    ('ข้าวหน้าไก่', 'Rice topped with chicken',
     550, 200, 28, 12, 78, 750, 310, 40, 25, 400, 'rice_dish')
ON CONFLICT DO NOTHING;

-- ── ตัวอย่าง user (สำหรับ dev/test) ─────────────────────────────
INSERT INTO users (
    line_user_id, name, age, gender,
    weight_kg, height_cm, activity_level,
    diseases, goal
) VALUES (
    'Utest123', 'ทดสอบ', 35, 'male',
    70, 170, 2,
    '["diabetes"]', 'ลดหวาน'
) ON CONFLICT DO NOTHING;


-- ══════════════════════════════════════════════════════════════════
-- 12. ตรวจสอบว่าสร้างครบ
-- ══════════════════════════════════════════════════════════════════
DO $$
DECLARE
    tbl TEXT;
    missing TEXT[] := ARRAY[]::TEXT[];
BEGIN
    FOREACH tbl IN ARRAY ARRAY['users','foods','recommendations','food_logs'] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = tbl AND table_schema = 'public'
        ) THEN
            missing := array_append(missing, tbl);
        END IF;
    END LOOP;

    IF array_length(missing, 1) > 0 THEN
        RAISE EXCEPTION 'ตาราง % ยังไม่ถูกสร้าง', array_to_string(missing, ', ');
    ELSE
        RAISE NOTICE '✓ สร้างทุกตารางเรียบร้อยแล้ว: users, foods, recommendations, food_logs';
        RAISE NOTICE '✓ Views: daily_nutrition_summary, recent_food_history';
        RAISE NOTICE '✓ ขั้นตอนต่อไป: import foods จาก CSV ด้วย scripts/import_foods.py';
    END IF;
END;
$$;
