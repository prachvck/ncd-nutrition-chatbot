"""
rag/rag_service.py
RAG module สำหรับ NCD Chatbot — pgvector + bge-m3

เดิมไฟล์นี้ใช้ ChromaDB (local file store) แต่เปลี่ยนมาใช้ pgvector แทน
เพราะ:
  1. ข้อมูลอยู่ใน PostgreSQL เดียวกับ users/foods/food_logs — ไม่ต้องดูแล
     ระบบ storage แยก
  2. Deploy บน Railway ไม่มีปัญหา ephemeral filesystem (Chroma เก็บไฟล์ลง
     disk ซึ่งหายเวลา container restart ถ้าไม่มี persistent volume)
  3. Filter ตามโรคของผู้ใช้ทำเป็น SQL WHERE ธรรมดา ไม่ต้องแยก logic
  4. ตรงกับสเปคที่วางแผนไว้ (bge-m3 embeddings + pgvector)

รันได้ทั้ง local Postgres (ติดตั้ง pgvector extension เอง) และ Supabase
(มี pgvector ให้พร้อมอยู่แล้ว) — โค้ดชุดเดียวกันไม่ต้องแก้ตอนย้าย cloud
เปลี่ยนแค่ DATABASE_URL ใน .env
"""
import asyncio
import logging
import os
from typing import Optional

# [FIX — DEV_LOG Entry 38] ทดสอบจริงเจอ "RAG query error: Your currently
# installed version of Keras is Keras 3, but this is not yet supported in
# Transformers" — เพราะเครื่องมี TensorFlow (ใช้กับ ANN) transformers เลยพยายาม
# โหลดฝั่ง TF ด้วย ทั้งที่ sentence-transformers ใช้ PyTorch — บอก transformers
# ให้ไม่ใช้ TF (ต้องตั้งก่อน import transformers/sentence_transformers)
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

from db.database import get_pool

log = logging.getLogger(__name__)

EMBED_MODEL_NAME = "BAAI/bge-m3"   # 1024-dim, multilingual (รองรับไทยดี)
EMBED_DIM = 1024

last_sources: list = []   # [Entry 49] เอกสารที่ดึงมาครั้งล่าสุด (ใช้ใน eval/eval_rag.py)
_embed_model = None   # โหลดครั้งเดียว ตอนเรียกใช้ครั้งแรก (lazy load)
_ready = False


def _get_embed_model():
    """โหลด bge-m3 แบบ lazy — โมเดลค่อนข้างใหญ่ (~2GB) ไม่อยาก block
    ตอน import module ครั้งแรกถ้ายังไม่ได้ใช้ RAG จริง"""
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        log.info(f"RAG: กำลังโหลด embedding model {EMBED_MODEL_NAME} (ครั้งแรกอาจใช้เวลาสักครู่)...")
        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
        log.info("RAG: โหลด embedding model สำเร็จ")
    return _embed_model


def _embed(texts: list[str]) -> list[list[float]]:
    """แปลงข้อความเป็น vector — normalize แล้วเพื่อให้ cosine similarity ใช้ inner product ได้"""
    model = _get_embed_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


async def _conn():
    """ยืม connection จาก pool กลางของแอป (เดียวกับที่ db/database.py ใช้)
    แล้ว register pgvector codec ให้ connection นี้รู้จัก type `vector`
    (asyncpg ไม่รู้จัก vector type ของ pgvector โดย default)"""
    from pgvector.asyncpg import register_vector
    pool = await get_pool()
    conn = await pool.acquire()
    await register_vector(conn)
    return conn


def _all_documents() -> list[dict]:
    """[DEV_LOG Entry 49] เอกสารทั้งหมด = ฐานความรู้หลัก (rag/ncd_knowledge.py)
    + ไฟล์สรุปเอกสารที่วางไว้ใน rag/sources/**/*.md (ถ้ามี front-matter ครบ)"""
    from rag.ncd_knowledge import NCD_DOCUMENTS
    from rag.source_loader import load_source_documents
    docs = list(NCD_DOCUMENTS)
    seen = {d["id"] for d in docs}
    for d in load_source_documents():
        if d["id"] not in seen:
            docs.append(d); seen.add(d["id"])
    return docs


def _kb_hash(docs: list[dict]) -> str:
    import hashlib, json
    h = hashlib.sha256()
    h.update(EMBED_MODEL_NAME.encode())
    for d in sorted(docs, key=lambda x: x["id"]):
        h.update(json.dumps([d["id"], d["disease"], d["topic"], d["content"],
                             d.get("source"), d.get("url")], ensure_ascii=False).encode())
    return h.hexdigest()[:16]


