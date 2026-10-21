"""
app/line_reply.py  —  Phase 1
helper functions สร้าง message objects ส่ง LINE
"""


def text_msg(text: str) -> dict:
    """ข้อความธรรมดา"""
    return {"type": "text", "text": text}


def quick_reply(text: str, items: list[tuple[str, str]]) -> dict:
    """
    ข้อความ + ปุ่ม quick reply ใต้กล่องแชท
    items: [(label_บนปุ่ม, ข้อความที่ส่งเมื่อกด), ...]
    """
    return {
        "type": "text",
        "text": text,
        "quickReply": {
            "items": [
                {
                    "type": "action",
                    "action": {"type": "message", "label": lbl, "text": msg},
                }
                for lbl, msg in items
            ]
        },
    }


def quick_reply_postback(text: str, items: list[tuple[str, str, str]]) -> dict:
    """
    ข้อความ + ปุ่ม quick reply แบบ postback — ต่างจาก quick_reply() ตรงที่
    กดแล้วไม่โชว์เป็นข้อความที่ "ผู้ใช้พิมพ์" ในแชท (ใช้ displayText ควบคุม
    ข้อความที่โชว์แทน) เหมาะกับปุ่มที่ส่ง data ภายใน เช่น
    "__intent__:ask_calorie:ทุเรียนกินได้มั้ย" ที่ไม่อยากให้ผู้ใช้เห็น
    ข้อความเทคนิคแบบนั้นโผล่ในแชทตัวเอง

    items: [(label_บนปุ่ม, postback_data, displayText_ที่โชว์ในแชท), ...]
    """
    return {
        "type": "text",
        "text": text,
        "quickReply": {
            "items": [
                {
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": lbl,
                        "data": data,
                        "displayText": display,
                    },
                }
                for lbl, data, display in items
            ]
        },
    }


def profile_summary(profile: dict) -> str:
    """สรุป profile เป็น text"""
    diseases = profile.get("diseases", [])
    d_text   = ", ".join(diseases) if diseases else "ไม่มี"
    activity_label = {
        1: "นั่งทำงาน", 2: "เบา", 3: "ปานกลาง", 4: "หนัก", 5: "หนักมาก"
    }.get(profile.get("activity_level", 2), "-")

    return (
        f"ข้อมูลของคุณ {profile.get('name', '')} ครับ\n\n"
        f"อายุ        : {profile.get('age', '-')} ปี\n"
        f"เพศ         : {'ชาย' if profile.get('gender') == 'male' else 'หญิง'}\n"
        f"น้ำหนัก    : {profile.get('weight_kg', '-')} กก.\n"
        f"ส่วนสูง    : {profile.get('height_cm', '-')} ซม.\n"
        f"กิจกรรม    : {activity_label}\n"
        f"โรคประจำตัว: {d_text}\n"
        f"เป้าหมาย   : {profile.get('goal', '-')}"
    )


HELP_TEXT = """\
อิ่มจังช่วยอะไรได้บ้าง

🍱 แนะนำอาหาร
แนะนำ 3 เมนูสำหรับมื้อถัดไป ตามโรคประจำตัวและพลังงานที่เหลือของวันนี้ กด 'กินเมนูนี้' เพื่อบันทึก (เปลี่ยนมื้อได้ที่ปุ่มใต้การ์ด)

📝 บันทึกการกิน
พิมพ์บอกได้เลย เช่น 'กินข้าวผัดหมูมื้อเที่ยง'

🔍 ถามแคล
เช่น 'ข้าวผัดกี่แคล' หรือ 'ส้มตำกินได้ไหม' ระบบจะเช็คให้ว่าเหมาะกับโรคของคุณไหม

📊 สรุปวันนี้
ดูว่าวันนี้กินไปเท่าไหร่เทียบกับเป้าหมาย

👤 โปรไฟล์ผู้ใช้
ดูข้อมูลสุขภาพ เป้าหมายต่อวัน และแก้ไขข้อมูล

⏰ แจ้งเตือนมื้ออาหาร
พิมพ์ 'เปิดแจ้งเตือน' ให้เตือนมื้อที่ยังไม่ได้บันทึก + สรุปรายสัปดาห์ทุกวันอาทิตย์
เปลี่ยนเวลา เช่น 'ตั้งเวลาเที่ยง 12:30' · ปิด พิมพ์ 'ปิดแจ้งเตือน'"""
