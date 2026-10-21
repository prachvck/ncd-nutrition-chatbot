"""
eval/eval_rag.py — วัด hallucination ก่อน/หลังใช้ RAG (รายงานบทที่ 5.4 ข้อ 3) [DEV_LOG Entry 49]

วิธีวัด:
  ชุดคำถาม eval/rag_testset.csv (25 ข้อ) แต่ละข้อมี
    - gold          : ข้อเท็จจริงอ้างอิงจากเอกสารทางการ (WHO/NIDDK/KDOQI/AHA/DASH/กรมอนามัย)
    - must_not      : วลีที่ถ้าโผล่ในคำตอบ = ให้คำแนะนำผิด/อันตรายแน่นอน (คั่นด้วย |)
    - expected_docs : id เอกสารที่ RAG ควรดึงมา (ใช้วัด retrieval recall@3)
  ตอบแต่ละข้อ 2 แบบด้วยฟังก์ชันเดียวกับแชทบอทจริง (answer_calorie_question):
    A) ไม่มี RAG (rag_context="")   B) มี RAG (query_rag top-3)
  แล้วตัดสินด้วย:
    1) rule-based: เจอวลี must_not = hallucination แน่นอน
    2) LLM-as-judge (Typhoon, temperature 0): เทียบคำตอบกับ gold แยกเป็นข้อกล่าวอ้าง
       นับ CONTRADICTED (ขัดกับ gold) — ข้อกล่าวอ้างที่ gold ไม่ได้พูดถึงไม่นับว่าผิด
  hallucination rate = สัดส่วนคำตอบที่มี CONTRADICTED ≥ 1 หรือโดน must_not

ข้อจำกัด (ควรเขียนในรายงาน): judge เป็น LLM ตัวเดียวกับที่ตอบ อาจลำเอียง — สุ่ม 20-30%
ของผลมาให้คนตรวจซ้ำ (ไฟล์ CSV ที่ได้มีคอลัมน์ human_check ว่างไว้ให้กรอก)

รัน (ต้องเปิด Postgres + มี TYPHOON_API_KEY):
    python -m eval.eval_rag
    python -m eval.eval_rag --no-judge     # rule-based อย่างเดียว
"""
import os, sys, csv, json, re, asyncio, argparse, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(override=True)

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = {"age": 60, "gender": "male", "weight_kg": 68, "height_cm": 165,
           "activity_level": 2, "goal": ""}

JUDGE_SYSTEM = """คุณเป็นผู้ตรวจความถูกต้องของคำตอบด้านโภชนาการ ตอบเป็น JSON เท่านั้น
ให้แยกคำตอบเป็นข้อกล่าวอ้างด้านสุขภาพ/ตัวเลข แล้วเทียบกับ "ข้อเท็จจริงอ้างอิง"
- SUPPORTED: ตรงกับข้อเท็จจริงอ้างอิง
- CONTRADICTED: ขัดแย้งกับข้อเท็จจริงอ้างอิง (เช่น ตัวเลขต่างกัน แนะนำตรงข้าม)
- NOT_IN_REFERENCE: ข้อเท็จจริงอ้างอิงไม่ได้พูดถึง
รูปแบบ: {"supported": n, "contradicted": n, "not_in_reference": n,
"contradicted_claims": ["..."]}"""


def judge(answer: str, gold: str) -> dict:
    from app.llm_service import _chat
    raw = _chat(JUDGE_SYSTEM, f"ข้อเท็จจริงอ้างอิง:\n{gold}\n\nคำตอบที่ต้องตรวจ:\n{answer}",
                max_tokens=600, temperature=0.0)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else {"error": raw[:200]}
    except Exception:
        return {"error": raw[:200]}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-judge", action="store_true")
    a = ap.parse_args()

    from db.database import init_db
    from rag.rag_service import init_rag, query_rag, is_ready
    import rag.rag_service as R
    from app.llm_service import answer_calorie_question
    from app.state import extract_food_keyword, is_generic_food_term
    from ml.pipeline import NCDModel

    await init_db()
    await init_rag()
    if not is_ready():
        print("RAG ไม่พร้อม (เช็ค Postgres/pgvector/bge-m3) — หยุด"); return
    model = NCDModel(csv_path=os.getenv("CSV_PATH", "foods_master_v2.csv"))

    with open(os.path.join(HERE, "rag_testset.csv"), encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    out, agg = [], {"no_rag": {"halluc": 0, "rule": 0, "contra": 0},
                    "rag": {"halluc": 0, "rule": 0, "contra": 0}}
    hit = 0
    for i, r in enumerate(rows, 1):
        diseases = [d for d in r["diseases"].split("|") if d]
        user = {**PROFILE, "diseases": diseases}
        targets = model.compute_user_targets(user)
        ctx_user = {**user, "meal_limit_kcal": targets["meal_limit"]["energy_kcal"]}
        kw = extract_food_keyword(r["question"])
        foods = [] if is_generic_food_term(kw) else model.search_food(kw, 3)
        suit = model.evaluate_food_limits(foods[0], set(diseases), targets["meal_limit"]) if foods else None
        rag_ctx = await query_rag(r["question"], diseases=diseases, n_results=3)
        got = [s["id"] for s in R.last_sources]
        exp = [d for d in r["expected_docs"].split("|") if d]
        recall_hit = any(e in got for e in exp)
        hit += recall_hit
        row = {"id": r["id"], "question": r["question"], "diseases": r["diseases"],
               "retrieved": "|".join(got), "retrieval_hit": recall_hit, "gold": r["gold"]}
        for mode, ctx in (("no_rag", ""), ("rag", rag_ctx)):
            ans = await asyncio.to_thread(answer_calorie_question, foods, ctx_user, r["question"], ctx, suit)
            bad = [p for p in r["must_not"].split("|") if p and p in ans]
            j = {} if a.no_judge else await asyncio.to_thread(judge, ans, r["gold"])
            contra = int(j.get("contradicted", 0) or 0) if isinstance(j, dict) else 0
            halluc = bool(bad) or contra > 0
            agg[mode]["halluc"] += halluc; agg[mode]["rule"] += bool(bad); agg[mode]["contra"] += contra
            row.update({f"{mode}_answer": ans, f"{mode}_must_not_hits": "|".join(bad),
                        f"{mode}_judge": json.dumps(j, ensure_ascii=False),
                        f"{mode}_hallucination": halluc})
        row["human_check"] = ""
        out.append(row)
        print(f"  {i}/{len(rows)} {r['id']} hit={recall_hit} "
              f"no_rag={row['no_rag_hallucination']} rag={row['rag_hallucination']}")

    n = len(rows)
    summary = {
        "n_questions": n,
        "retrieval_recall_at_3": round(hit / n, 4),
        "hallucination_rate_no_rag": round(agg["no_rag"]["halluc"] / n, 4),
        "hallucination_rate_rag": round(agg["rag"]["halluc"] / n, 4),
        "must_not_violations_no_rag": agg["no_rag"]["rule"],
        "must_not_violations_rag": agg["rag"]["rule"],
        "contradicted_claims_no_rag": agg["no_rag"]["contra"],
        "contradicted_claims_rag": agg["rag"]["contra"],
        "judge": "none (rule-based only)" if a.no_judge else "Typhoon LLM-as-judge vs gold",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    with open(os.path.join(HERE, "results", f"rag_eval_{stamp}.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    with open(os.path.join(HERE, "results", f"rag_eval_{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
