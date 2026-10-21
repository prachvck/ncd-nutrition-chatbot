"""
Scraper for the INMU Thai Food Composition Database (Thai FCD)
https://inmu.mahidol.ac.th/thaifcd/

This is the official database published by the Institute of Nutrition,
Mahidol University (INMU) — the same institute the project's original
nutritionaddsugar.csv data traces back to. Much higher quality / more
authoritative than the calforlife.com community source (scripts/scrape_calforlife.py),
so this should be the primary way to expand the food database.

Site structure (found by inspecting the site's own AJAX calls, no API docs
exist):
  1. GET .../foodsearch/food_group_result?food_group_id=<id>&...
     -> HTML fragment with the full list of foods in that group (id, Thai
        name, English name, scientific name, food code). Confirmed this is
        NOT paginated in practice (total_page=1 even for a ~300-item group
        like D - Vegetables), so one request per group is enough.
  2. GET .../foodsearch/food_name_result?selected_id=<food id>&selected_dbcode=STD&...
     -> HTML fragment with the full per-100g nutrient table for that food.

Both endpoints are plain GET, no auth, no CSRF token needed (confirmed empty
ci_csrf_token= works) — same-origin/XHR headers below are set defensively in
case that ever changes.

Philosophy (per project owner's explicit instruction, same as the calforlife
scraper): COLLECT EVERYTHING FIRST, CLEAN LATER. Never silently drop a row
that parsed successfully — flag it with a reason in _flag / _flag_reason
instead. Only genuinely unparseable pages go to a separate .unparsed.csv.

IMPORTANT — run this locally, not inside Claude's sandbox:
    inmu.mahidol.ac.th is not on Claude's sandbox network allowlist (curl/
    requests from that sandbox get blocked at the proxy). This script must
    be run on your own machine, which has normal internet access.

Usage:
    pip install requests beautifulsoup4
    python scripts/scrape_thaifcd.py
    python scripts/scrape_thaifcd.py --groups A,D,F      # only some groups
    python scripts/scrape_thaifcd.py --limit-per-group 10  # quick test run
    python scripts/scrape_thaifcd.py --delay 0.5         # be gentler on the server

Output:
    thaifcd_foods_raw.csv          - every food that parsed successfully
    thaifcd_foods_raw.csv.unparsed.csv - list/detail pages that failed to parse, with reason
    .thaifcd_seen_ids.txt          - resume marker (safe to delete to start over)
"""
import argparse
import csv
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://inmu.mahidol.ac.th/thaifcd"
LIST_URL = BASE + "/foodsearch/food_group_result"
DETAIL_URL = BASE + "/foodsearch/food_name_result"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE + "/foodsearch/food_group",
}

# food group letter -> (food_group_id, English label), taken directly from
# the <select> options on https://inmu.mahidol.ac.th/thaifcd/foodsearch/food_group
FOOD_GROUPS = {
    "A": (70, "Cereals and their products"),
    "B": (71, "Starchy roots, tubers and their products"),
    "C": (73, "Legums, nuts, seeds and their products"),
    "D": (74, "Vegetables and their products"),
    "E": (75, "Fruits and their products"),
    "F": (76, "Meat, other animals and their products"),
    "G": (77, "Finfish, shellfish, other aquatic animals and their products"),
    "H": (78, "Eggs and their products"),
    "J": (79, "Milk and its products"),
    "K": (80, "Fats, oils and their products"),
    "M": (81, "Sugars, syrup and confectionery"),
    "N": (72, "Spices, herbs, condiments and other seasonings"),
    "Q": (82, "Beverages: nonalcoholic"),
    "S": (83, "Fast foods: franchise foods"),
    "T": (84, "Mixed foods: ready-to-eat"),
    "U": (85, "Miscellaneous"),
    "Z": (69, "Branded Food Products"),
}

# Nutrient row label (exact text in the left column of the detail table) ->
# column name matching nutritionaddsugar.csv's existing schema.
NUTRIENT_MAP = {
    "Energy, by calculation": "energy_kcal",
    "Moisture": "water_g",
    "Protein, total": "protein_g",
    "Fat, total": "fat_g",
    "Carbohydrate, available": "carb_available_g",
    "Dietary fibre": "dietary_fiber_g",
    "Ash": "ash_g",
    "Calcium": "calcium_mg",
    "Phosphorus": "phosphorus_mg",
    "Magnesium": "magnesium_mg",
    "Sodium": "sodium_mg",
    "Potassium": "potassium_mg",
    "Iron": "iron_mg",
    "Copper": "copper_mg",
    "Zinc": "zinc_mg",
    "b-carotene": "betacarotene_ug",
    "Retinol": "retinol_ug",
    "Vitamin A; retinol activity equivalent": "vitamin_a_rae_ug",
    "Thiamin": "thiamin_mg",
    "Riboflavin": "riboflavin_mg",
    "Niacin": "niacin_mg",
    "Vitamin C": "vitamin_c_mg",
    # This DB reports "Alpha-tocopherol" rather than a combined "Vitamin E" —
    # it's the standard proxy for vitamin E, but flagged with a note so it's
    # easy to double check during the cleaning pass.
    "Alpha-tocopherol": "vitamin_e_mg",
}