async def init_rag(force_reseed: bool = False):
    """
    เตรียม RAG ตอนเปิดแอป: โหลด embedding model + ตรวจว่าเอกสารใน DB ตรงกับ
    ฐานความรู้ในโค้ดหรือไม่ (เทียบ hash) — [FIX — DEV_LOG Entry 49] เดิม seed
    เฉพาะตอนตารางว่าง แก้เนื้อหาใน ncd_knowledge.py แล้ว DB ไม่อัปเดตตาม
    ตอนนี้ถ้า hash ไม่ตรง → ลบเอกสารเก่าแล้ว embed ใหม่ทั้งหมดอัตโนมัติ

    ต้องรัน db/rag_schema.sql (สร้าง extension + ตาราง) ก่อนครั้งแรก
    """
    global _ready
    pool = await get_pool()
    docs = _all_documents()
    kb_hash = _kb_hash(docs)

    async with pool.acquire() as conn:
        try:
            count = await conn.fetchval("SELECT COUNT(*) FROM rag_documents")
            await conn.execute("ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS url TEXT")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            stored = await conn.fetchval("SELECT value FROM rag_meta WHERE key='kb_hash'")
        except Exception as e:
            log.error(
                "RAG: ตาราง rag_documents ยังไม่มี — รัน `psql -f db/rag_schema.sql` ก่อน "
                f"(error: {e})"
            )
            _ready = False
            return

    # โหลด embedding model ตอนเปิดแอปเลย (Entry 38) — โหลดไม่ได้ = ปิด RAG
    try:
        await asyncio.to_thread(_get_embed_model)
    except Exception as e:
        log.error(f"RAG: โหลด embedding model ไม่สำเร็จ — ปิด RAG (แอปทำงานต่อได้): {e}")
        _ready = False
        return

    if count > 0 and stored == kb_hash and not force_reseed:
        log.info(f"RAG ready — เอกสาร {count} รายการ (ตรงกับฐานความรู้ปัจจุบัน {kb_hash})")
        _ready = True
        return

    log.info(f"RAG: ฐานความรู้เปลี่ยน ({stored} → {kb_hash}) — embed และ seed ใหม่ {len(docs)} รายการ...")
    try:
        vectors = await asyncio.to_thread(_embed, [d["content"].strip() for d in docs])
    except Exception as e:
        log.error(f"RAG: embed เอกสารไม่สำเร็จ — ปิด RAG (แอปทำงานต่อได้): {e}")
        _ready = False
        return

    conn = await _conn()
    try:
        async with conn.transaction():
            await conn.execute("DELETE FROM rag_documents")
            for doc, vec in zip(docs, vectors):
                await conn.execute(
                    """
                    INSERT INTO rag_documents (id, disease, topic, content, source, url, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    doc["id"], doc["disease"], doc["topic"], doc["content"].strip(),
                    doc.get("source") or "ไม่ระบุ", doc.get("url") or None, vec,
                )
            await conn.execute("""
                INSERT INTO rag_meta(key, value) VALUES('kb_hash', $1)
                ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
            """, kb_hash)
    finally:
        await pool.release(conn)

    log.info(f"RAG ready — seed เอกสารสำเร็จ {len(docs)} รายการ")
    _ready = True


async def query_rag(question: str, diseases: Optional[list[str]] = None,
                     n_results: int = 3) -> str:
    """
    ค้นหาเอกสารที่เกี่ยวข้องจาก pgvector ด้วย cosine similarity
    คืน string context สำหรับแนบใน prompt ก่อนส่งให้ LLM

    question : คำถามหรือ context ที่ต้องการค้น
    diseases : list โรคของ user เพื่อ filter (จะรวม 'general' เสมอ)
    n_results: จำนวน document ที่ต้องการ
    """
    if not _ready:
        log.warning("RAG ยังไม่ได้ init หรือตารางว่าง — ข้าม")
        return ""

    try:
        disease_names = {
            "diabetes":     "เบาหวาน",
            "hypertension": "ความดันโลหิตสูง",
            "heart":        "โรคหัวใจ",
            "ckd":          "โรคไต",
            "obesity":      "โรคอ้วน",
        }
        diseases_th = [disease_names.get(d, d) for d in (diseases or [])]
        query_text = f"{question} {' '.join(diseases_th)}".strip()

        # [FIX — Entry 38] embed เป็นงาน CPU หนัก — รันใน thread ไม่ให้บล็อก
        # event loop (เดิมบล็อกทั้งแอป ข้อความผู้ใช้อื่นค้างไปด้วย)
        [query_vec] = await asyncio.to_thread(_embed, [query_text])

        # [FIX — DEV_LOG Entry 51] eval_rag: ผู้ใช้ไม่มีโรคถามเรื่องทั่วไป (ไขมันรวมกี่ %)
        # แล้วไม่กรองเลย → ได้เอกสาร "เกณฑ์ระบบโรคหัวใจ" (ไขมัน 28%) มาตอบผิด — ตอนนี้
        # รวมโรคที่ "พูดถึงในคำถาม" ด้วย และถ้าไม่มีโรคเลยให้ค้นเฉพาะเอกสาร general
        diseases = sorted(set(diseases or []) | diseases_mentioned(question)) or None

        conn = await _conn()
        try:
            if diseases:
                disease_list = list(diseases) + ["general"]
                # [FIX — DEV_LOG Entry 30] เอกสารความดัน (ht_001/ht_002, DASH)
                # แนะนำให้ "เพิ่มโพแทสเซียม" (กล้วย ส้ม มะเขือเทศ) ซึ่งขัดกับ
                # เอกสารโรคไต (ckd_002: ให้เลี่ยงอาหารโพแทสเซียมสูง) — ถ้าผู้ใช้
                # เป็นไตด้วย ไม่ดึงเอกสารความดันมาให้ LLM (เอกสารไตครอบคลุม
                # การจำกัดโซเดียม ≤1,500mg อยู่แล้ว) ตรงกับ logic ใน
                # adjust_features_by_disease ที่ไม่บังคับ K ขั้นต่ำเมื่อเป็น CKD
                if "ckd" in disease_list:
                    disease_list = [d for d in disease_list if d != "hypertension"]
                rows = await conn.fetch(
                    """
                    SELECT id, content, topic, source, embedding <=> $1 AS distance
                    FROM rag_documents
                    WHERE disease = ANY($2::text[])
                    ORDER BY distance ASC
                    LIMIT $3
                    """,
                    query_vec, disease_list, n_results,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, content, topic, source, embedding <=> $1 AS distance
                    FROM rag_documents
                    WHERE disease = 'general'
                    ORDER BY distance ASC
                    LIMIT $2
                    """,
                    query_vec, n_results,
                )
        finally:
            await (await get_pool()).release(conn)

        if not rows:
            return ""

        context_parts = [
            f"[{r['topic']} — ที่มา: {r['source'] or 'ไม่ระบุ'}]\n{r['content'].strip()}"
            for r in rows
        ]
        global last_sources
        last_sources = [{"id": r["id"], "topic": r["topic"], "source": r["source"],
                         "distance": float(r["distance"])} for r in rows]
        return "\n\n".join(context_parts)

    except Exception as e:
        log.error(f"RAG query error: {e}")
        # [FIX — Entry 38] ถ้าโหลด/รัน embedding model ไม่ได้ ปิด RAG ไปเลย กัน
        # ทุกคำถามต้องรอโหลดโมเดลใหม่แล้วล้มซ้ำ (ช้า ~1 นาทีต่อคำถาม)
        if _embed_model is None:
            _disable_rag()
        return ""


_DISEASE_WORDS = {
    "diabetes": ("เบาหวาน", "น้ำตาลในเลือด", "อินซูลิน"),
    "hypertension": ("ความดัน",),
    "ckd": ("โรคไต", "ไตเสื่อม", "ไตวาย", "ฟอกไต", "เป็นไต", "ผู้ป่วยไต"),
    "heart": ("หัวใจ", "คอเลสเตอรอล"),
    "obesity": ("อ้วน", "ลดน้ำหนัก", "ลดความอ้วน", "น้ำหนักเกิน"),
}


def diseases_mentioned(text: str) -> set:
    """[Entry 51] โรคที่ถูกพูดถึงในคำถาม (เช่น ผู้ใช้ไม่มีโรคแต่ถามแทนพ่อแม่)"""
    t = text or ""
    return {d for d, words in _DISEASE_WORDS.items() if any(w in t for w in words)}


def _disable_rag():
    global _ready
    _ready = False


def is_ready() -> bool:
    return _ready
