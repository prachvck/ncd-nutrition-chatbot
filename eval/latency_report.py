"""
eval/latency_report.py — สรุปเวลาตอบของแชทบอทจากการใช้งานจริง [DEV_LOG Entry 44]

ข้อมูลมาจากตาราง interaction_logs (แอปบันทึกให้อัตโนมัติทุกข้อความ):
  server_ms = เวลาตั้งแต่เริ่มประมวลผลจนส่ง reply ให้ LINE เสร็จ
  e2e_ms    = เวลาตั้งแต่ผู้ใช้กดส่ง (timestamp ของ LINE) จนส่ง reply เสร็จ
  llm_ms    = เวลาที่ใช้รอ LLM (Typhoon) รวมทุกครั้งในข้อความนั้น

รัน:  python -m eval.latency_report [--days 7] [--csv out.csv]
"""
import os, sys, argparse, asyncio, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np


def _stats(v):
    v = np.array([x for x in v if x is not None], dtype=float)
    if not len(v):
        return None
    return {"n": len(v), "mean": v.mean(), "median": np.median(v),
            "p90": np.percentile(v, 90), "p95": np.percentile(v, 95), "max": v.max(),
            "under_3s": (v < 3000).mean(), "under_5s": (v < 5000).mean()}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--csv", default=None)
    a = ap.parse_args()
    from db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = [dict(r) for r in await conn.fetch("""
            SELECT route, intent, server_ms, e2e_ms, llm_ms, error, created_at
            FROM interaction_logs WHERE created_at > NOW() - make_interval(days => $1)
        """, a.days)]
    if not rows:
        print("ยังไม่มีข้อมูลใน interaction_logs (ลองใช้งานแชทบอทใน LINE ก่อน)")
        return
    print(f"ข้อความทั้งหมด {len(rows)} ข้อความ ใน {a.days} วันล่าสุด, error {sum(r['error'] for r in rows)}")
    groups = {"(ทั้งหมด)": rows}
    for r in rows:
        key = (r["route"] or "unknown").split(":")[-1] if r["route"] else "unknown"
        groups.setdefault(key, []).append(r)
    hdr = f"{'route':22s} {'n':>4s} {'mean':>7s} {'median':>7s} {'p90':>7s} {'p95':>7s} {'<3s':>6s} {'<5s':>6s}  llm-mean"
    out = []
    for metric in ("server_ms", "e2e_ms"):
        print(f"\n── {metric} (มิลลิวินาที) ──\n{hdr}")
        for g, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            s = _stats([r[metric] for r in rs])
            if not s:
                continue
            llm = _stats([r["llm_ms"] for r in rs])
            print(f"{g:22s} {s['n']:4d} {s['mean']:7.0f} {s['median']:7.0f} {s['p90']:7.0f} "
                  f"{s['p95']:7.0f} {s['under_3s']:6.0%} {s['under_5s']:6.0%}  {llm['mean'] if llm else 0:7.0f}")
            out.append({"metric": metric, "route": g, **{k: round(float(v), 3) for k, v in s.items()}})
    if a.csv:
        with open(a.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
            w.writeheader(); w.writerows(out)
        print(f"\nบันทึก {a.csv}")


if __name__ == "__main__":
    asyncio.run(main())
