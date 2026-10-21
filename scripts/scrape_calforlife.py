"""
scripts/scrape_calforlife.py
=============================================================================
ดึงข้อมูลโภชนาการอาหารจาก calforlife.com (ข้อมูลที่ผู้ใช้เว็บกรอกเอง —
ไม่ใช่แหล่งที่ได้รับการรับรองทางการแพทย์ เหมาะใช้เสริมฐานข้อมูล "แคล/สารอาหาร
ต่อเมนู" สำหรับแนะนำเมนู/ตอบคำถามแคล เท่านั้น — ไม่ใช้เป็นเอกสารอ้างอิงของ
RAG ที่ต้องการแหล่งที่มาน่าเชื่อถือแบบ กรมอนามัย/สมาคมเบาหวาน/WHO)

วิธีใช้:
    pip install requests beautifulsoup4
    python scripts/scrape_calforlife.py --start-page 1 --end-page 400

[แนวทาง] สคริปต์นี้แค่ "ดึงข้อมูลดิบ" ให้ครบที่สุดเท่าที่ parse ได้ —
ไม่ตัดขยะทิ้งตอนดึง (เพราะ logic กรองอัตโนมัติเคยตัดสินผิดพลาด ตัดของจริง
ทิ้งไปด้วย) แต่จะติด "flag" + เหตุผลไว้ในคอลัมน์ _flag / _flag_reason ให้
เปิดดูและกรองเอาเองทีหลังด้วยตา/Excel/pandas ก่อนค่อยเอาไปรวมเข้า
nutritionaddsugar.csv

ผลลัพธ์ 2 ไฟล์:
    1. calforlife_foods_raw.csv       — ทุกรายการที่ parse ตัวเลขได้สำเร็จ
       (คอลัมน์ตรงกับ nutritionaddsugar.csv + _flag, _flag_reason ท้ายสุด)
    2. calforlife_foods_raw.csv.unparsed.csv — รายการที่ดึงข้อมูลไม่ได้เลย
       (โหลดหน้าไม่สำเร็จ/หารูปแบบประโยคสรุปไม่เจอ) เก็บ url+ชื่อ+เหตุผลไว้
       เผื่ออยากไปเช็คเองทีหลังว่าทำไมถึงพลาด

ทำอะไรบ้าง:
    1. ไล่หน้ารายชื่ออาหาร /th/calories/food/page{N} เก็บลิงก์ + ชื่อเมนู
    2. เปิดแต่ละลิงก์ ดึงพลังงาน/โปรตีน/คาร์บ/ไขมัน/โซเดียม/โพแทสเซียม/
       ใยอาหาร ต่อหน่วยบริโภคที่เว็บระบุ แล้วแปลงเป็นค่าต่อ 100 กรัม
       (nutritionaddsugar.csv เก็บเป็นค่าต่อ 100 กรัมเหมือนกัน)
    3. รองรับ resume — รันซ้ำแล้วข้ามรายการที่ scrape ไปแล้ว (เก็บ slug
       ที่เจอแล้วไว้ในไฟล์ .seen_slugs.txt คู่กับ output)

**ไฟล์นี้ scrape จริงตอนรัน ไม่ได้ auto-import เข้า DB ให้เอง** — เปิด
CSV ที่ได้มาตรวจ/กรอง _flag ก่อน แล้วค่อยรวมเข้า nutritionaddsugar.csv เอง
ก่อนรัน import_foods.py
=============================================================================
"""

import argparse
import csv
import os
import re
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://www.calforlife.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# คอลัมน์ให้ตรงกับ nutritionaddsugar.csv เป๊ะ (ตัวที่ดึงไม่ได้ปล่อยว่าง)
# + _flag / _flag_reason ท้ายสุด ไว้กรองขยะทีหลังเอง (ไม่ได้ตัดทิ้งตอน scrape)
DATA_COLS = [
    "food_id", "food_name_th", "food_name_en",
    "energy_kcal", "water_g", "protein_g", "fat_g", "carb_available_g",
    "dietary_fiber_g", "ash_g",
    "calcium_mg", "phosphorus_mg", "magnesium_mg", "sodium_mg", "potassium_mg",
    "iron_mg", "copper_mg", "zinc_mg", "iodine_ug",
    "betacarotene_ug", "retinol_ug", "vitamin_a_rae_ug",
    "thiamin_mg", "riboflavin_mg", "niacin_mg", "vitamin_c_mg", "vitamin_e_mg",
]
OUT_COLS = DATA_COLS + ["_flag", "_flag_reason", "_source_url"]
UNPARSED_COLS = ["url", "display_name", "reason"]

