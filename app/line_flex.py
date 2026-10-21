"""
app/line_flex.py  —  Phase 2
สร้าง Flex Message สำหรับเมนูแนะนำและสรุปโภชนาการ
"""

MEAL_LABELS = ["มื้อเช้า", "มื้อเที่ยง", "มื้อเย็น"]


def build_meal_flex(meals: list, result: dict, options_for: str | None = None) -> dict:
    """
    options_for: [DEV_LOG Entry 32] ถ้าระบุ (เช่น "มื้อเช้า") = การ์ดทุกใบเป็น
    "ตัวเลือก" ของมื้อเดียวกัน — หัวการ์ดเป็น "มื้อเช้า · ตัวเลือกที่ 1" ปุ่มเป็น
    "กินเมนูนี้" และกดใบไหนก็บันทึกเป็นมื้อนั้น (เดิมการ์ด 3 ใบ = เช้า/เที่ยง/เย็น)
    """
    bubbles = []
    for i, meal in enumerate(meals):
        if options_for:
            label = options_for
            header = f"{options_for} · ตัวเลือกที่ {i + 1}"
            button = "กินเมนูนี้"
        else:
            label = meal.get("meal_label") or (
                MEAL_LABELS[meal.get("meal_no", 1) - 1]
                if meal.get("meal_no") else "เมนูแนะนำ"
            )
            header, button = label, f"กิน{label}นี้"
        bubbles.append(_meal_bubble(meal, label, header=header, button_label=button))

    alt = (f"เมนูแนะนำ{options_for} {len(meals)} ตัวเลือก" if options_for
           else f"เมนูแนะนำ {len(meals)} มื้อ")
    return {
        "type": "flex",
        "altText": alt,
        "contents": {"type": "carousel", "contents": bubbles},
    }


def _meal_bubble(meal: dict, label: str, header: str | None = None,
                 button_label: str | None = None) -> dict:
    header = header or label
    button_label = button_label or f"กิน{label}นี้"
    name   = meal.get("food_name_th", "")
    # [FIX — DEV_LOG Entry 10] เมนู "กับข้าวอย่างเดียว" ถูกบวกโภชนาการข้าวสวย
    # เข้าไปแล้วตั้งแต่ ml/pipeline.py — บอกผู้ใช้ตรงๆ ในชื่อที่แสดง กันสับสน
    # ว่าทำไมแคล/ปริมาณสูงกว่าที่คิด (ไม่ได้มีแค่กับอย่างเดียว)
    if meal.get("_includes_rice"):
        name = f"{name} + ข้าวสวย"
    # [FIX — DEV_LOG Entry 31] ระบบเลือกขนาดจานได้แล้ว (เล็ก/ปกติ/ใหญ่) — บอก
    # ผู้ใช้บนการ์ด และส่งขนาดไปกับปุ่ม "กิน" ให้บันทึกปริมาณเดียวกัน
    portion = meal.get("_portion", "normal") or "normal"
    portion_th = {"small": "จานเล็ก", "large": "จานใหญ่"}.get(portion, "")
    display_name = f"{name} ({portion_th})" if portion_th else name
    kcal   = meal.get("energy_kcal", 0)
    carb   = meal.get("carb_available_g", 0)
    prot   = meal.get("protein_g", 0)
    fat    = meal.get("fat_g", 0)
    sodium = meal.get("sodium_mg", 0)
    serving= meal.get("_serving_g", 300)

    lim    = meal.get("meal_limit", {})
    lim_e  = lim.get("energy_kcal", 0)
    pct    = int(kcal / lim_e * 100) if lim_e > 0 else 0
    pct_str= f"{pct}% ของ limit" if lim_e > 0 else ""

    # meal_type จาก label
    meal_type_map = {"มื้อเช้า": "breakfast", "มื้อเที่ยง": "lunch", "มื้อเย็น": "dinner"}
    meal_type = meal_type_map.get(label, "unknown")

    # ข้อความสำหรับปุ่ม "กิน" — format: __eat__:food_id:portion[:r<item_id>]:name:meal_label
    # [DEV_LOG Entry 44] r<item_id> = id ใน recommendation_items ให้รู้ว่าผู้ใช้
    # เลือกการ์ดใบไหนจากรอบแนะนำไหน (ใช้เป็น reward ของ Bandit)
    food_id = meal.get("food_id") or 0
    rid     = f"r{meal['_rec_item_id']}:" if meal.get("_rec_item_id") else ""
    eat_msg = f"__eat__:{food_id}:{portion}:{rid}{name}:{label}"[:300]

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": "#f0f9f4", "paddingAll": "14px",
            "contents": [
                {"type": "text", "text": header, "size": "xs",
                 "color": "#888888", "weight": "bold"},
                {"type": "text", "text": display_name, "size": "md",
                 "weight": "bold", "wrap": True, "color": "#1a1a1a"},
                {"type": "text", "text": pct_str, "size": "xs",
                 "color": "#1D9E75"} if pct_str else {"type": "filler"},
            ],
        },
        "body": {
            "type": "box", "layout": "vertical",
            "spacing": "sm", "paddingAll": "14px",
            "contents": [
                _row("พลังงาน", f"{kcal:.0f} kcal", "#e85d04"),
                _row("คาร์บ",   f"{carb:.1f} g"),
                _row("โปรตีน",  f"{prot:.1f} g"),
                _row("ไขมัน",   f"{fat:.1f} g"),
                _row("โซเดียม", f"{sodium:.0f} mg"),
                {"type": "text", "text": f"ปริมาณ {serving} g/มื้อ",
                 "size": "xs", "color": "#aaaaaa", "margin": "md"},
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "spacing": "sm", "paddingAll": "12px",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#1D9E75",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": button_label,
                        "data": eat_msg,
                        "displayText": f"{button_label} ({name})"[:300],
                    },
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "อื่นๆ (แนะนำใหม่)",
                        "text": "แนะนำเมนู",
                    },
                },
            ],
        },
    }


