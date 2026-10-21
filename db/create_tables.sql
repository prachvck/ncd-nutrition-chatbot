-- ══════════════════════════════════════════════════════════════════
-- NCD Chatbot — วางใน pgAdmin Query Tool แล้วกด F5
-- ══════════════════════════════════════════════════════════════════

-- 1. ENUM types
DO $$ BEGIN
    CREATE TYPE gender_type  AS ENUM ('male', 'female');
    CREATE TYPE meal_type    AS ENUM ('breakfast', 'lunch', 'dinner', 'snack', 'unknown');
    CREATE TYPE portion_type AS ENUM ('small', 'normal', 'large');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;


-- 2. TABLE: users
CREATE TABLE IF NOT EXISTS users (
    line_user_id    TEXT         PRIMARY KEY,
    name            TEXT,
    age             INT          CHECK (age BETWEEN 5 AND 120),
    gender          gender_type,
    weight_kg       FLOAT        CHECK (weight_kg BETWEEN 20 AND 300),
    height_cm       FLOAT        CHECK (height_cm BETWEEN 100 AND 250),
    activity_level  INT          CHECK (activity_level BETWEEN 1 AND 5),
    diseases        TEXT         NOT NULL DEFAULT '[]',
    goal            TEXT         NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- 3. TABLE: foods
CREATE TABLE IF NOT EXISTS foods (
    food_id             SERIAL       PRIMARY KEY,
    food_name_th        TEXT         NOT NULL,
    food_name_en        TEXT,
    energy_kcal         FLOAT,
    water_g             FLOAT,
    protein_g           FLOAT,
    fat_g               FLOAT,
    carb_available_g    FLOAT,
    dietary_fiber_g     FLOAT,
    ash_g               FLOAT,
    calcium_mg          FLOAT,
    phosphorus_mg       FLOAT,
    magnesium_mg        FLOAT,
    sodium_mg           FLOAT,
    potassium_mg        FLOAT,
    iron_mg             FLOAT,
    copper_mg           FLOAT,
    zinc_mg             FLOAT,
    iodine_ug           FLOAT,
    betacarotene_ug     FLOAT,
    retinol_ug          FLOAT,
    vitamin_a_rae_ug    FLOAT,
    thiamin_mg          FLOAT,
    riboflavin_mg       FLOAT,
    niacin_mg           FLOAT,
    vitamin_c_mg        FLOAT,
    vitamin_e_mg        FLOAT,
    serving_g           INT          NOT NULL DEFAULT 300,
    food_category       TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_foods_name_th  ON foods(food_name_th);
CREATE INDEX IF NOT EXISTS idx_foods_name_en  ON foods(food_name_en);
CREATE INDEX IF NOT EXISTS idx_foods_category ON foods(food_category);


-- 4. TABLE: recommendations
CREATE TABLE IF NOT EXISTS recommendations (
    id                   SERIAL       PRIMARY KEY,
    line_user_id         TEXT         NOT NULL REFERENCES users(line_user_id) ON DELETE CASCADE,
    bmr                  FLOAT        NOT NULL,
    tdee                 FLOAT        NOT NULL,
    target_energy        FLOAT,
    target_carb_g        FLOAT,
    target_protein_g     FLOAT,
    target_fat_g         FLOAT,
    target_sodium_mg     FLOAT,
    target_potassium_mg  FLOAT,
    target_calcium_mg    FLOAT,
    target_magnesium_mg  FLOAT,
    pred_cluster         INT          CHECK (pred_cluster IN (0, 1, 2)),
    snapshot_age         INT,
    snapshot_weight_kg   FLOAT,
    snapshot_diseases    TEXT         DEFAULT '[]',
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rec_user    ON recommendations(line_user_id);
CREATE INDEX IF NOT EXISTS idx_rec_created ON recommendations(line_user_id, created_at DESC);


-- 5. TABLE: food_logs
CREATE TABLE IF NOT EXISTS food_logs (
    id                  SERIAL       PRIMARY KEY,
    line_user_id        TEXT         NOT NULL REFERENCES users(line_user_id) ON DELETE CASCADE,
    recommendation_id   INT          REFERENCES recommendations(id) ON DELETE SET NULL,
    food_id             INT          REFERENCES foods(food_id) ON DELETE SET NULL,
    food_name_th        TEXT         NOT NULL,
    food_name_en        TEXT,
    meal_type           meal_type    NOT NULL DEFAULT 'unknown',
    portion             portion_type NOT NULL DEFAULT 'normal',
    portion_multiplier  FLOAT        NOT NULL DEFAULT 1.0,
    energy_kcal         FLOAT        NOT NULL DEFAULT 0,
    water_g             FLOAT        NOT NULL DEFAULT 0,
    protein_g           FLOAT        NOT NULL DEFAULT 0,
    fat_g               FLOAT        NOT NULL DEFAULT 0,
    carb_available_g    FLOAT        NOT NULL DEFAULT 0,
    sodium_mg           FLOAT        NOT NULL DEFAULT 0,
    potassium_mg        FLOAT        NOT NULL DEFAULT 0,
    calcium_mg          FLOAT        NOT NULL DEFAULT 0,
    magnesium_mg        FLOAT        NOT NULL DEFAULT 0,
    phosphorus_mg       FLOAT        NOT NULL DEFAULT 0,   -- [DEV_LOG Entry 36]
    eaten_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_food_log_dedup UNIQUE (line_user_id, food_name_th, eaten_at)
);

CREATE INDEX IF NOT EXISTS idx_food_logs_user_date ON food_logs(line_user_id, eaten_at DESC);


-- 6. VIEW: daily_nutrition_summary
CREATE OR REPLACE VIEW daily_nutrition_summary AS
SELECT
    line_user_id,
    (eaten_at AT TIME ZONE 'Asia/Bangkok')::date        AS log_date,
    COUNT(*)                                            AS meal_count,
    ROUND(SUM(energy_kcal)::NUMERIC,      1)           AS total_energy_kcal,
    ROUND(SUM(carb_available_g)::NUMERIC, 1)           AS total_carb_g,
    ROUND(SUM(protein_g)::NUMERIC,        1)           AS total_protein_g,
    ROUND(SUM(fat_g)::NUMERIC,            1)           AS total_fat_g,
    ROUND(SUM(sodium_mg)::NUMERIC,        1)           AS total_sodium_mg,
    ROUND(SUM(potassium_mg)::NUMERIC,     1)           AS total_potassium_mg,
    ROUND(SUM(calcium_mg)::NUMERIC,       1)           AS total_calcium_mg,
    ROUND(SUM(magnesium_mg)::NUMERIC,     1)           AS total_magnesium_mg,
    ROUND(SUM(phosphorus_mg)::NUMERIC, 1)          AS total_phosphorus_mg
FROM food_logs
GROUP BY line_user_id, (eaten_at AT TIME ZONE 'Asia/Bangkok')::date;


-- 7. VIEW: recent_food_history
CREATE OR REPLACE VIEW recent_food_history AS
SELECT
    line_user_id,
    food_name_th,
    MAX(eaten_at) AS last_eaten_at
FROM food_logs
WHERE eaten_at > NOW() - INTERVAL '3 days'
GROUP BY line_user_id, food_name_th
ORDER BY line_user_id, last_eaten_at DESC;


-- 8. ตรวจสอบว่าสร้างครบ
DO $$
DECLARE tbl TEXT; missing TEXT[] := ARRAY[]::TEXT[];
BEGIN
    FOREACH tbl IN ARRAY ARRAY['users','foods','recommendations','food_logs'] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = tbl AND table_schema = 'public'
        ) THEN missing := array_append(missing, tbl);
        END IF;
    END LOOP;
    IF array_length(missing, 1) > 0 THEN
        RAISE EXCEPTION 'ตาราง % ยังไม่ถูกสร้าง', array_to_string(missing, ', ');
    ELSE
        RAISE NOTICE 'สร้างทุกตารางเรียบร้อย: users, foods, recommendations, food_logs';
        RAISE NOTICE 'Views: daily_nutrition_summary, recent_food_history';
    END IF;
END;
$$;
