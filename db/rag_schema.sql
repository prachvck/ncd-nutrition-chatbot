-- ══════════════════════════════════════════════════════════════════
-- RAG (Retrieval-Augmented Generation) — pgvector setup
-- รันไฟล์นี้ครั้งเดียวหลัง schema.sql (ต่อยอดจาก DB เดิม ไม่ลบของเก่า)
--   psql -d ncd_chatbot -f db/rag_schema.sql
-- ══════════════════════════════════════════════════════════════════

-- ── 1. Extension ─────────────────────────────────────────────────
-- ต้องมี pgvector ติดตั้งใน PostgreSQL ก่อน (local: ติดตั้งผ่าน package
-- manager เช่น `apt install postgresql-16-pgvector` หรือ build จาก
-- https://github.com/pgvector/pgvector — Supabase มี extension นี้ให้
-- อยู่แล้วโดยไม่ต้องติดตั้งเพิ่ม)
CREATE EXTENSION IF NOT EXISTS vector;


-- ── 2. TABLE: rag_documents ──────────────────────────────────────
--    เก็บ chunk ของเอกสารสุขภาพ (กรมอนามัย / สมาคมเบาหวานแห่งประเทศไทย /
--    WHO / DASH ฯลฯ) พร้อม embedding vector สำหรับ semantic search
--    embedding เป็น 1024 มิติ เพราะใช้โมเดล BAAI/bge-m3
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS rag_documents (
    id          TEXT            PRIMARY KEY,   -- เช่น 'dm_001'
    disease     TEXT            NOT NULL,       -- diabetes | hypertension | heart | ckd | obesity | general
    topic       TEXT            NOT NULL,       -- หัวข้อสั้นๆ อธิบายเนื้อหา
    content     TEXT            NOT NULL,       -- เนื้อหาเต็มของ chunk นี้
    source      TEXT,                           -- ที่มาเอกสาร เช่น 'กรมอนามัย 2561', 'WHO 2026'
    url         TEXT,                           -- [Entry 49] ลิงก์เอกสารต้นทาง
    embedding   vector(1024)    NOT NULL,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  rag_documents            IS 'ฐานความรู้สำหรับ RAG — chunk เอกสารสุขภาพ + embedding';
COMMENT ON COLUMN rag_documents.disease    IS 'ใช้ filter ผลลัพธ์ตามโรคของผู้ใช้';
COMMENT ON COLUMN rag_documents.source     IS 'ที่มาเอกสารจริง เพื่อให้ระบบอ้างอิงแหล่งข้อมูลได้ (ตามที่รายงานระบุไว้)';
COMMENT ON COLUMN rag_documents.embedding  IS 'bge-m3 dense embedding, 1024 dims, cosine similarity';

CREATE INDEX IF NOT EXISTS idx_rag_documents_disease ON rag_documents(disease);

-- [Entry 49] hash ของฐานความรู้ที่ seed ล่าสุด — init_rag เทียบแล้ว reseed เองถ้าเปลี่ยน
CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS url TEXT;

-- หมายเหตุ: ไม่สร้าง ivfflat index ตอนนี้เพราะจำนวนเอกสารยังน้อย (หลักสิบ-ร้อย)
-- sequential scan + cosine distance เร็วพอ ถ้าเอกสารโตเกิน ~5,000 แถวค่อยพิจารณา
-- เพิ่ม: CREATE INDEX ON rag_documents USING ivfflat (embedding vector_cosine_ops);


-- ── 3. ตรวจสอบว่าสร้างครบ ────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'rag_documents' AND table_schema = 'public'
    ) THEN
        RAISE EXCEPTION 'ตาราง rag_documents ยังไม่ถูกสร้าง';
    ELSE
        RAISE NOTICE '✓ pgvector extension + ตาราง rag_documents พร้อมใช้งาน';
        RAISE NOTICE '✓ ขั้นตอนต่อไป: รัน python -m rag.rag_service เพื่อ seed เอกสารเริ่มต้น';
    END IF;
END;
$$;