# This DB version doesn't have an "Iodine" row at all (older Thai FCD /
# nutritionaddsugar.csv schema has iodine_ug) — always left blank for scraped
# rows. Listed here just so it's obvious this is intentional, not a bug.
NO_MATCH_SCHEMA_COLS = ["iodine_ug"]

# Nutrients this DB has that our schema doesn't. Kept (not dropped) as
# extra_* columns so nothing collected is lost; a later cleaning pass can
# decide whether any of these are worth folding into the schema.
EXTRA_NUTRIENT_LABELS = [
    "Selenium",
    "Vitamin D (D2+D3)",
    "Vitamin B-6, total",
    "Folate, total",
    "Vitamin B-12",
    "Sugars, total",
    "Fatty acids, total saturated",
    "Fatty acids, total monounsaturated",
    "Fatty acids, total polyunsaturated",
    "Fatty acids, total omega-3 polyunsaturated",
    "Fatty acids, total omega-6 polyunsaturated",
    "Cholesterol",
]


def _extra_col_name(label: str) -> str:
    return "extra_" + re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


EXTRA_COLS = [_extra_col_name(l) for l in EXTRA_NUTRIENT_LABELS]
EXTRA_LABEL_TO_COL = dict(zip(EXTRA_NUTRIENT_LABELS, EXTRA_COLS))

SCHEMA_COLS = [
    "food_id", "food_code", "food_name_th", "food_name_en", "scientific_name",
    "food_group_letter", "food_group_name",
    "energy_kcal", "water_g", "protein_g", "fat_g", "carb_available_g",
    "dietary_fiber_g", "ash_g", "calcium_mg", "phosphorus_mg", "magnesium_mg",
    "sodium_mg", "potassium_mg", "iron_mg", "copper_mg", "zinc_mg",
    "iodine_ug",
    "betacarotene_ug", "retinol_ug", "vitamin_a_rae_ug",
    "thiamin_mg", "riboflavin_mg", "niacin_mg", "vitamin_c_mg", "vitamin_e_mg",
]

OUT_COLS = SCHEMA_COLS + EXTRA_COLS + ["_flag", "_flag_reason", "_source_url"]
UNPARSED_COLS = ["stage", "url", "context", "reason"]

NUM_RE = re.compile(r"-?\d+(\.\d+)?")


def clean_num(text: str):
    """'-' / '<0.01' / '1,234' style cells -> float or None. Never raises."""
    if text is None:
        return None
    t = text.strip().replace(",", "")
    if t in ("", "-", "–", "N/A", "na", "NA"):
        return None
    t = t.lstrip("<>~=").strip()
    m = NUM_RE.search(t)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse_food_list(html: str, group_letter: str, group_id: int):
    """Returns list of dicts: id, dbcode, name_th, name_en, scientific_name, food_code."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("tbody#tbody_food_nutrients") or soup.select("tbody")
    out = []
    table = soup.find("table")
    if table is None:
        return out
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        link = tds[1].find("a")
        if link is None:
            continue
        href = link.get("href", "")
        m = re.search(r"[?&]id=(\d+)", href)
        dbm = re.search(r"[?&]dbcode=([A-Za-z0-9]+)", href)
        if not m:
            continue
        out.append({
            "id": m.group(1),
            "dbcode": dbm.group(1) if dbm else "STD",
            "name_th": tds[1].get_text(strip=True),
            "name_en": tds[2].get_text(strip=True),
            "scientific_name": tds[3].get_text(strip=True),
            "food_code": tds[4].get_text(strip=True),
            "group_letter": group_letter,
            "group_id": group_id,
        })
    return out


def parse_food_detail(html: str) -> dict:
    """Returns a dict of schema/extra column -> value (float or None). Empty
    dict means the nutrient table itself couldn't be found (real parse failure)."""
    soup = BeautifulSoup(html, "html.parser")
    tbody = soup.find("tbody", id="tbody_food_nutrients")
    if tbody is None:
        return {}
    result = {}
    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        label = tds[0].get_text(strip=True)
        value_cell = tds[2].get_text(strip=True)
        value = clean_num(value_cell)
        if label in NUTRIENT_MAP:
            result[NUTRIENT_MAP[label]] = value
        elif label in EXTRA_LABEL_TO_COL:
            result[EXTRA_LABEL_TO_COL[label]] = value
    return result


