"""
eval/cuq_score.py — คิดคะแนนแบบสอบถาม (CUQ + ความพึงพอใจรายฟีเจอร์) จาก CSV ของ Google Forms [DEV_LOG Entry 65]

แบบสอบถาม: docs/QUESTIONNAIRE.md — คอลัมน์หาจากเลขนำหน้าคำถาม (CUQ1. … CUQ16., F1. …, E1. …)
คะแนน CUQ ตามคู่มือ Ulster University:
  CUQ = ((ผลรวมข้อคี่ − 8) + (40 − ผลรวมข้อคู่)) / 64 × 100   (0–100, ค่าอ้างอิง ≈ 68)

รัน:  python -m eval.cuq_score responses.csv [--out eval/results/cuq_scores.csv]
"""
import re, sys, csv, argparse, statistics as st


def _num(v):
    m = re.match(r"\s*(\d)", str(v or ""))
    return int(m.group(1)) if m else None


def cronbach_alpha(rows: list[list[int]]) -> float | None:
    """rows = คำตอบรายคน (กลับคะแนนข้อลบแล้ว)"""
    if len(rows) < 2:
        return None
    k = len(rows[0])
    item_var = sum(st.pvariance([r[i] for r in rows]) for i in range(k))
    total_var = st.pvariance([sum(r) for r in rows])
    return None if total_var == 0 else k / (k - 1) * (1 - item_var / total_var)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    with open(a.csv, encoding="utf-8-sig") as f:
        data = list(csv.DictReader(f))
    if not data:
        print("ไฟล์ว่าง"); return
    cols = {}
    for h in data[0]:
        m = re.match(r"\s*(CUQ|F|E)\s*(\d+)\s*\.", h, re.I)
        if m:
            cols[(m.group(1).upper(), int(m.group(2)))] = h
    cuq_cols = [cols.get(("CUQ", i)) for i in range(1, 17)]
    if None in cuq_cols:
        miss = [i + 1 for i, c in enumerate(cuq_cols) if c is None]
        print(f"หาคอลัมน์ CUQ ไม่ครบ (ขาดข้อ {miss}) — ตรวจว่าคำถามขึ้นต้นด้วย 'CUQ1.' … 'CUQ16.'"); return

    scores, adjusted, out = [], [], []
    for r in data:
        v = [_num(r[c]) for c in cuq_cols]
        if None in v:
            continue
        odd, even = sum(v[0::2]), sum(v[1::2])
        s = ((odd - 8) + (40 - even)) / 64 * 100
        scores.append(s)
        adjusted.append([x if i % 2 == 0 else 6 - x for i, x in enumerate(v)])
        out.append({"respondent": r.get(next((h for h in r if h.startswith("A2")), ""), ""),
                    "cuq": round(s, 1)})

    print(f"ผู้ตอบ {len(data)} คน, คิด CUQ ได้ {len(scores)} คน")
    if scores:
        print(f"\nCUQ (0–100): เฉลี่ย {st.mean(scores):.1f}"
              + (f" ± {st.stdev(scores):.1f}" if len(scores) > 1 else "")
              + f" | มัธยฐาน {st.median(scores):.1f} | ต่ำสุด {min(scores):.1f} | สูงสุด {max(scores):.1f}")
        print(f"สูงกว่าค่าอ้างอิง 68: {sum(s > 68 for s in scores)}/{len(scores)} คน")
        alpha = cronbach_alpha(adjusted)
        if alpha is not None:
            print(f"Cronbach's alpha (16 ข้อ, กลับคะแนนข้อลบแล้ว): {alpha:.3f}  (≥0.7 = เชื่อถือได้)")
        print("\nรายข้อ (เฉลี่ย 1–5; ข้อคู่ = ด้านลบ ยิ่งต่ำยิ่งดี)")
        for i, c in enumerate(cuq_cols, 1):
            vals = [x for x in (_num(r[c]) for r in data) if x is not None]
            print(f"  CUQ{i:<2d} {'+' if i % 2 else '−'} {st.mean(vals):.2f}  {c[:60]}")

    for grp, name in (("F", "ความพึงพอใจรายฟีเจอร์"), ("E", "ภาพรวม")):
        keys = sorted(k for k in cols if k[0] == grp)
        if not keys:
            continue
        print(f"\n{name} (เฉลี่ย 1–5)")
        for k in keys:
            vals = [x for x in (_num(r[cols[k]]) for r in data) if x is not None]
            if vals:
                print(f"  {grp}{k[1]:<2d} {st.mean(vals):.2f} ± {st.stdev(vals) if len(vals) > 1 else 0:.2f}"
                      f"  (n={len(vals)})  {cols[k][:60]}")

    if a.out and out:
        with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["respondent", "cuq"])
            w.writeheader(); w.writerows(out)
        print(f"\nบันทึก → {a.out}")


if __name__ == "__main__":
    main()