def _row(label: str, value: str, color: str = "#333333") -> dict:
    return {
        "type": "box", "layout": "horizontal",
        "contents": [
            {"type": "text", "text": label, "size": "sm",
             "color": "#666666", "flex": 3},
            {"type": "text", "text": value, "size": "sm",
             "color": color, "weight": "bold", "align": "end", "flex": 2},
        ],
    }


def build_summary_flex(today: dict, budget: dict, diseases=None, dashboard_url: str | None = None) -> dict:
    total_kcal = float(today.get("total_energy_kcal", 0) or 0)
    lim_kcal   = budget.get("energy_kcal", {}).get("limit", 1)
    pct        = min(int(total_kcal / lim_kcal * 100), 100) if lim_kcal else 0
    count      = int(today.get("meal_count", 0) or 0)

    col_labels = {
        "energy_kcal":      "พลังงาน",
        "carb_available_g": "คาร์บ",
        "protein_g":        "โปรตีน",
        "fat_g":            "ไขมัน",
        "sodium_mg":        "โซเดียม",
    }
    # [DEV_LOG Entry 36] ผู้ป่วยไตต้องเห็นโพแทสเซียม/ฟอสฟอรัสด้วย
    if "ckd" in (diseases or []):
        col_labels["potassium_mg"]  = "โพแทสเซียม"
        col_labels["phosphorus_mg"] = "ฟอสฟอรัส"
    rows = [_summary_row(label, budget.get(col, {}))
            for col, label in col_labels.items()]

    return {
        "type": "flex",
        "altText": f"สรุปโภชนาการวันนี้ {total_kcal:.0f}/{lim_kcal:.0f} kcal",
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box", "layout": "vertical",
                "backgroundColor": "#1D9E75", "paddingAll": "16px",
                "contents": [
                    {"type": "text", "text": "สรุปโภชนาการวันนี้",
                     "color": "#ffffff", "weight": "bold", "size": "md"},
                    {"type": "text",
                     "text": f"{total_kcal:.0f} / {lim_kcal:.0f} kcal ({pct}%)",
                     "color": "#d4f1e4", "size": "lg", "weight": "bold"},
                    {"type": "text", "text": f"บันทึกแล้ว {count} มื้อ",
                     "color": "#d4f1e4", "size": "xs"},
                ],
            },
            "body": {
                "type": "box", "layout": "vertical",
                "spacing": "sm", "paddingAll": "16px",
                "contents": rows,
            },
            # [DEV_LOG Entry 61] ปุ่มเปิดหน้าสรุปย้อนหลัง 10 วัน + วิเคราะห์รายสัปดาห์ (LIFF)
            **({"footer": {
                "type": "box", "layout": "vertical", "paddingAll": "12px",
                "contents": [{
                    "type": "button", "style": "primary", "color": "#1D9E75", "height": "sm",
                    "action": {"type": "uri", "label": "ดูย้อนหลัง & วิเคราะห์รายสัปดาห์",
                               "uri": dashboard_url},
                }],
            }} if dashboard_url else {}),
        },
    }


def _summary_row(label: str, b: dict) -> dict:
    used  = b.get("used", 0)
    limit = b.get("limit", 0)
    unit  = b.get("unit", "")
    over  = b.get("over", False)
    pct   = min(used / limit * 100, 100) if limit else 0
    color = "#e85d04" if over else "#1D9E75"
    flag  = " !" if over else ""
    return {
        "type": "box", "layout": "vertical", "spacing": "xs",
        "contents": [
            {
                "type": "box", "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": f"{label}{flag}", "size": "sm",
                     "color": "#444444", "flex": 3},
                    {"type": "text",
                     "text": f"{used:.0f}/{limit:.0f}{unit}",
                     "size": "sm", "color": color,
                     "weight": "bold", "align": "end", "flex": 3},
                ],
            },
            {
                "type": "box", "layout": "horizontal", "height": "6px",
                "contents": [
                    {"type": "box", "layout": "vertical",
                     "backgroundColor": color,
                     "flex": max(int(pct), 1), "contents": []},
                    {"type": "box", "layout": "vertical",
                     "backgroundColor": "#e0e0e0",
                     "flex": max(100 - int(pct), 1), "contents": []},
                ],
            },
        ],
    }
