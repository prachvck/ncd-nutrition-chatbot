"""
db/database.py  (อัปเดต)
CRUD functions สำหรับทุก table — asyncpg + PostgreSQL
"""
import os, json, logging
from dotenv import load_dotenv

# override=True: ให้ค่าใน .env ชนะเสมอ แม้จะมี environment variable ชื่อเดียวกัน
# ตั้งไว้อยู่แล้วในระบบ (ค่าว่างจาก OS env var เป็นสาเหตุของ
# "invalid DSN: scheme is expected to be..., got ''" ที่เจอตอน dev บน Windows)
load_dotenv(override=True)
log = logging.getLogger(__name__)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/ncd_chatbot")

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        import asyncpg
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _pool

async def init_db():
    pool = await get_pool()
    log.info("DB connection pool ready")
    # [DEV_LOG Entry 36] migration อัตโนมัติ (รันซ้ำได้) — เพิ่ม phosphorus_mg ใน
    # food_logs + view สรุปรายวัน ให้หน้าสรุปวันนี้/งบต่อมื้อของผู้ป่วยไตนับ
    # ฟอสฟอรัสที่กินไปแล้วได้ (DB ที่สร้างจาก schema.sql เก่าไม่มีคอลัมน์นี้)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "ALTER TABLE food_logs ADD COLUMN IF NOT EXISTS phosphorus_mg FLOAT NOT NULL DEFAULT 0")
            await conn.execute(DAILY_SUMMARY_VIEW_SQL)
    except Exception as e:
        log.warning(f"DB migration (phosphorus_mg) ไม่สำเร็จ: {e}")
    # [DEV_LOG Entry 44] ตารางสำหรับ Bandit + วัดผล + CNN (รันซ้ำได้ทุกครั้งที่เปิดแอป)
    try:
        async with pool.acquire() as conn:
            await conn.execute(MIGRATION_V44_SQL)
            await conn.execute(MIGRATION_V54_SQL)
            await conn.execute(MIGRATION_V64_SQL)
    except Exception as e:
        log.warning(f"DB migration (Entry 44/54) ไม่สำเร็จ: {e}")


# [DEV_LOG Entry 54] แจ้งเตือนมื้ออาหาร + สรุปรายสัปดาห์ (รายงาน 5.4 ข้อ 6) — ผู้ใช้ต้องเปิดเอง
# (opt-in) เพราะ push message ของ LINE OA มีโควตาต่อเดือน; last_* = วันที่ส่งล่าสุด กันส่งซ้ำ
# [DEV_LOG Entry 64] log สำหรับวัดผลจากการใช้งานจริง (fallback rate / task completion / ความแม่น CNN)
MIGRATION_V64_SQL = """
ALTER TABLE interaction_logs ADD COLUMN IF NOT EXISTS reply_text TEXT;
ALTER TABLE interaction_logs ADD COLUMN IF NOT EXISTS fallback   TEXT;
ALTER TABLE interaction_logs ADD COLUMN IF NOT EXISTS cnn_ms     FLOAT;
CREATE INDEX IF NOT EXISTS idx_interaction_user ON interaction_logs(line_user_id, created_at);
ALTER TABLE food_image_predictions ADD COLUMN IF NOT EXISTS top3              JSONB;
ALTER TABLE food_image_predictions ADD COLUMN IF NOT EXISTS confirmed_food_id INT;
ALTER TABLE food_image_predictions ADD COLUMN IF NOT EXISTS resolved_at       TIMESTAMPTZ;
"""

