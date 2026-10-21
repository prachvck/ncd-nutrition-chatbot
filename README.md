# อิ่มจัง — LINE Chatbot แนะนำอาหารสำหรับผู้ป่วย NCD

ปริญญานิพนธ์ คณะเทคโนโลยีสารสนเทศ สจล. — แนะนำอาหารรายมื้อตามโรคประจำตัว
(เบาหวาน ความดัน โรคหัวใจ โรคไต โรคอ้วน) ผ่าน LINE

```
ข้อความ LINE ─► /webhook (FastAPI, ตอบ 200 ทันที + ประมวลผลเบื้องหลัง, กัน event ซ้ำ)
               ├─ Rich Menu → จับข้อความตรงตัว
               └─ อื่นๆ → LLM intent (Typhoon) → keyword fallback / ถามผู้ใช้ถ้าไม่มั่นใจ
แนะนำอาหาร: targets (BMR/TDEE/โรค) → ANN cluster + Disease Override → hard filter
            (เพดานโรค + fail-safe) → KNN + MMR (pool ≤20) → LinUCB เลือก 3 จาน → Flex
บันทึกการกิน: ปุ่ม "กินเมนูนี้" / พิมพ์เอง / รูป (CNN) → ยืนยัน → food_logs → reward Bandit
ถามแคล: ค้นหาเมนู + เช็คเกณฑ์โรค + RAG (pgvector + bge-m3) → Typhoon ตอบ
```

## โครงสร้าง

```
app/        main.py (webhook/handlers), llm_service.py, line_flex.py, line_reply.py,
            state.py, metrics.py (เวลาตอบ), cnn_service.py (จุดเสียบโมเดล CNN)
ml/         pipeline.py — NCDModel: targets, KMeans→ANN, hard filter, KNN+MMR, ค้นหาเมนู
bandit/     linucb.py (LinUCB), service.py (policy, reward, เก็บโมเดลใน DB)
rag/        ncd_knowledge.py (25 เอกสารอ้างอิงแหล่งทางการ), rag_service.py, source_loader.py
db/         database.py (asyncpg + auto-migration), schema.sql, rag_schema.sql
eval/       ชุดทดสอบ + สคริปต์วัดผล (ดูด้านล่าง), results/
scripts/    สคริปต์เติม/แก้ข้อมูลอาหาร (รันซ้ำได้, ที่มาอยู่ในคอลัมน์ mineral_source)
data/       raw/ (ข้อมูลดิบจาก scrape/Project 1), intermediate/ (ไฟล์ระหว่างทาง)
profile/templates/form.html — หน้า LIFF กรอกโปรไฟล์สุขภาพ (หน้าเว็บเดียวของระบบ)
foods_master_v2.csv — ข้อมูลอาหารที่ใช้จริง (2,591 แถว, 736 จาน)
cnn_label_food_mapping.csv — สัญญา CNN label (THFOOD-100) → food_id
```

## ติดตั้ง/รัน (dev)

```bash
pip install -r requirements.txt
cp .env.example .env            # ใส่ LINE secret/token, TYPHOON_API_KEY, DATABASE_URL
docker compose up -d            # Postgres + pgvector ที่พอร์ต 5433
psql -h 127.0.0.1 -p 5433 -U postgres -d ncd_chatbot -f db/schema.sql
psql -h 127.0.0.1 -p 5433 -U postgres -d ncd_chatbot -f db/rag_schema.sql
python import_foods.py --prune  # นำ foods_master_v2.csv เข้าตาราง foods
uvicorn app.main:app --port 8000
ngrok http 8000                 # Webhook URL: https://<ngrok>/webhook
```

ตารางเสริม (recommendation_items, interaction_logs, bandit_model, processed_events,
food_image_predictions) ถูกสร้างอัตโนมัติตอนเปิดแอป RAG embed เอกสารใหม่เองเมื่อเนื้อหาเปลี่ยน

## วัดผล (eval/)

| สคริปต์ | วัดอะไร | ต้องใช้ |
|---|---|---|
| `python -m eval.eval_intent` | accuracy / macro-F1 ของ intent (136 ประโยค) LLM vs keyword | TYPHOON_API_KEY |
| `python -m eval.eval_meal_parse` | LLM แยกข้อความบันทึกการกิน (50 ประโยค) | TYPHOON_API_KEY |
| `python -m eval.eval_diversity [--variant X]` | ความหลากหลายของเมนู (ILD/หมวด/ไม่ซ้ำ) | — |
| `python -m eval.eval_food_search` | Top-1/Top-3 การค้นหาเมนูจากชื่อ (45 คำค้น) | — |
| `python -m eval.eval_safety` | % เมนูที่แนะนำผ่านเกณฑ์โรค (72 โปรไฟล์ × 3 มื้อ) | — |
| `python -m eval.simulate_bandit` | acceptance rate / regret: random vs KNN vs LinUCB | — |
| `python -m eval.eval_rag` | hallucination ก่อน/หลัง RAG + retrieval recall@3 (25 คำถาม) | DB + API key |
| `python -m eval.latency_report` | เวลาตอบจากการใช้งานจริง (mean/median/p90/p95) | DB |

## ตั้งค่าเพิ่มเติม (.env)

- `BANDIT_POLICY=linucb|knn|ab` — `ab` แบ่งผู้ใช้ครึ่งต่อครึ่งเพื่อเทียบตอนทดสอบกับคนจริง
- `CNN_MODEL_PATH` — วางไฟล์โมเดล THFOOD-100 แล้วฟีเจอร์ส่งรูปจะเปิดเอง
- `REMINDERS_ENABLED=1` — ลูปแจ้งเตือนมื้อ/สรุปรายสัปดาห์ (ผู้ใช้เปิดเองด้วย "เปิดแจ้งเตือน")
- `REQUIRE_LIFF_AUTH=1` — ฟอร์ม LIFF ต้องยืนยันตัวตนด้วย LINE access token
