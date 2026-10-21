"""
scripts/add_cnn_aliases.py — DEV_LOG Entry 74

ทดสอบจริง: พิมพ์ชื่อเมนูกับถ่ายรูปเมนูเดียวกันได้คนละ food_id 18/100 label
(เช่น พิมพ์ "ไข่เจียว" ได้ไข่เจียวฝรั่ง 154 kcal แต่รูปได้ไข่เจียวไทย 361 kcal/100 g,
"ต้มยำ" ได้ต้มยำไก่ แต่รูปได้ต้มยำกุ้ง) — ผิดข้อตกลงใน CLAUDE.md ว่าพิมพ์/รูปต้องได้ food_id เดียวกัน
→ เพิ่ม alias ชื่อไทยของทุก label CNN ชี้ไป food_id ตาม cnn_label_food_mapping.csv
+ ชื่อทั่วไปที่ค้นแล้วได้ผลแปลก (ต้มจืด → ข้าวราดต้มจืด, นม → นมเย็น ฯลฯ)

รัน (จาก root chabot/): python scripts/add_cnn_aliases.py   (รันซ้ำได้)
"""
import pandas as pd

AP = "food_aliases.csv"
NOTE_CNN = "Entry 74 ชื่อ label CNN = food_id เดียวกับรูป"
NOTE_GEN = "Entry 74 ชื่อทั่วไป"
GENERIC = {  # alias: food_id
    "ต้มจืด": 90101, "แกงจืดเต้าหู้": 90101,
    "นม": 21156, "นมจืด": 21156, "นมสด": 21156,
    "ข้าวสวย": 21783, "ข้าวเปล่า": 21783, "ข้าว": 21783,
    "ข้าวกล้อง": 20005, "ข้าวเหนียว": 20010,
    "ไข่ต้ม": 21944, "ไข่ดาว": 22068,
}

al = pd.read_csv(AP, encoding="utf-8-sig")
al = al[~al.note.astype(str).str.startswith("Entry 74")]
have = set(al.alias.astype(str).str.replace(" ", ""))
mp = pd.read_csv("cnn_label_food_mapping.csv", encoding="utf-8-sig")
add = []
for r in mp.itertuples():
    a = str(r.Dish_Name_Thai).strip()
    if a.replace(" ", "") not in have and str(r.food_id).isdigit():
        add.append({"alias": a, "food_id": int(r.food_id), "note": NOTE_CNN}); have.add(a.replace(" ", ""))
for a, fid in GENERIC.items():
    if a.replace(" ", "") not in have:
        add.append({"alias": a, "food_id": fid, "note": NOTE_GEN}); have.add(a)
out = pd.concat([al, pd.DataFrame(add)], ignore_index=True)
out.to_csv(AP, index=False, encoding="utf-8-sig")
print(f"เพิ่ม alias {len(add)} รายการ (รวม {len(out)})")