SUMMARY_RE = re.compile(
    r"ในปริมาณ\s*(?P<label>.+?)\s*"
    r"มีพลังงานทั้งหมด\s*(?P<kcal>[\d.]+)\s*กิโลแคลอรี่\s*,\s*"
    r"โปรตีน\s*(?P<protein>[\d.]+)\s*กรัม\s*,\s*"
    r"คาร์โบไฮเดรต\s*(?P<carb>[\d.]+)\s*กรัม\s*,\s*"
    r"ไขมัน\s*(?P<fat>[\d.]+)\s*กรัม"
)
# หาตัวเลข+"g" ที่ไหนก็ได้ใน label — ครอบคลุมทั้ง "100g" ตรงๆ และ "1 large (50 g)"
GRAMS_IN_LABEL_RE = re.compile(r"([\d.]+)\s*g\b")
SODIUM_RE    = re.compile(r"โซเดียม\D{0,15}?([\d.]+)\s*mg")
POTASSIUM_RE = re.compile(r"โพแทสเซียม\D{0,15}?([\d.]+)\s*mg")
FIBER_RE     = re.compile(r"ใยอาหาร\D{0,15}?([\d.]+)\s*g")

JUNK_NAME_RE = re.compile(r"^\d+$|^(.)\1*$")  # ตัวเลขล้วน หรือตัวอักษรซ้ำตัวเดียว


def fetch(url: str, retries: int = 3, delay: float = 0.6) -> str | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return None
        except requests.RequestException as e:
            print(f"  [warn] fetch fail ({attempt+1}/{retries}) {url}: {e}")
        time.sleep(delay * (attempt + 1))
    return None


def get_listing_links(html: str) -> list[tuple[str, str]]:
    """คืน [(url, display_name), ...] จากหน้ารายชื่ออาหาร"""
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/th/calories/" not in href or "/th/calories/food/" in href:
            continue
        if href in seen:
            continue
        text = a.get_text(strip=True)
        if not text:
            continue
        seen.add(href)
        out.append((href, text))
    return out


def parse_food_page(html: str) -> tuple[dict | None, str | None]:
    """คืน (row_dict, None) ถ้าสำเร็จ หรือ (None, เหตุผล) ถ้า parse ไม่ได้"""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)

    m = SUMMARY_RE.search(text)
    if not m:
        return None, "ไม่พบประโยคสรุปโภชนาการในหน้า (รูปแบบเว็บอาจเปลี่ยน หรือเมนูข้อมูลไม่ครบ)"
    g_match = GRAMS_IN_LABEL_RE.search(m.group("label"))
    if not g_match:
        return None, f"หาน้ำหนักกรัมใน label ไม่เจอ (label='{m.group('label')}')"
    grams = float(g_match.group(1))
    if grams <= 0:
        return None, "น้ำหนักกรัมเป็น 0 หรือติดลบ"

    kcal    = float(m.group("kcal"))
    protein = float(m.group("protein"))
    carb    = float(m.group("carb"))
    fat     = float(m.group("fat"))

    factor = 100.0 / grams
    row = {
        "energy_kcal":      round(kcal * factor, 2),
        "protein_g":        round(protein * factor, 2),
        "fat_g":            round(fat * factor, 2),
        "carb_available_g": round(carb * factor, 2),
    }
    sod = SODIUM_RE.search(text)
    pot = POTASSIUM_RE.search(text)
    fib = FIBER_RE.search(text)
    row["sodium_mg"]       = round(float(sod.group(1)) * factor, 2) if sod else ""
    row["potassium_mg"]    = round(float(pot.group(1)) * factor, 2) if pot else ""
    row["dietary_fiber_g"] = round(float(fib.group(1)) * factor, 2) if fib else ""
    return row, None


def flag_reason(name_en: str, name_th: str, row: dict) -> str:
    """คืนเหตุผลที่ 'น่าสงสัยว่าเป็นขยะ' (ไม่ตัดทิ้ง แค่ติด flag) หรือ '' ถ้าดูปกติดี"""
    main_name = (name_th or name_en or "").strip()
    if len(main_name) < 2 or JUNK_NAME_RE.match(main_name):
        return f"ชื่อดูน่าสงสัย ('{main_name}')"
    if row["energy_kcal"] == 0 and row["protein_g"] == 0 \
            and row["fat_g"] == 0 and row["carb_available_g"] == 0:
        return "พลังงาน/โปรตีน/ไขมัน/คาร์บ เป็น 0 ทั้งหมด"
    if row["energy_kcal"] > 950:
        return f"พลังงานต่อ 100g สูงผิดปกติ ({row['energy_kcal']})"
    return ""