MIGRATION_V54_SQL = """
CREATE TABLE IF NOT EXISTS user_reminders (
    line_user_id     TEXT PRIMARY KEY REFERENCES users(line_user_id) ON DELETE CASCADE,
    enabled          BOOLEAN NOT NULL DEFAULT FALSE,
    breakfast_time   TIME NOT NULL DEFAULT '07:30',
    lunch_time       TIME NOT NULL DEFAULT '12:00',
    dinner_time      TIME NOT NULL DEFAULT '18:00',
    weekly_summary   BOOLEAN NOT NULL DEFAULT TRUE,
    last_breakfast   DATE,
    last_lunch       DATE,
    last_dinner      DATE,
    last_weekly      DATE,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


# [DEV_LOG Entry 44]
#  - recommendation_items: เมนูที่ "โชว์" ให้ผู้ใช้ในแต่ละรอบ + context vector
#    ตอนตัดสินใจ + reward — Bandit ต้องรู้ว่าโชว์อะไรแล้วผู้ใช้เลือกอะไร
#  - food_logs.recommendation_item_id: ผูกการกินกับการ์ดที่กด
#  - processed_events: กัน LINE ส่ง event ซ้ำ (redelivery) แล้วบันทึก/ให้ reward ซ้ำ
#  - interaction_logs: เวลาตอบ + intent ต่อข้อความ (ใช้วัดผล chatbot)
#  - bandit_model: พารามิเตอร์ LinUCB (A^-1, b) ให้เรียนรู้ต่อได้หลังรีสตาร์ท
#  - food_image_predictions: ผลทายภาพจาก CNN (ตามที่ตกลงไว้ใน CLAUDE.md)
MIGRATION_V44_SQL = """
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS meal_type TEXT;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS policy    TEXT;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS status    TEXT NOT NULL DEFAULT 'open';

