"""
eval/eval_intent.py — วัดความแม่นยำการจำแนกเจตนา (intent) [DEV_LOG Entry 44]

รัน (จากโฟลเดอร์ chabot):
    python -m eval.eval_intent                 # LLM (Typhoon) + keyword เทียบกัน
    python -m eval.eval_intent --mode keyword  # keyword อย่างเดียว (ไม่ต้องใช้ API)

ชุดทดสอบ: eval/intent_testset.csv (text,label) — 136 ประโยค 7 คลาส
(recommend, log_meal, ask_calorie, summary, edit_profile, help, unknown)
ตั้งใจเขียนให้ไม่ตรง keyword (สำนวนพูดจริง/อังกฤษ/สะกดไม่ตรง) เพื่อวัดการ generalize

รายงาน:
  - accuracy, macro-F1, F1 รายคลาส, confusion matrix
  - แบบ "ระบบจริง": LLM conf ≥ 0.65 → ส่งตรง / ต่ำกว่า → ถามผู้ใช้ (abstain)
    รายงาน coverage (สัดส่วนที่ส่งตรง) + accuracy เฉพาะที่ส่งตรง
  - เวลาเฉลี่ยต่อการจำแนก (ms)
ผลเก็บที่ eval/results/
"""
import os, sys, csv, json, time, argparse, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)   # [Entry 51] ต้องโหลด TYPHOON_API_KEY ก่อน import llm_service
from sklearn.metrics import accuracy_score, f1_score, classification_report, confusion_matrix

HERE = os.path.dirname(os.path.abspath(__file__))
THRESHOLD = 0.65
LABELS = ["recommend", "log_meal", "ask_calorie", "summary", "edit_profile", "help", "unknown"]


def load_set(path):
    with open(path, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r["text"].strip()]


def run_keyword(rows):
    from app.state import classify_intent
    out = []
    for r in rows:
        t = time.perf_counter()
        pred = classify_intent(r["text"])
        out.append({"pred": pred, "conf": 1.0, "ms": (time.perf_counter() - t) * 1000})
    return out


def run_llm(rows):
    from app.llm_service import classify_intent_llm
    out = []
    for i, r in enumerate(rows, 1):
        t = time.perf_counter()
        res = classify_intent_llm(r["text"])
        out.append({"pred": res["intent"], "conf": res["confidence"],
                    "ms": (time.perf_counter() - t) * 1000})
        print(f"\r  LLM {i}/{len(rows)}", end="", flush=True)
    print()
    if all(x["conf"] == 0.0 and x["pred"] == "unknown" for x in out):
        raise SystemExit("เรียก LLM ไม่สำเร็จเลยสักข้อ (เช็ค TYPHOON_API_KEY ใน .env / อินเทอร์เน็ต) — ไม่บันทึกผล")
    return out


def report(name, rows, preds, outdir):
    y = [r["label"] for r in rows]
    p = [x["pred"] for x in preds]
    acc = accuracy_score(y, p)
    f1 = f1_score(y, p, labels=LABELS, average="macro", zero_division=0)
    summary = {"mode": name, "n": len(rows), "accuracy": round(acc, 4), "macro_f1": round(f1, 4),
               "mean_ms": round(sum(x["ms"] for x in preds) / len(preds), 1)}
    if name == "llm":
        routed = [(yy, xx) for yy, xx in zip(y, preds) if xx["pred"] != "unknown" and xx["conf"] >= THRESHOLD]
        summary["threshold"] = THRESHOLD
        summary["coverage"] = round(len(routed) / len(rows), 4)
        summary["accuracy_when_routed"] = round(
            sum(yy == xx["pred"] for yy, xx in routed) / len(routed), 4) if routed else None
        failed = sum(1 for x in preds if x["conf"] == 0.0 and x["pred"] == "unknown")
        summary["llm_call_failures"] = failed
    print(f"\n=== {name} ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(classification_report(y, p, labels=LABELS, zero_division=0))
    cm = confusion_matrix(y, p, labels=LABELS)
    print("confusion matrix (แถว=จริง, คอลัมน์=ทาย):", LABELS)
    for lab, row in zip(LABELS, cm):
        print(f"  {lab:13s} {[int(v) for v in row]}")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    with open(os.path.join(outdir, f"intent_{name}_{stamp}.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["text", "label", "pred", "conf", "ms", "correct"])
        for r, x in zip(rows, preds):
            w.writerow([r["text"], r["label"], x["pred"], x["conf"], round(x["ms"], 1), r["label"] == x["pred"]])
    summary["per_class"] = classification_report(y, p, labels=LABELS, zero_division=0, output_dict=True)
    summary["confusion_matrix"] = {"labels": LABELS, "matrix": cm.tolist()}
    with open(os.path.join(outdir, f"intent_{name}_{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["both", "llm", "keyword"], default="both")
    ap.add_argument("--testset", default=os.path.join(HERE, "intent_testset.csv"))
    a = ap.parse_args()
    rows = load_set(a.testset)
    outdir = os.path.join(HERE, "results"); os.makedirs(outdir, exist_ok=True)
    if a.mode in ("both", "keyword"):
        report("keyword", rows, run_keyword(rows), outdir)
    if a.mode in ("both", "llm"):
        report("llm", rows, run_llm(rows), outdir)


if __name__ == "__main__":
    main()