def split_name(display: str) -> tuple[str, str]:
    """'Egg, whole, raw, fresh - ไข่, ไก่, ทั้งใบ' -> (en, th)"""
    if " - " in display:
        en, th = display.split(" - ", 1)
        return en.strip(), th.strip()
    return "", display.strip()


def load_seen(seen_path: str) -> set[str]:
    if not os.path.exists(seen_path):
        return set()
    with open(seen_path, encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def main():
    ap = argparse.ArgumentParser(description="Scrape calforlife.com food nutrition data (raw, no filtering)")
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--end-page",   type=int, default=400)
    ap.add_argument("--output",     default="data/raw/calforlife_foods_raw.csv")
    ap.add_argument("--delay",      type=float, default=0.5, help="วินาที ระหว่างแต่ละ request")
    ap.add_argument("--start-id",   type=int, default=12000, help="food_id เริ่มต้น (กันชนกับของเดิม 11001-11253)")
    args = ap.parse_args()

    unparsed_path = args.output + ".unparsed.csv"
    seen_path     = args.output + ".seen_slugs.txt"
    seen          = load_seen(seen_path)
    next_id       = args.start_id

    if os.path.exists(args.output):
        with open(args.output, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if rows:
            next_id = max(int(r["food_id"]) for r in rows) + 1
        write_header = False
    else:
        write_header = True

    out_f  = open(args.output, "a", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(out_f, fieldnames=OUT_COLS)
    if write_header:
        writer.writeheader()

    write_unparsed_header = not os.path.exists(unparsed_path)
    unparsed_f = open(unparsed_path, "a", newline="", encoding="utf-8-sig")
    unparsed_writer = csv.DictWriter(unparsed_f, fieldnames=UNPARSED_COLS)
    if write_unparsed_header:
        unparsed_writer.writeheader()

    seen_f = open(seen_path, "a", encoding="utf-8")

    n_saved, n_flagged, n_unparsed = 0, 0, 0

    for page in range(args.start_page, args.end_page + 1):
        list_url = f"{BASE}/th/calories/food/page{page}"
        html = fetch(list_url, delay=args.delay)
        time.sleep(args.delay)
        if not html:
            print(f"[page {page}] fetch ล้มเหลว ข้าม")
            continue

        links = get_listing_links(html)
        if not links:
            print(f"[page {page}] ไม่พบรายการอาหาร (อาจหมดข้อมูลจริงแล้ว)")
            continue

        for href, display in links:
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            if slug in seen:
                continue
            seen.add(slug)

            detail_html = fetch(href, delay=args.delay)
            time.sleep(args.delay)
            if not detail_html:
                unparsed_writer.writerow({"url": href, "display_name": display, "reason": "โหลดหน้าไม่สำเร็จ"})
                unparsed_f.flush()
                n_unparsed += 1
                seen_f.write(slug + "\n")
                continue

            parsed, err = parse_food_page(detail_html)
            if parsed is None:
                unparsed_writer.writerow({"url": href, "display_name": display, "reason": err})
                unparsed_f.flush()
                n_unparsed += 1
                seen_f.write(slug + "\n")
                continue

            name_en, name_th = split_name(display)
            reason = flag_reason(name_en, name_th, parsed)

            row = {c: "" for c in OUT_COLS}
            row.update(parsed)
            row["food_id"]      = next_id
            row["food_name_th"] = name_th or name_en
            row["food_name_en"] = name_en
            row["_flag"]        = "สงสัย" if reason else ""
            row["_flag_reason"] = reason
            row["_source_url"]  = href
            writer.writerow(row)
            out_f.flush()
            seen_f.write(slug + "\n")
            seen_f.flush()
            next_id += 1
            n_saved += 1
            if reason:
                n_flagged += 1

        print(f"[page {page}] สะสมแล้ว: บันทึก {n_saved} (สงสัยว่าขยะ {n_flagged} รายการ อยู่ในไฟล์เดียวกัน), parse ไม่ได้ {n_unparsed}")

    out_f.close()
    unparsed_f.close()
    seen_f.close()
    print(f"\nเสร็จแล้ว — บันทึกทั้งหมด {n_saved} รายการ → {args.output}")
    print(f"  ในนั้นติด flag ว่าน่าสงสัย {n_flagged} รายการ (ดูคอลัมน์ _flag / _flag_reason)")
    print(f"parse ไม่ได้เลย {n_unparsed} รายการ → {unparsed_path}")


if __name__ == "__main__":
    main()