CREATE TABLE IF NOT EXISTS recommendation_items (
    id                 SERIAL PRIMARY KEY,
    recommendation_id  INT NOT NULL REFERENCES recommendations(id) ON DELETE CASCADE,
    position           SMALLINT NOT NULL,
    food_id            INT,
    food_name_th       TEXT NOT NULL,
    portion            TEXT NOT NULL DEFAULT 'normal',
    meal_type          TEXT,
    knn_rank           SMALLINT,
    bandit_score       FLOAT,
    context            JSONB,
    reward             FLOAT,
    rewarded_at        TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rec_items_rec  ON recommendation_items(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_rec_items_food ON recommendation_items(food_id);

ALTER TABLE food_logs ADD COLUMN IF NOT EXISTS recommendation_item_id INT
    REFERENCES recommendation_items(id) ON DELETE SET NULL;
ALTER TABLE food_logs ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'typed';

CREATE TABLE IF NOT EXISTS processed_events (
    event_id    TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS interaction_logs (
    id              SERIAL PRIMARY KEY,
    line_user_id    TEXT,
    event_type      TEXT,
    input_text      TEXT,
    route           TEXT,
    intent          TEXT,
    intent_conf     FLOAT,
    server_ms       FLOAT,
    e2e_ms          FLOAT,
    llm_ms          FLOAT,
    rag_used        BOOLEAN NOT NULL DEFAULT FALSE,
    error           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_interaction_created ON interaction_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS bandit_model (
    name             TEXT PRIMARY KEY,
    feature_version  TEXT NOT NULL,
    d                INT NOT NULL,
    a_inv            JSONB NOT NULL,
    b                JSONB NOT NULL,
    n_updates        INT NOT NULL DEFAULT 0,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS food_image_predictions (
    id                 SERIAL PRIMARY KEY,
    line_user_id       TEXT,
    image_url          TEXT,
    predicted_label    TEXT,
    predicted_food_id  INT,
    confidence         FLOAT,
    model_version      TEXT,
    confirmed          BOOLEAN,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


DAILY_SUMMARY_VIEW_SQL = """
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
GROUP BY line_user_id, (eaten_at AT TIME ZONE 'Asia/Bangkok')::date
"""

# ── Users ─────────────────────────────────────────────────────────
async def get_user(uid):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE line_user_id=$1", uid)
    if not row: return None
    d = dict(row); d["diseases"] = json.loads(d.get("diseases") or "[]"); return d

async def upsert_user(uid, data):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users(line_user_id,name,age,gender,weight_kg,height_cm,activity_level,diseases,goal)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT(line_user_id) DO UPDATE SET
                name=EXCLUDED.name, age=EXCLUDED.age, gender=EXCLUDED.gender,
                weight_kg=EXCLUDED.weight_kg, height_cm=EXCLUDED.height_cm,
                activity_level=EXCLUDED.activity_level, diseases=EXCLUDED.diseases,
                goal=EXCLUDED.goal, updated_at=NOW()
        """, uid, data.get("name"), data.get("age"), data.get("gender"),
            data.get("weight_kg"), data.get("height_cm"), data.get("activity_level"),
            json.dumps(data.get("diseases",[])), data.get("goal",""))

def is_profile_complete(user):
    return all([user.get("age"), user.get("gender"), user.get("weight_kg"), user.get("height_cm")])

# ── Foods ─────────────────────────────────────────────────────────
async def search_foods(keyword, top_n=5):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM foods WHERE food_name_th ILIKE $1 OR food_name_en ILIKE $1 LIMIT $2",
            f"%{keyword}%", top_n)
    return [dict(r) for r in rows]

async def get_all_foods_df():
    import pandas as pd
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM foods ORDER BY food_id")
    return pd.DataFrame([dict(r) for r in rows])

# ── Recommendations ───────────────────────────────────────────────
async def save_recommendation(uid, rec, items=None):
    """บันทึกรอบการแนะนำ 1 รอบ + [Entry 44] เมนูที่โชว์ทุกตัว (items)
    คืน (recommendation_id, [item_id ตามลำดับ items])"""
    user = await get_user(uid)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                INSERT INTO recommendations(
                    line_user_id,bmr,tdee,target_energy,target_carb_g,target_protein_g,
                    target_fat_g,target_sodium_mg,target_potassium_mg,target_calcium_mg,
                    target_magnesium_mg,pred_cluster,snapshot_age,snapshot_weight_kg,snapshot_diseases,
                    meal_type,policy)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17) RETURNING id
            """, uid, rec.get("bmr"), rec.get("tdee"),
                rec.get("target_energy"), rec.get("target_carb_g"), rec.get("target_protein_g"),
                rec.get("target_fat_g"), rec.get("target_sodium_mg"),
                rec.get("target_potassium_mg"), rec.get("target_calcium_mg"), rec.get("target_magnesium_mg"),
                rec.get("pred_cluster"),
                user.get("age") if user else None, user.get("weight_kg") if user else None,
                json.dumps(user.get("diseases",[]) if user else []),
                rec.get("meal_type"), rec.get("policy"))
            rec_id, item_ids = row["id"], []
            for pos, it in enumerate(items or []):
                iid = await conn.fetchval("""
                    INSERT INTO recommendation_items(
                        recommendation_id,position,food_id,food_name_th,portion,meal_type,
                        knn_rank,bandit_score,context)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id
                """, rec_id, pos, it.get("food_id"), it.get("food_name_th", ""),
                    it.get("portion", "normal"), rec.get("meal_type"),
                    it.get("knn_rank"), it.get("bandit_score"),
                    json.dumps(it["context"]) if it.get("context") is not None else None)
                item_ids.append(iid)
    return rec_id, item_ids


async def get_open_recommendation(uid, max_age_hours=12):
    """[Entry 44] รอบแนะนำล่าสุดที่ผู้ใช้ยังไม่ได้เลือก (status=open) พร้อม items"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rec = await conn.fetchrow("""
            SELECT id, meal_type, policy, created_at FROM recommendations
            WHERE line_user_id=$1 AND status='open'
              AND created_at > NOW() - make_interval(hours => $2)
            ORDER BY created_at DESC LIMIT 1
        """, uid, max_age_hours)
        if not rec:
            return None
        items = await conn.fetch("""
            SELECT id, position, food_id, food_name_th, portion, context, reward
            FROM recommendation_items WHERE recommendation_id=$1 ORDER BY position
        """, rec["id"])
    out = dict(rec)
    out["items"] = [{**dict(i), "context": json.loads(i["context"]) if i["context"] else None}
                    for i in items]
    return out


async def get_recommendation_items(rec_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rec = await conn.fetchrow("SELECT id, status, meal_type FROM recommendations WHERE id=$1", rec_id)
        items = await conn.fetch("""
            SELECT id, position, food_id, food_name_th, portion, context, reward
            FROM recommendation_items WHERE recommendation_id=$1 ORDER BY position
        """, rec_id)
    if not rec:
        return None
    out = dict(rec)
    out["items"] = [{**dict(i), "context": json.loads(i["context"]) if i["context"] else None}
                    for i in items]
    return out


async def get_recommendation_id_of_item(item_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT recommendation_id FROM recommendation_items WHERE id=$1", item_id)


async def close_recommendation(rec_id, status, rewards: dict):
    """[Entry 44] ปิดรอบแนะนำ (chosen/rejected/expired) + เขียน reward ต่อ item
    rewards: {item_id: reward} — คืน True ถ้าปิดสำเร็จ (กันให้ reward ซ้ำ:
    อัปเดตได้เฉพาะรอบที่ยัง open อยู่เท่านั้น)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            res = await conn.execute(
                "UPDATE recommendations SET status=$2 WHERE id=$1 AND status='open'", rec_id, status)
            if res.split()[-1] == "0":
                return False
            for iid, r in rewards.items():
                await conn.execute(
                    "UPDATE recommendation_items SET reward=$2, rewarded_at=NOW() WHERE id=$1",
                    iid, r)
    return True


async def get_recently_shown_names(uid, hours=6, limit=9):
    """[Entry 44] เมนูที่เพิ่งโชว์ไป (แทน session history ในหน่วยความจำ —
    รีสตาร์ทแอปแล้วไม่หาย)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT ri.food_name_th FROM recommendation_items ri
            JOIN recommendations r ON r.id = ri.recommendation_id
            WHERE r.line_user_id=$1 AND r.created_at > NOW() - make_interval(hours => $2)
            ORDER BY r.created_at DESC, ri.position LIMIT $3
        """, uid, hours, limit)
    return [r["food_name_th"] for r in rows]


async def get_user_food_history_stats(uid, days=30):
    """[Entry 44] ประวัติการกินสำหรับ context ของ Bandit:
    {"food_counts": {food_id: n}, "name_counts": {food_name_th: n}, "total": n}"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT food_id, food_name_th, COUNT(*) AS n FROM food_logs
            WHERE line_user_id=$1 AND eaten_at > NOW() - make_interval(days => $2)
            GROUP BY food_id, food_name_th
        """, uid, days)
    food_counts, name_counts, total = {}, {}, 0
    for r in rows:
        if r["food_id"] is not None:
            food_counts[int(r["food_id"])] = food_counts.get(int(r["food_id"]), 0) + int(r["n"])
        name_counts[r["food_name_th"]] = int(r["n"])
        total += int(r["n"])
    return {"food_counts": food_counts, "name_counts": name_counts, "total": total}


# ── Webhook dedup / metrics ───────────────────────────────────────
async def mark_event_processed(event_id):
    """[Entry 44] คืน True ถ้า event นี้ยังไม่เคยประมวลผล (และบันทึกไว้แล้ว)
    False = ซ้ำ (LINE redelivery) → ข้าม"""
    if not event_id:
        return True
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            "INSERT INTO processed_events(event_id) VALUES($1) ON CONFLICT DO NOTHING", event_id)
    return res.split()[-1] != "0"


async def save_interaction_log(row: dict):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO interaction_logs(line_user_id,event_type,input_text,route,intent,
                intent_conf,server_ms,e2e_ms,llm_ms,rag_used,error,reply_text,fallback,cnn_ms)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
        """, row.get("uid"), row.get("event_type"), (row.get("text") or "")[:500],
            row.get("route"), row.get("intent"), row.get("intent_conf"),
            row.get("server_ms"), row.get("e2e_ms"), row.get("llm_ms"),
            bool(row.get("rag_used")), bool(row.get("error")),
            (row.get("reply_text") or "")[:2000] or None, row.get("fallback"), row.get("cnn_ms"))


async def save_image_prediction(uid, label, food_id, confidence, model_version, image_url=None,
                                top3=None):
    """[Entry 47] ผลทายภาพจาก CNN (ไม่เก็บไฟล์ภาพใน DB — ตามข้อตกลงใน CLAUDE.md)
    [Entry 64] เก็บ top3 ไว้ด้วย ใช้วัด Top-1/Top-3 จากการใช้งานจริง"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("""
            INSERT INTO food_image_predictions(line_user_id,image_url,predicted_label,
                predicted_food_id,confidence,model_version,top3)
            VALUES($1,$2,$3,$4,$5,$6,$7::jsonb) RETURNING id
        """, uid, image_url, label, food_id, confidence, model_version,
            json.dumps(top3 or [], ensure_ascii=False))


async def resolve_image_prediction(pred_id: int, confirmed: bool, food_id=None):
    """[Entry 64] ผู้ใช้กดยืนยัน/ยกเลิกผลจากรูป → ใช้คำนวณความแม่นของ CNN ตอนใช้จริง"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE food_image_predictions
            SET confirmed=$2, confirmed_food_id=$3, resolved_at=NOW()
            WHERE id=$1 AND resolved_at IS NULL
        """, pred_id, confirmed, food_id)


async def save_event_log(uid: str, route: str, text: str = ""):
    """[Entry 64] เหตุการณ์ที่ไม่ได้มาทาง webhook (เช่น เปิดหน้า Dashboard) — นับ task completion"""
    await save_interaction_log({"uid": uid, "event_type": "liff", "text": text or f"[{route}]",
                                "route": route})


# ── Reminders [Entry 54] ──────────────────────────────────────────
REMINDER_MEALS = ("breakfast", "lunch", "dinner")


async def get_reminder(uid):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM user_reminders WHERE line_user_id=$1", uid)
    return dict(row) if row else None


async def set_reminder(uid, enabled=None, meal=None, at=None):
    """เปิด/ปิด หรือเปลี่ยนเวลาเตือนมื้อ (at = datetime.time)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_reminders(line_user_id) VALUES($1) ON CONFLICT DO NOTHING", uid)
        if enabled is not None:
            await conn.execute(
                "UPDATE user_reminders SET enabled=$2, updated_at=NOW() WHERE line_user_id=$1",
                uid, bool(enabled))
        if meal in REMINDER_MEALS and at is not None:
            await conn.execute(
                f"UPDATE user_reminders SET {meal}_time=$2, enabled=TRUE, updated_at=NOW() "
                f"WHERE line_user_id=$1", uid, at)
    return await get_reminder(uid)


async def claim_due_meal_reminders(meal, window_minutes=60):
    """คืน uid ที่ถึงเวลาเตือนมื้อ `meal` (เวลาไทย) และยังไม่ได้เตือนวันนี้ — มาร์กว่าส่งแล้วใน
    คำสั่งเดียว (UPDATE ... RETURNING) จึงไม่ส่งซ้ำแม้มีหลาย worker; ข้ามคนที่บันทึกมื้อนั้นแล้ว"""
    assert meal in REMINDER_MEALS
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            WITH now_th AS (SELECT (NOW() AT TIME ZONE 'Asia/Bangkok') AS ts)
            UPDATE user_reminders r SET last_{meal} = (SELECT ts::date FROM now_th)
            WHERE r.enabled
              AND (SELECT ts::time FROM now_th) >= r.{meal}_time
              AND (SELECT ts::time FROM now_th) <  r.{meal}_time + make_interval(mins => $1)
              AND r.last_{meal} IS DISTINCT FROM (SELECT ts::date FROM now_th)
            RETURNING r.line_user_id
        """, int(window_minutes))
        uids = [r["line_user_id"] for r in rows]
        if not uids:
            return []
        logged = await conn.fetch("""
            SELECT DISTINCT line_user_id FROM food_logs
            WHERE line_user_id = ANY($1::text[]) AND meal_type = $2::meal_type
              AND (eaten_at AT TIME ZONE 'Asia/Bangkok')::date = (NOW() AT TIME ZONE 'Asia/Bangkok')::date
        """, uids, meal)
    done = {r["line_user_id"] for r in logged}
    return [u for u in uids if u not in done]


async def claim_due_weekly(weekday=6, at_hour=19):
    """สรุปรายสัปดาห์: วันอาทิตย์ (isodow 7) ตั้งแต่ 19:00 เวลาไทย ส่งครั้งเดียวต่อสัปดาห์"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            WITH now_th AS (SELECT (NOW() AT TIME ZONE 'Asia/Bangkok') AS ts)
            UPDATE user_reminders r SET last_weekly = (SELECT ts::date FROM now_th)
            WHERE r.enabled AND r.weekly_summary
              AND EXTRACT(ISODOW FROM (SELECT ts FROM now_th)) = $1
              AND EXTRACT(HOUR FROM (SELECT ts FROM now_th)) >= $2
              AND r.last_weekly IS DISTINCT FROM (SELECT ts::date FROM now_th)
            RETURNING r.line_user_id
        """, weekday + 1, at_hour)
    return [r["line_user_id"] for r in rows]


async def get_logs_range(uid, days=10):
    """[Entry 61] รายการอาหารที่บันทึก ย้อนหลัง `days` วัน (เวลาไทย) สำหรับหน้า dashboard"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT (eaten_at AT TIME ZONE 'Asia/Bangkok')::date AS log_date, eaten_at,
                   food_name_th, meal_type::text AS meal_type, portion::text AS portion, energy_kcal
            FROM food_logs
            WHERE line_user_id=$1
              AND (eaten_at AT TIME ZONE 'Asia/Bangkok')::date > (NOW() AT TIME ZONE 'Asia/Bangkok')::date - $2::int
            ORDER BY eaten_at
        """, uid, int(days))
    return [dict(r) for r in rows]


async def get_week_summary(uid, days=7):
    """สรุปรายวันย้อนหลัง `days` วัน (รวมวันนี้) จาก view daily_nutrition_summary"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM daily_nutrition_summary
            WHERE line_user_id=$1
              AND log_date > (NOW() AT TIME ZONE 'Asia/Bangkok')::date - $2::int
            ORDER BY log_date
        """, uid, int(days))
    return [dict(r) for r in rows]


# ── Bandit model persistence ──────────────────────────────────────
async def load_bandit_model(name):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM bandit_model WHERE name=$1", name)
    if not row:
        return None
    d = dict(row)
    d["a_inv"] = json.loads(d["a_inv"]); d["b"] = json.loads(d["b"])
    return d


async def save_bandit_model(name, feature_version, d, a_inv, b, n_updates):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO bandit_model(name,feature_version,d,a_inv,b,n_updates,updated_at)
            VALUES($1,$2,$3,$4,$5,$6,NOW())
            ON CONFLICT(name) DO UPDATE SET feature_version=EXCLUDED.feature_version,
                d=EXCLUDED.d, a_inv=EXCLUDED.a_inv, b=EXCLUDED.b,
                n_updates=EXCLUDED.n_updates, updated_at=NOW()
        """, name, feature_version, d, json.dumps(a_inv), json.dumps(b), n_updates)

async def get_latest_recommendation(uid):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM recommendations WHERE line_user_id=$1 ORDER BY created_at DESC LIMIT 1", uid)
    return dict(row) if row else None

# ── Food Logs ─────────────────────────────────────────────────────
PORTION_MUL = {"small": 0.75, "normal": 1.0, "large": 1.35}

async def save_food_log(uid, log_data, recommendation_id=None):
    portion = log_data.get("portion","normal")
    mul = PORTION_MUL.get(portion, 1.0)
    food_id = log_data.get("food_id")
    if not food_id and log_data.get("food_name_th"):
        results = await search_foods(log_data["food_name_th"], top_n=1)
        if results: food_id = results[0]["food_id"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        # [FIX — DEV_LOG Entry 32] food_logs.food_id อ้างอิง foods(food_id) —
        # ถ้าตาราง foods ใน DB ยังไม่ได้ import ข้อมูลชุดล่าสุด (เมนูที่เพิ่ม
        # ใหม่ใน foods_master_v2.csv) INSERT จะชน foreign key แล้วบันทึกไม่ได้
        # เลย — กันไว้: ถ้าไม่มี food_id นี้ใน DB ให้เก็บเป็น NULL (ยังมีชื่อ +
        # ค่าโภชนาการ snapshot ครบ) แล้วเตือนใน log ให้รัน import_foods.py
        if food_id is not None:
            exists = await conn.fetchval("SELECT 1 FROM foods WHERE food_id=$1", int(food_id))
            if not exists:
                log.warning(f"food_id {food_id} ไม่มีในตาราง foods — บันทึกเป็น NULL "
                            f"(รัน: python import_foods.py --csv foods_master_v2.csv)")
                food_id = None
        # [FIX — DEV_LOG Entry 44] constraint uq_food_log_dedup ใช้ eaten_at
        # ละเอียดระดับไมโครวินาที → แทบไม่เคยชนกันจริง (กันกดซ้ำไม่ได้) —
        # เช็คเองว่าเพิ่งบันทึกเมนูเดียวกันไปภายใน 60 วินาทีหรือยัง
        dup = await conn.fetchval("""
            SELECT id FROM food_logs WHERE line_user_id=$1 AND food_name_th=$2
              AND eaten_at > NOW() - INTERVAL '60 seconds' LIMIT 1
        """, uid, log_data.get("food_name_th", ""))
        if dup:
            log.info(f"skip duplicate food_log uid={uid} ({log_data.get('food_name_th')})")
            return -1
        row = await conn.fetchrow("""
            INSERT INTO food_logs(
                line_user_id,recommendation_id,food_id,food_name_th,food_name_en,
                meal_type,portion,portion_multiplier,
                energy_kcal,water_g,protein_g,fat_g,carb_available_g,
                sodium_mg,potassium_mg,calcium_mg,magnesium_mg,phosphorus_mg,
                recommendation_item_id,source)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
            ON CONFLICT ON CONSTRAINT uq_food_log_dedup DO NOTHING RETURNING id
        """, uid, recommendation_id or log_data.get("recommendation_id"), food_id,
            log_data.get("food_name_th",""), log_data.get("food_name_en",""),
            log_data.get("meal_type","unknown"), portion, mul,
            (log_data.get("energy_kcal") or 0)*mul, (log_data.get("water_g") or 0)*mul,
            (log_data.get("protein_g") or 0)*mul, (log_data.get("fat_g") or 0)*mul,
            (log_data.get("carb_available_g") or 0)*mul, (log_data.get("sodium_mg") or 0)*mul,
            (log_data.get("potassium_mg") or 0)*mul, (log_data.get("calcium_mg") or 0)*mul,
            (log_data.get("magnesium_mg") or 0)*mul, (log_data.get("phosphorus_mg") or 0)*mul,
            log_data.get("recommendation_item_id"), log_data.get("source", "typed"))
    return row["id"] if row else -1

async def get_today_summary(uid):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM daily_nutrition_summary
            WHERE line_user_id=$1
              AND log_date=(NOW() AT TIME ZONE 'Asia/Bangkok')::date
        """, uid)
    if not row: return {"meal_count":0,"total_energy_kcal":0,"total_carb_g":0,
                        "total_protein_g":0,"total_fat_g":0,"total_sodium_mg":0,
                        "total_potassium_mg":0,"total_phosphorus_mg":0}
    return dict(row)

async def get_today_logs(uid):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM food_logs
            WHERE line_user_id=$1
              AND (eaten_at AT TIME ZONE 'Asia/Bangkok')::date=(NOW() AT TIME ZONE 'Asia/Bangkok')::date
            ORDER BY eaten_at
        """, uid)
    return [dict(r) for r in rows]

async def delete_today_logs(uid):
    """[DEV_LOG Entry 38] ลบบันทึกการกินของวันนี้ (เวลาไทย) ของผู้ใช้คนนี้ —
    ใช้กับคำสั่งทดสอบ 'ลบบันทึกวันนี้' คืนจำนวนแถวที่ลบ"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("""
            DELETE FROM food_logs
            WHERE line_user_id=$1
              AND (eaten_at AT TIME ZONE 'Asia/Bangkok')::date=(NOW() AT TIME ZONE 'Asia/Bangkok')::date
        """, uid)
    try:
        return int(res.split()[-1])
    except Exception:
        return 0


async def get_recent_food_names(uid, days=3):
    # [FIX — DEV_LOG Entry 44] เดิมอ่าน view recent_food_history ที่ล็อก 3 วัน
    # ไว้ในตัว view — พารามิเตอร์ days ไม่มีผล ตอนนี้ query ตรงด้วย days จริง
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT food_name_th, MAX(eaten_at) AS last_eaten FROM food_logs
            WHERE line_user_id=$1 AND eaten_at > NOW() - make_interval(days => $2)
            GROUP BY food_name_th ORDER BY last_eaten
        """, uid, int(days))
    return [r["food_name_th"] for r in rows]