def flag_reason(row: dict) -> str:
    """Non-destructive sanity check — never causes a row to be dropped, only
    annotated, per the collect-everything-then-clean-once policy."""
    core = ["energy_kcal", "protein_g", "fat_g", "carb_available_g"]
    if all(row.get(c) is None for c in core):
        return "ไม่มีข้อมูล macro หลักเลย (energy/protein/fat/carb ว่างหมด)"
    energy = row.get("energy_kcal")
    if energy is not None and energy > 900:
        return f"พลังงานต่อ 100g สูงผิดปกติ ({energy})"
    if not (row.get("food_name_th") or row.get("food_name_en")):
        return "ไม่มีชื่ออาหารทั้งไทยและอังกฤษ"
    return ""


def load_seen(path: Path) -> set:
    if not path.exists():
        return set()
    return set(path.read_text(encoding="utf-8").splitlines())


def pd_read_max_food_id(csv_path: Path):
    """Return the highest food_id already present in an existing output CSV,
    or None if the file has no data rows. Named to make the resume-counter
    fix above self-explanatory; deliberately uses the stdlib csv module
    (not pandas) since this script has no other pandas dependency."""
    max_id = None
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                fid = int(row["food_id"])
            except (KeyError, ValueError, TypeError):
                continue
            if max_id is None or fid > max_id:
                max_id = fid
    return max_id


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--groups", default="", help="Comma-separated group letters to scrape, e.g. A,D,F. Default: all.")
    ap.add_argument("--output", default="data/raw/thaifcd_foods_raw.csv")
    ap.add_argument("--delay", type=float, default=0.4, help="Seconds to wait between requests.")
    ap.add_argument("--start-id", type=int, default=20000, help="First synthetic food_id to assign (avoid colliding with existing 11001-11253 and calforlife's 12000+ range).")
    ap.add_argument("--limit-per-group", type=int, default=0, help="For quick testing: only scrape the first N foods per group (0 = no limit).")
    args = ap.parse_args()

    groups = list(FOOD_GROUPS.keys())
    if args.groups.strip():
        wanted = {g.strip().upper() for g in args.groups.split(",")}
        groups = [g for g in groups if g in wanted]
        missing = wanted - set(groups)
        if missing:
            print(f"WARNING: unknown group letters ignored: {sorted(missing)}", file=sys.stderr)

    out_path = Path(args.output)
    unparsed_path = Path(str(args.output) + ".unparsed.csv")
    seen_path = Path(".thaifcd_seen_ids.txt")

    seen = load_seen(seen_path)
    write_header = not out_path.exists()
    write_header_unparsed = not unparsed_path.exists()

    session = requests.Session()
    session.headers.update(HEADERS)

    # Resume-safe food_id counter: if the output file already has rows (e.g.
    # a previous run crashed partway through), continue after the highest
    # food_id already written instead of restarting at --start-id — starting
    # over caused a real collision the first time this script was used (two
    # different foods ended up sharing food_id 20000-20009 because run #2
    # restarted the counter at --start-id while resuming past already-seen
    # foods from run #1's partial output).
    next_id = args.start_id
    if out_path.exists():
        try:
            existing = pd_read_max_food_id(out_path)
            if existing is not None and existing >= next_id:
                next_id = existing + 1
        except Exception as e:
            print(f"WARNING: couldn't determine max food_id from existing {out_path} ({e}); "
                  f"falling back to --start-id={args.start_id}. If this output file already has "
                  f"rows, check for food_id collisions before importing.", file=sys.stderr)
    n_saved = n_flagged = n_unparsed = n_skipped_seen = 0

    with out_path.open("a", newline="", encoding="utf-8-sig") as f_out, \
         unparsed_path.open("a", newline="", encoding="utf-8-sig") as f_unparsed, \
         seen_path.open("a", encoding="utf-8") as f_seen:

        writer = csv.DictWriter(f_out, fieldnames=OUT_COLS)
        if write_header:
            writer.writeheader()
        unparsed_writer = csv.DictWriter(f_unparsed, fieldnames=UNPARSED_COLS)
        if write_header_unparsed:
            unparsed_writer.writeheader()

        for letter in groups:
            group_id, group_name = FOOD_GROUPS[letter]
            print(f"\n=== Group {letter} - {group_name} (food_group_id={group_id}) ===")

            params = {
                "order_fields": "", "order_directions": "",
                "page_no": 1, "dummy_page_no": 1, "status": "A",
                "food_group_id": group_id, "mode": "food_group_result",
                "ci_csrf_token": "", "_": int(time.time() * 1000),
            }
            try:
                resp = session.get(LIST_URL, params=params, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"  FAILED to fetch food list for group {letter}: {e}")
                unparsed_writer.writerow({
                    "stage": "list", "url": f"{LIST_URL}?food_group_id={group_id}",
                    "context": f"group {letter}", "reason": str(e),
                })
                n_unparsed += 1
                continue

            foods = parse_food_list(resp.text, letter, group_id)
            print(f"  found {len(foods)} foods in list")
            if not foods:
                unparsed_writer.writerow({
                    "stage": "list", "url": f"{LIST_URL}?food_group_id={group_id}",
                    "context": f"group {letter}", "reason": "list table empty or unparseable",
                })
                n_unparsed += 1
                continue

            if args.limit_per_group:
                foods = foods[: args.limit_per_group]

            for food in foods:
                key = f"{food['dbcode']}:{food['id']}"
                if key in seen:
                    n_skipped_seen += 1
                    continue

                detail_params = {
                    "order_fields": "", "order_directions": "",
                    "page_no": 1, "dummy_page_no": 1, "status": "A",
                    "selected_name": food["name_en"] or food["name_th"],
                    "selected_id": food["id"],
                    "selected_dbcode": food["dbcode"],
                    "food_group_id": group_id,
                    "food_name": food["name_en"] or food["name_th"],
                    "mode": "food_group_result",
                    "ci_csrf_token": "",
                    "_": int(time.time() * 1000),
                }
                detail_url_full = f"{DETAIL_URL}?selected_id={food['id']}&selected_dbcode={food['dbcode']}"
                try:
                    dresp = session.get(DETAIL_URL, params=detail_params, timeout=20)
                    dresp.raise_for_status()
                except requests.RequestException as e:
                    unparsed_writer.writerow({
                        "stage": "detail", "url": detail_url_full,
                        "context": food["name_en"] or food["name_th"],
                        "reason": f"request failed: {e}",
                    })
                    n_unparsed += 1
                    f_seen.write(key + "\n")
                    seen.add(key)
                    time.sleep(args.delay)
                    continue

                nutrients = parse_food_detail(dresp.text)
                if not nutrients:
                    unparsed_writer.writerow({
                        "stage": "detail", "url": detail_url_full,
                        "context": food["name_en"] or food["name_th"],
                        "reason": "nutrient table not found / empty response",
                    })
                    n_unparsed += 1
                    f_seen.write(key + "\n")
                    seen.add(key)
                    time.sleep(args.delay)
                    continue

                # Compute the flag reason on the raw (float/None) values,
                # before converting None -> "" for CSV writing below —
                # flag_reason() does numeric comparisons that break on "".
                reason_check = dict(nutrients)
                reason_check["food_name_th"] = food["name_th"]
                reason_check["food_name_en"] = food["name_en"]
                reason = flag_reason(reason_check)

                row = {c: "" for c in OUT_COLS}
                row["food_id"] = next_id
                row["food_code"] = food["food_code"]
                row["food_name_th"] = food["name_th"]
                row["food_name_en"] = food["name_en"]
                row["scientific_name"] = food["scientific_name"]
                row["food_group_letter"] = letter
                row["food_group_name"] = group_name
                row["_source_url"] = f"https://inmu.mahidol.ac.th/thaifcd/foodsearch/food_name/?dbcode={food['dbcode']}&food_group_id={group_id}&id={food['id']}&name={food['name_en']}"
                for k, v in nutrients.items():
                    row[k] = v if v is not None else ""
                row["_flag"] = "สงสัย" if reason else ""
                row["_flag_reason"] = reason
                if reason:
                    n_flagged += 1

                writer.writerow(row)
                n_saved += 1
                next_id += 1
                f_seen.write(key + "\n")
                seen.add(key)
                time.sleep(args.delay)

            print(f"  group {letter} done. running totals: saved={n_saved} flagged={n_flagged} unparsed={n_unparsed} skipped(already seen)={n_skipped_seen}")

    print(f"\n=== DONE ===\nsaved={n_saved}  flagged={n_flagged}  unparsed={n_unparsed}  skipped(resume)={n_skipped_seen}")
    print(f"output: {out_path}")
    print(f"unparsed log: {unparsed_path}")
    print(f"resume marker: {seen_path} (delete this file to force a full re-scrape)")


if __name__ == "__main__":
    main()
