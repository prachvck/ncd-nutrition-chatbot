"""
rag/test_rag.py
สคริปต์ทดสอบ RAG แบบ standalone — ไม่ต้องเปิด LINE/ngrok/FastAPI เลย
ใช้เช็คว่า pgvector + bge-m3 ทำงานถูกต้องก่อนไปต่อ

วิธีรัน (จาก root ของ chabot/):
    python -m rag.test_rag

เตรียมก่อนรัน:
    1. ติดตั้ง pgvector extension ให้ PostgreSQL แล้ว
    2. รัน: psql -d <ชื่อ_db> -f db/rag_schema.sql
    3. pip install -r requirements.txt
    4. ตั้งค่า DATABASE_URL ใน .env ให้ชี้ไปที่ DB ที่รัน rag_schema.sql แล้ว
"""
import asyncio
from rag.rag_service import init_rag, query_rag, is_ready


async def main():
    print("=" * 60)
    print("1) init_rag() — seed เอกสารเข้า pgvector (ครั้งแรกจะโหลด bge-m3 ~2GB)")
    print("=" * 60)
    await init_rag()
    print(f"   is_ready() = {is_ready()}")

    if not is_ready():
        print("\n[FAIL] RAG ไม่พร้อมใช้งาน — เช็คว่ารัน db/rag_schema.sql แล้วหรือยัง")
        return

    test_cases = [
        # (คำถาม, โรคของ user)
        ("เบาหวานกินทุเรียนได้ไหม", ["diabetes"]),
        ("ความดันสูงกินอะไรได้บ้าง", ["hypertension"]),
        ("อยากลดน้ำหนักควรกินยังไง", ["obesity"]),
    ]

    print("\n" + "=" * 60)
    print("2) query_rag() — ทดสอบค้นหาเอกสารจริง")
    print("=" * 60)
    for question, diseases in test_cases:
        print(f"\n--- คำถาม: {question} (โรค: {diseases}) ---")
        context = await query_rag(question, diseases=diseases, n_results=2)
        if context:
            print(context)
        else:
            print("[ไม่พบเอกสาร — ลองเช็คว่า seed สำเร็จหรือคำถามไม่ตรงกับหมวดโรคที่มี]")

    print("\n" + "=" * 60)
    print("เสร็จแล้ว — ถ้าเห็น context ข้างบนแปลว่า pgvector + bge-m3 ทำงานถูกต้อง")
    print("ขั้นต่อไป: รัน `uvicorn app.main:app --reload` แล้วลองถามในแชท LINE จริง")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
