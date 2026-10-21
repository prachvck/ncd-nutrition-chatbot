"""
app/main.py  —  Phase 2  (LIFF form version)
"""
import os, re, json, logging, hmac, hashlib, base64, asyncio, time
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import httpx

from db.database import (
    init_db, get_user, upsert_user, is_profile_complete,
    save_food_log, get_today_summary, get_recent_food_names,
    save_recommendation, get_today_logs, delete_today_logs,
    mark_event_processed, save_interaction_log, get_recently_shown_names,
    get_user_food_history_stats, get_recommendation_id_of_item, save_image_prediction,
    resolve_image_prediction, save_event_log,
    get_week_summary, get_logs_range,
)
from app import metrics, cnn_service, reminders, dashboard, meal_warnings
from bandit import service as bandit
from app.state import (
    State, get_state, set_state,
    get_temp, set_temp, clear_temp,
    classify_intent, extract_food_keyword, is_generic_food_term,
)
from app.line_reply  import (
    text_msg, quick_reply, quick_reply_postback, profile_summary, HELP_TEXT,
)
from app.line_flex   import build_meal_flex, build_summary_flex
from app.llm_service import (
    parse_meal_text, confirm_meal_message, answer_calorie_question,
    explain_recommendation, classify_intent_llm, INTENT_LABELS_TH,
)
from ml.pipeline import NCDModel
from rag.rag_service import init_rag, query_rag, is_ready as rag_is_ready

load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
ACCESS_TOKEN   = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
REPLY_URL      = "https://api.line.me/v2/bot/message/reply"
PUSH_URL       = "https://api.line.me/v2/bot/message/push"
CSV_PATH       = os.getenv("CSV_PATH", "foods_master_v2.csv")
MODEL_PATH     = os.getenv("MODEL_PATH", "models/ann_model.keras")
LIFF_ID        = os.getenv("LIFF_ID", "2009629473-L2qa2I9A")

ncd_model: NCDModel = None
templates = Jinja2Templates(directory="profile/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ncd_model
    log.info("Initializing DB...")
    await init_db()
    log.info("DB connection pool ready")
    log.info("Loading ML model...")
    ncd_model = NCDModel(csv_path=CSV_PATH, model_save_path=MODEL_PATH)
    if not ncd_model._ready:
        await ncd_model.init_from_db()
    log.info("Initializing RAG (pgvector)...")
    try:
        await init_rag()
    except Exception as e:
        # ไม่ให้ RAG ที่ยังไม่พร้อม (เช่น ยังไม่รัน db/rag_schema.sql) ทำให้แอปทั้งตัวล่ม
        # ระบบยังทำงานได้ปกติ แค่คำตอบจะไม่มีเอกสารอ้างอิงแนบไปด้วย
        log.warning(f"RAG init ล้มเหลว (แอปยังทำงานต่อได้ปกติ แต่ไม่มี RAG context): {e}")
    await bandit.init_bandit(ncd_model)
    await asyncio.to_thread(cnn_service.init_cnn)
    # [DEV_LOG Entry 54] ลูปแจ้งเตือนมื้ออาหาร/สรุปรายสัปดาห์ (ผู้ใช้ต้องเปิดเอง)
    reminder_task = asyncio.create_task(reminders.run_loop(_push, lambda: ncd_model))
    log.info("Ready!")
    yield
    reminder_task.cancel()


app = FastAPI(title="NCD Bot Phase 2", lifespan=lifespan)


def _verify(body: bytes, sig: str) -> bool:
    # [FIX — DEV_LOG Entry 48] เดิมไม่มี secret = ยอมรับทุก request (ใครก็ยิง
    # webhook ปลอมได้) — ตอนนี้ต้องตั้ง ALLOW_UNSIGNED_WEBHOOK=1 เองถ้าจะทดสอบแบบไม่มี secret
    if not CHANNEL_SECRET:
        return os.getenv("ALLOW_UNSIGNED_WEBHOOK", "0") == "1"
    mac = hmac.new(CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(mac).decode(), sig)


async def _reply(reply_token: str, messages: list[dict]):
    if not ACCESS_TOKEN: return
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {ACCESS_TOKEN}"}
    payload = {"replyToken": reply_token, "messages": messages[:5]}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(REPLY_URL,
                              content=json.dumps(payload, ensure_ascii=False).encode(),
                              headers=headers)
    if r.status_code != 200:
        log.error(f"LINE reply error {r.status_code}: {r.text}")


async def _push(uid: str, messages: list[dict]):
    if not ACCESS_TOKEN: return
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {ACCESS_TOKEN}"}
    payload = {"to": uid, "messages": messages[:5]}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(PUSH_URL,
                              content=json.dumps(payload, ensure_ascii=False).encode(),
                              headers=headers)
    # [Entry 54] 429 = โควตา push ของ LINE OA ต่อเดือนหมด (แจ้งเตือนจะส่งไม่ออก)
    if r.status_code != 200:
        log.error(f"LINE push error {r.status_code}: {r.text[:200]}")


@app.get("/form", response_class=HTMLResponse)
async def form_page(request: Request):
    return templates.TemplateResponse("form.html", {"request": request})


# [DEV_LOG Entry 61] หน้าสรุปการกินย้อนหลัง 10 วัน + วิเคราะห์รายสัปดาห์ — เปิดผ่าน LIFF ตัวเดิม:
# https://liff.line.me/<LIFF_ID>/dashboard → LINE ต่อ path ท้าย Endpoint URL (…/form) → /form/dashboard
@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/form/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "liff_id": LIFF_ID})


@app.get("/api/dashboard")
async def dashboard_api(uid: str, request: Request):
    if not await _liff_uid_ok(request, uid):
        return JSONResponse({"error": "auth"}, status_code=401)
    user = await get_user(uid)
    if not user or not is_profile_complete(user):
        return JSONResponse({"error": "no_profile"}, status_code=404)
    import datetime as _dt
    from zoneinfo import ZoneInfo
    today = _dt.datetime.now(ZoneInfo("Asia/Bangkok")).date()
    targets = await asyncio.to_thread(ncd_model.compute_user_targets, user)
    rows = await get_week_summary(uid, days=14)
    logs = await get_logs_range(uid, days=dashboard.SHOW_DAYS)
    try:
        await save_event_log(uid, "dashboard")       # [Entry 64] นับ task "ดูสรุปย้อนหลัง"
    except Exception as e:
        log.warning(f"save_event_log failed: {e}")
    return JSONResponse(dashboard.build_payload(user, targets, rows, logs, today))


async def _liff_uid_ok(request: Request, uid: str) -> bool:
    """[DEV_LOG Entry 48] เดิม /get_profile และ /submit_profile เชื่อ uid ที่ส่งมา
    ตรงๆ (ใครรู้ userId ก็อ่าน/แก้ข้อมูลสุขภาพคนอื่นได้) — ตอนนี้หน้า LIFF ส่ง
    access token มาด้วย แล้วถาม LINE ว่า token นี้เป็นของ userId ไหน
    ปิดได้ด้วย REQUIRE_LIFF_AUTH=0 (ทดสอบนอก LINE เท่านั้น)"""
    if os.getenv("REQUIRE_LIFF_AUTH", "1") != "1":
        return True
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not uid:
        return False
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get("https://api.line.me/v2/profile", headers={"Authorization": auth})
        return r.status_code == 200 and r.json().get("userId") == uid
    except Exception as e:
        log.warning(f"LIFF token verify failed: {e}")
        return False


@app.post("/submit_profile")
async def submit_profile(request: Request):
    data = await request.json()
    line_user_id   = data.get("line_user_id", "")
    if not await _liff_uid_ok(request, line_user_id):
        return JSONResponse({"status": "error", "message": "ยืนยันตัวตนไม่สำเร็จ กรุณาเปิดฟอร์มจากในแอป LINE"},
                            status_code=401)
    age            = int(data.get("age", 0))
    gender         = data.get("gender", "")
    if not line_user_id or not age or not gender:
        return JSONResponse({"status": "error", "message": "ข้อมูลไม่ครบ"}, status_code=400)

    profile = {
        "name":           data.get("name", ""),
        "age":            age,
        "gender":         gender,
        "weight_kg":      float(data.get("weight_kg", 0)),
        "height_cm":      float(data.get("height_cm", 0)),
        "activity_level": int(data.get("activity_level", 2)),
        "diseases":       data.get("diseases", []),
        "goal":           data.get("goal", ""),
    }
    await upsert_user(line_user_id, profile)
    set_state(line_user_id, State.READY)
    clear_temp(line_user_id)

    targets = await asyncio.to_thread(ncd_model.compute_user_targets, profile)
    dl      = targets["daily_limit"]
    nutrition = {
        "bmr":              round(targets["bmr"], 1),
        "tdee":             round(targets["tdee"], 1),
        "bmi":              targets.get("bmi"),
        "bmi_category":     targets.get("bmi_category"),
        "target_energy":    round(dl.get("energy_kcal", 0), 1),
        "target_carb_g":    round(dl.get("carb_available_g", 0), 1),
        "target_protein_g": round(dl.get("protein_g", 0), 1),
        "target_fat_g":     round(dl.get("fat_g", 0), 1),
        "target_sodium_mg": round(dl.get("sodium_mg", 0), 1),
    }

    BMI_CAT_TH = {
        "underweight": "น้ำหนักน้อย", "normal": "ปกติ",
        "overweight": "เกินเกณฑ์", "obese": "อ้วน",
    }
    bmi_line = ""
    if nutrition["bmi"] is not None:
        cat_th = BMI_CAT_TH.get(nutrition["bmi_category"], "")
        bmi_line = f"BMI: {nutrition['bmi']} ({cat_th})\n"
        if nutrition["bmi_category"] in ("overweight", "obese"):
            bmi_line += "ปรับพลังงานเป้าหมายให้ลดลงเล็กน้อยเพื่อช่วยควบคุมน้ำหนักครับ\n"

    name = profile["name"]
    # [DEV_LOG Entry 43] แสดงชื่อโรคเป็นภาษาไทย (เดิมขึ้น "hypertension, ckd")
    d_th = {"diabetes": "เบาหวาน", "hypertension": "ความดันโลหิตสูง", "obesity": "โรคอ้วน",
            "ckd": "โรคไต", "heart": "โรคหัวใจ"}
    diseases_text = (", ".join(d_th.get(d, d) for d in profile["diseases"])
                     if profile["diseases"] else "ไม่มี")
    push_text = (
        f"บันทึกข้อมูลสำเร็จแล้วครับ คุณ{name}!\n\n"
        f"โรคประจำตัว: {diseases_text}\n"
        f"{bmi_line}"
        f"เป้าหมายพลังงาน: {nutrition['target_energy']} kcal/วัน\n\n"
        f"กด 'แนะนำอาหาร' ที่เมนูด้านล่างได้เลยครับ!"
    )
    try:
        await _push(line_user_id, [text_msg(push_text)])
    except Exception as e:
        log.warning(f"push failed: {e}")

    return JSONResponse({"status": "success", "nutrition": nutrition})


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    body = await request.body()
    sig  = request.headers.get("X-Line-Signature", "")
    if not _verify(body, sig):
        raise HTTPException(400, "Invalid signature")
    data = json.loads(body)
    # [FIX — DEV_LOG Entry 44] เดิมประมวลผลทุกอย่าง (LLM 2-10 วินาที) ก่อนตอบ
    # 200 ให้ LINE — ถ้าช้า LINE ถือว่า timeout แล้วส่ง event ซ้ำ (redelivery)
    # → บันทึกการกิน/ให้ reward ซ้ำได้ ตอนนี้ตอบ 200 ทันที แล้วประมวลผลเบื้องหลัง
    # (reply token ยังใช้ได้) + กัน event ซ้ำด้วย webhookEventId
    for event in data.get("events", []):
        background.add_task(_process_event, event)
    return JSONResponse({"status": "ok"})


async def _process_event(event: dict):
    etype = event.get("type")
    if etype == "postback":
        text = event["postback"]["data"]
    elif etype == "message" and event.get("message", {}).get("type") == "text":
        text = event["message"]["text"].strip()
    elif etype == "message" and event.get("message", {}).get("type") == "image":
        text = None   # [Entry 47] CNN — ดู _handle_image
    else:
        return
    uid   = event.get("source", {}).get("userId", "")
    token = event.get("replyToken", "")
    try:
        if not await mark_event_processed(event.get("webhookEventId")):
            log.info(f"skip duplicate webhook event {event.get('webhookEventId')}")
            return
    except Exception as e:
        log.warning(f"dedup check failed (ประมวลผลต่อ): {e}")

    m = metrics.start(uid=uid, event_type=etype if text is not None else "image",
                      text=text or "[image]")
    try:
        if text is None:
            msgs = await _handle_image(uid, event)
        else:
            msgs = await handle(uid, text)
        metrics.mark(reply_text=_summarize_reply(msgs))
        await _reply(token, msgs)
    except Exception as e:
        metrics.mark(error=True, fallback="error")
        log.exception(f"Error uid={uid}: {e}")
        await _reply(token, [text_msg("ขออภัยครับ เกิดข้อผิดพลาด ลองใหม่ได้เลยครับ")])
    finally:
        d = metrics.finish()
        if d is not None:
            ts = event.get("timestamp")
            if ts:
                d["e2e_ms"] = round(time.time() * 1000 - float(ts), 1)
            log.info(f"[metrics] route={d.get('route')} server={d.get('server_ms')}ms "
                     f"llm={d.get('llm_ms', 0):.0f}ms e2e={d.get('e2e_ms')}ms")
            try:
                await save_interaction_log(d)
            except Exception as e:
                log.warning(f"save_interaction_log failed: {e}")


_CORR_START = ("ไม่ใช่", "ไม่ได้กิน", "ผิด", "จริงๆเป็น", "จริงๆ เป็น", "อันนี้คือ", "อันนี้เป็น")


def _image_correction(text: str, pending: dict) -> str | None:
    """[Entry 69] ผู้ใช้พิมพ์แก้ผลทายจากรูป → ชื่อเมนูใหม่ (None = ไม่ใช่ข้อความแก้)
    "ไม่ใช่หมูแต่เป็นกุ้ง" + ข้าวผัดหมู → ข้าวผัดกุ้ง · "ไม่ใช่ เป็นหอยทอด" → หอยทอด"""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not (t.startswith(_CORR_START) or "แต่เป็น" in t):
        return None
    name = str(pending.get("food_name_th") or "")
    m = re.search(r"ไม่ใช่\s*(.+?)\s*(?:แต่)?\s*(?:เป็น|คือ)\s*(.+)", t)
    if m:
        old, new = m.group(1).strip(), m.group(2).strip()
        new = re.sub(r"(ครับ|ค่ะ|คะ|นะ|จ้า)+$", "", new).strip()
        if old and old in name and new:
            return name.replace(old, new, 1)
        return new or None
    m = re.search(r"(?:ไม่ใช่|ผิด|จริงๆ ?เป็น|อันนี้คือ|อันนี้เป็น)\s*(?:ครับ|ค่ะ|นะ)?\s*(?:เป็น|คือ)?\s*(.+)", t)
    new = re.sub(r"(ครับ|ค่ะ|คะ|นะ|จ้า)+$", "", m.group(1)).strip() if m else ""
    new = re.sub(r"^(อันนี้|ในรูป|รูปนี้)\s*(คือ|เป็น)?\s*", "", new).strip()
    return new if len(new) >= 2 else None


def _summarize_reply(msgs: list[dict]) -> str:
    """[Entry 64] ข้อความที่บอทตอบ (เก็บใน interaction_logs ไว้ตรวจย้อนหลัง/ดู fallback)"""
    parts = []
    for m in msgs or []:
        if m.get("type") == "text":
            parts.append(m.get("text", ""))
        elif m.get("type") == "flex":
            parts.append(f"[flex] {m.get('altText', '')}")
        else:
            parts.append(f"[{m.get('type')}]")
    return "\n---\n".join(parts)


CONTENT_URL = "https://api-data.line.me/v2/bot/message/{}/content"


async def _handle_image(uid: str, event: dict) -> list[dict]:
    """[DEV_LOG Entry 47] ผู้ใช้ส่งรูปอาหาร → CNN ทาย → ยืนยันก่อนบันทึก
    (ใช้ flow ปุ่ม "กินเมนูนี้" เดิม: __eat__:food_id:... → ยืนยัน/ยกเลิก)"""
    metrics.mark(route="image")
    user = await get_user(uid)
    if not user or not is_profile_complete(user):
        return await _send_form_link(uid)
    if not await asyncio.to_thread(cnn_service.is_ready):
        metrics.mark(fallback="cnn_unavailable")
        return [text_msg("ตอนนี้ยังไม่รองรับการบันทึกจากรูปภาพครับ "
                         "พิมพ์ชื่อเมนูแทนได้เลย เช่น 'กินข้าวผัดหมูมื้อเที่ยง'")]
    msg_id = event["message"]["id"]
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(CONTENT_URL.format(msg_id),
                             headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
    if r.status_code != 200:
        log.error(f"LINE content error {r.status_code}: {r.text[:200]}")
        metrics.mark(fallback="error")
        return [text_msg("ขออภัยครับ ดาวน์โหลดรูปไม่สำเร็จ ลองส่งใหม่อีกครั้งครับ")]
    t = time.perf_counter()
    try:
        preds = await asyncio.to_thread(cnn_service.predict, r.content, 3)
    except Exception as e:
        log.error(f"CNN predict failed: {e}")
        metrics.mark(error=True, fallback="error")
        return [text_msg("ขออภัยครับ วิเคราะห์รูปไม่สำเร็จ ลองส่งใหม่ หรือพิมพ์ชื่อเมนูแทนได้เลยครับ")]
    metrics.mark(cnn_ms=round((time.perf_counter() - t) * 1000, 1))
    if not preds:
        metrics.mark(fallback="error")
        return [text_msg("ขออภัยครับ วิเคราะห์รูปไม่สำเร็จ พิมพ์ชื่อเมนูแทนได้เลยครับ")]
    top = preds[0]
    pred_id = None
    try:
        pred_id = await save_image_prediction(
            uid, top["label"], top.get("food_id"), top["confidence"], cnn_service.CNN_MODEL_VERSION,
            top3=[{"index": p["index"], "label": p["label"], "food_id": p.get("food_id"),
                   "confidence": round(p["confidence"], 4)} for p in preds])
    except Exception as e:
        log.warning(f"save_image_prediction failed: {e}")
    # [Entry 64] i<pred_id> ในปุ่ม → ตอนกดยืนยัน/ยกเลิกรู้ว่าเป็นผลจากรูปไหน (วัดความแม่นจริง)
    itag = f"i{pred_id}:" if pred_id else ""
    meal_th = MEAL_TH.get(await _current_meal_type(uid), "")
    if top["confidence"] < cnn_service.CNN_MIN_CONF or top.get("food_id") is None:
        # ไม่มั่นใจ → ให้ผู้ใช้เลือกจาก 3 อันดับแรก (กดแล้วเข้า flow ยืนยันเดิม)
        metrics.mark(fallback="cnn_low_conf")
        opts = [(p["label"][:20], f"__eat__:{p['food_id']}:normal:{itag}{p['db_name']}:{meal_th}",
                 f"กิน{p['label']}") for p in preds if p.get("food_id")]
        return [quick_reply_postback("ไม่แน่ใจว่าเป็นเมนูไหนครับ เลือกได้เลย "
                                     "(ถ้าไม่ใช่สักอัน พิมพ์ชื่อเมนูมาแทนได้ครับ)", opts)]
    msgs = await _handle_log_meal(
        uid, f"__eat__:{top['food_id']}:normal:{itag}{top['db_name']}:{meal_th}", user)
    return [text_msg(f"จากรูป น่าจะเป็น \"{top['label']}\" ({top['confidence']:.0%}) ครับ")] + msgs


async def _llm(fn, *args):
    """เรียกฟังก์ชัน LLM (sync) ใน thread + จับเวลารวมไว้ใน metrics"""
    t = time.perf_counter()
    try:
        return await asyncio.to_thread(fn, *args)
    finally:
        metrics.add_llm_ms((time.perf_counter() - t) * 1000)


async def handle(uid: str, text: str) -> list[dict]:
    state = get_state(uid)
    user  = await get_user(uid)

    if text.lower() in ["reset","รีเซ็ต","เริ่มใหม่"]:
        metrics.mark(route="reset")
        set_state(uid, State.NEW); clear_temp(uid)
        return [text_msg("รีเซ็ตแล้วครับ")]
    if text.strip().lower() in MENU_HELP:
        metrics.mark(route="menu:help")
        return [text_msg(HELP_TEXT)]
    if text.strip().lower() in MENU_PROFILE:
        metrics.mark(route="menu:profile")
        if user and is_profile_complete(user):
            # มีโปรไฟล์แล้ว → แสดงข้อมูล + ปุ่มแก้ไข
            return await _show_profile(uid, user)
        else:
            # ยังไม่มี → ส่ง link ฟอร์ม
            return await _send_form_link(uid)

    if not user or not is_profile_complete(user):
        metrics.mark(route="onboarding")
        return await _send_form_link(uid)

    # [FIX — DEV_LOG Entry 30] เดิมถ้าอยู่ในสถานะรอยืนยันการกิน ข้อความอะไร
    # ก็ตามจะถูกตอบว่า "พิมพ์ 'ยืนยัน' หรือ 'ยกเลิก'" วนไปเรื่อยๆ (ผู้ใช้ค้าง
    # ทำอย่างอื่นไม่ได้) — ตอนนี้ถ้าไม่ใช่คำตอบยืนยัน/ยกเลิก ถือว่าผู้ใช้เปลี่ยน
    # ใจไปทำอย่างอื่น: ทิ้งรายการที่ค้างแล้วทำตามข้อความใหม่เลย
    notice = []
    if state == State.CONFIRM_MEAL:
        if text in CONFIRM_WORDS or text in CANCEL_WORDS:
            metrics.mark(route="confirm_meal")
            return await _handle_confirm_meal(uid, text, user)
        # [DEV_LOG Entry 69] แก้ผลจากรูปด้วยการพิมพ์ เช่น "ไม่ใช่หมูแต่เป็นกุ้ง" (ทดสอบจริงเคยตกไป disambiguation)
        pending = get_temp(uid).get("pending_meal") or {}
        corrected = _image_correction(text, pending) if pending.get("image_prediction_id") else None
        if corrected:
            metrics.mark(route="image_correction", fallback="cnn_corrected")
            try:
                await resolve_image_prediction(pending["image_prediction_id"], False, None)
            except Exception as e:
                log.warning(f"resolve_image_prediction failed: {e}")
            clear_temp(uid); set_state(uid, State.READY)
            meal_th = MEAL_TH.get(pending.get("meal_type"), "")
            return await _handle_log_meal(uid, f"กิน{corrected}{meal_th}", user)
        if pending.get("image_prediction_id") and text.strip().startswith(("ไม่ใช่", "ผิด")):
            metrics.mark(route="confirm_meal")          # "ไม่ใช่ครับ" = ยกเลิก
            return await _handle_confirm_meal(uid, "ยกเลิก", user)
        clear_temp(uid); set_state(uid, State.READY)
        notice = [text_msg("ยกเลิกรายการที่รอยืนยันไว้ก่อนหน้าแล้วนะครับ")]

    # ── [DEV_LOG Entry 54] คำสั่งแจ้งเตือน (เปิด/ปิด/ตั้งเวลา) ─────────────────
    rem = await reminders.handle_command(uid, text)
    if rem is not None:
        metrics.mark(route="reminder")
        return notice + rem

    # ── ปุ่ม Flex "กินเมนูนี้" ──────────────────────────────────────
    if text.startswith("__eat__:"):
        metrics.mark(route="button:eat")
        return notice + await _handle_log_meal(uid, text, user)

    # ── [Entry 33] ปุ่มเปลี่ยนมื้อใต้การ์ดแนะนำเมนู ──────────────────────
    if text.startswith("__meal__:"):
        metrics.mark(route="button:switch_meal")
        return (notice + await _handle_recommend(uid, user, meal_override=text.split(":", 1)[1]))[:5]

    # ── ผู้ใช้กดปุ่มเลือกเจตนาจากตอนที่ระบบไม่มั่นใจ (ดู _build_disambiguation_reply) ──
    if text.startswith("__intent__:"):
        metrics.mark(route="button:intent")
        return (notice + await _handle_intent_postback(uid, text, user))[:5]

    # ── [DEV_LOG Entry 35] ปุ่ม Rich Menu — จับข้อความตรงตัวก่อนส่งให้ LLM
    # (เร็วกว่า ไม่เดาผิด) รองรับทั้งชื่อปุ่มชุดเก่าและชุดใหม่ ─────────────
    t = text.strip().lower()
    # [DEV_LOG Entry 38] คำสั่งทดสอบ: ลบบันทึกการกินของวันนี้ (ต้องยืนยันก่อน)
    if t in ("ลบบันทึกวันนี้", "ยืนยันลบบันทึกวันนี้"):
        metrics.mark(route="delete_today")
    if t == "ลบบันทึกวันนี้":
        return notice + [quick_reply("ต้องการลบบันทึกการกินทั้งหมดของวันนี้ใช่ไหมครับ (ย้อนกลับไม่ได้)",
                                     [("ยืนยันลบ", "ยืนยันลบบันทึกวันนี้"), ("ไม่ลบ", "ยกเลิก")])]
    if t == "ยืนยันลบบันทึกวันนี้":
        from app.state import clear_session_history
        n = await delete_today_logs(uid)
        clear_session_history(uid)
        return notice + [text_msg(f"ลบบันทึกของวันนี้แล้ว {n} รายการครับ เริ่มบันทึกใหม่ได้เลย")]
    if t in MENU_RECOMMEND:
        metrics.mark(route="menu:recommend", intent="recommend")
        return (notice + await _handle_recommend(uid, user))[:5]
    if t in MENU_SUMMARY:
        metrics.mark(route="menu:summary", intent="summary")
        return (notice + await _handle_summary(uid, user))[:5]
    if t in MENU_ASK_CALORIE:
        metrics.mark(route="menu:ask_calorie")
        return notice + [quick_reply(
            "อยากรู้แคลหรือสารอาหารของเมนูไหน พิมพ์ถามได้เลยครับ\n"
            "เช่น 'ข้าวผัดกี่แคล' หรือ 'ส้มตำกินได้ไหม'\n"
            "ระบบจะเช็คให้ด้วยว่าเหมาะกับโรคประจำตัวของคุณไหม",
            [("ข้าวผัดกี่แคล", "ข้าวผัดกี่แคล"), ("ส้มตำกินได้ไหม", "ส้มตำกินได้ไหม"),
             ("ข้าวมันไก่กี่แคล", "ข้าวมันไก่กี่แคล")])]
    if t in MENU_LOG:
        metrics.mark(route="menu:log")
        return notice + [quick_reply(
            "บันทึกการกินได้ 2 แบบครับ\n"
            "1) กด 'แนะนำอาหาร' แล้วกด 'กินเมนูนี้' ที่การ์ด\n"
            "2) พิมพ์บอกเอง เช่น 'กินข้าวผัดหมูมื้อเที่ยง' "
            "(ใส่ 'จานเล็ก' หรือ 'จานใหญ่' ได้)",
            [("แนะนำอาหาร", "แนะนำอาหาร"), ("สรุปวันนี้", "สรุปวันนี้")])]

    return (notice + await _classify_and_route(uid, text, user))[:5]


# [DEV_LOG Entry 35] ข้อความจากปุ่ม Rich Menu (ทั้งชุดเก่าและชุดใหม่) — ตัวพิมพ์เล็ก
MENU_RECOMMEND   = {"แนะนำอาหาร", "แนะนำเมนู"}
MENU_SUMMARY     = {"สรุปวันนี้", "พฤติกรรมการกิน", "สรุป"}
MENU_ASK_CALORIE = {"ถามแคล", "ถามแคลอรี่"}
MENU_LOG         = {"บันทึกการกิน", "บันทึกอาหาร"}
MENU_PROFILE     = {"โปรไฟล์", "โปรไฟล์ผู้ใช้", "ดูโปรไฟล์", "ข้อมูลของฉัน", "แก้ไขโปรไฟล์",
                    "เปลี่ยนข้อมูล", "เป้าหมาย", "เป้าหมายสุขภาพ", "โปรไฟล์ & เป้าหมาย",
                    "โปรไฟล์และเป้าหมาย"}
MENU_HELP        = {"help", "ช่วย", "คำสั่ง", "วิธีใช้", "วิธีใช้งาน"}

# [Entry 76]
EXERCISE_PATTERN = re.compile(r"วิ่ง|ออกกำลัง|ปั่นจักรยาน|ว่ายน้ำ|เผาผลาญ|ยกเวท|ฟิตเนส|เดินเร็ว|คาร์ดิโอ")
TOO_GENERIC_MEAL = {"ข้าวราด", "ราดข้าว", "กับข้าว", "ข้าวแกง", "อาหาร", "ข้าวกับ", "ของกิน"}
WANT_PREFIXES = ("อยากกิน", "อยากทาน", "จะกิน", "ขอกิน", "กินอะไรดีระหว่าง")

# [Entry 75] ปุ่มทำต่อหลังตอบคำถาม/บันทึกเสร็จ
NEXT_STEP_QR = [("แนะนำอาหาร", "แนะนำอาหาร"), ("บันทึกการกิน", "บันทึกการกิน"),
                ("ถามแคล", "ถามแคล"), ("สรุปวันนี้", "สรุปวันนี้")]

CONFIRM_WORDS = {"ยืนยัน", "ใช่", "ถูกต้อง", "ok", "OK", "โอเค", "ใช่ บันทึกเลย"}
CANCEL_WORDS  = {"ยกเลิก", "ไม่", "ไม่ใช่"}


INTENT_CONFIDENCE_THRESHOLD = 0.65


async def _classify_and_route(uid: str, text: str, user: dict) -> list[dict]:
    """
    จำแนกเจตนาด้วย LLM ก่อน (เข้าใจประโยคที่ไม่เคยเห็นมาก่อนได้ ต่างจาก
    keyword matching เดิม) ถ้ามั่นใจสูงพอ ไปทำงานตรงๆ เลย
    ถ้าไม่มั่นใจ ให้ผู้ใช้เลือกเองผ่านปุ่ม แทนที่จะเดามั่วแล้วพังเงียบๆ
    ถ้า LLM เรียกไม่สำเร็จเลย (เช่น network/API key ปัญหา) fallback ไปใช้
    keyword classifier เดิมเป็นด่านสำรอง ให้บอทยังพอทำงานได้
    """
    result = await _llm(classify_intent_llm, text)
    intent      = result["intent"]
    confidence  = result["confidence"]
    candidates  = result["candidates"]
    metrics.mark(intent=intent, intent_conf=confidence)

    if confidence == 0.0 and intent == "unknown":
        # LLM เรียกไม่สำเร็จเลย (ไม่ใช่แค่ไม่มั่นใจ) → fallback keyword classifier
        kw_intent = classify_intent(text)
        if kw_intent != "unknown":
            metrics.mark(route=f"keyword:{kw_intent}", intent=kw_intent)
            return await _route_intent(kw_intent, uid, text, user)

    if intent != "unknown" and confidence >= INTENT_CONFIDENCE_THRESHOLD:
        metrics.mark(route=f"llm:{intent}")
        return await _route_intent(intent, uid, text, user)

    metrics.mark(route="disambiguation", fallback="disambiguation")
    return _build_disambiguation_reply(text, candidates or ([intent] if intent != "unknown" else []))


async def _specific_food(text: str) -> str | None:
    """[Entry 76] "อยากกินส้มตำ" / "ลาบก้อย" ถูกจัดเป็น recommend แล้วได้เมนูอื่น 3 จาน
    → ถ้าข้อความระบุชื่ออาหารที่มีในฐานข้อมูลตรงตัว ให้ตอบเรื่องจานนั้นแทน"""
    t = text.strip()
    if t in MENU_RECOMMEND:
        return None
    for p in WANT_PREFIXES:
        t = t.replace(p, "")
    kw = extract_food_keyword(t).replace("แนะนำ", "").strip()
    if is_generic_food_term(kw) or len(kw) < 3:
        return None
    res = await asyncio.to_thread(ncd_model.search_food, kw, 1)
    if res and res[0].get("_match") == "full" and res[0].get("food_type") == "dish":
        return kw
    return None


async def _route_intent(intent: str, uid: str, text: str, user: dict) -> list[dict]:
    if intent == "recommend":
        food = await _specific_food(text)
        if food:
            metrics.mark(route="recommend_specific")
            msgs = await _handle_ask_calorie(uid, f"{food}กินได้ไหม", user)
            msgs[-1] = quick_reply(msgs[-1]["text"], [(f"บันทึกว่ากิน{food}"[:20], f"กิน{food}")]
                                   + NEXT_STEP_QR[:3])
            return msgs
        return await _handle_recommend(uid, user)
    if intent == "log_meal":     return await _handle_log_meal(uid, text, user)
    if intent == "ask_calorie":  return await _handle_ask_calorie(uid, text, user)
    if intent == "summary":      return await _handle_summary(uid, user)
    if intent == "edit_profile": return await _send_form_link(uid, edit=True)
    if intent == "help":         return [text_msg(HELP_TEXT)]

    metrics.mark(fallback="unknown_intent")
    return [quick_reply("ต้องการทำอะไรครับ?", [
        ("แนะนำเมนู","แนะนำเมนู"),("บันทึกการกิน","กิน"),
        ("สรุปวันนี้","สรุปวันนี้"),("ถามแคล","ข้าวผัดหมูกี่แคล"),
    ])]


async def _handle_intent_postback(uid: str, data: str, user: dict) -> list[dict]:
    """data format: __intent__:<intent>:<ข้อความเดิมของผู้ใช้>"""
    parts   = data.split(":", 2)
    intent  = parts[1] if len(parts) > 1 else "unknown"
    original_text = parts[2] if len(parts) > 2 else ""
    return await _route_intent(intent, uid, original_text, user)


def _build_disambiguation_reply(text: str, candidates: list[str]) -> list[dict]:
    """สร้างปุ่มให้ผู้ใช้เลือกเองตอนระบบไม่มั่นใจว่าเจตนาคืออะไร
    (สูงสุด 4 ตัวเลือก เรียงตามที่ LLM คิดว่าน่าจะเป็นมากสุด)"""
    seen = []
    for c in candidates:
        if c in INTENT_LABELS_TH and c not in seen:
            seen.append(c)
    if not seen:
        seen = ["recommend", "log_meal", "ask_calorie", "summary"]
    seen = seen[:4]

    # LINE จำกัด postback data ไว้ที่ 300 ตัวอักษร — ตัดข้อความเดิมทิ้งถ้ายาวเกิน
    # กันปัญหาส่ง quick reply ไม่ผ่านตอนข้อความผู้ใช้ยาวมาก
    safe_text = text if len(text) <= 250 else text[:250]
    items = [
        (INTENT_LABELS_TH[i], f"__intent__:{i}:{safe_text}", INTENT_LABELS_TH[i])
        for i in seen
    ]
    preview = text if len(text) <= 30 else text[:30] + "…"
    return [quick_reply_postback(
        f'ไม่แน่ใจว่า "{preview}" หมายถึงอะไรครับ เลือกได้เลย:',
        items,
    )]



async def _show_profile(uid: str, user: dict) -> list[dict]:
    """แสดงโปรไฟล์ปัจจุบัน + ปุ่มแก้ไข"""
    diseases    = user.get("diseases", [])
    d_map       = {"diabetes":"เบาหวาน","hypertension":"ความดัน",
                   "obesity":"อ้วน","ckd":"โรคไต","heart":"โรคหัวใจ"}
    d_text      = ", ".join([d_map.get(d,d) for d in diseases]) if diseases else "ไม่มี"
    act_map     = {1:"นั่งทำงาน",2:"เบา",3:"ปานกลาง",4:"หนัก",5:"หนักมาก"}
    act_text    = act_map.get(user.get("activity_level",2),"-")
    gender_text = "ชาย" if user.get("gender") == "male" else "หญิง"

    summary = (
        f"📋 โปรไฟล์ของคุณ\n\n"
        f"ชื่อ       : {user.get('name','') or '-'}\n"
        f"อายุ       : {user.get('age','-')} ปี\n"
        f"เพศ        : {gender_text}\n"
        f"น้ำหนัก   : {user.get('weight_kg','-')} กก.\n"
        f"ส่วนสูง   : {user.get('height_cm','-')} ซม.\n"
        f"กิจกรรม   : {act_text}\n"
        f"โรคประจำตัว: {d_text}"
    )
    # [DEV_LOG Entry 35] ปุ่ม "เป้าหมาย" ถูกรวมเข้ากับโปรไฟล์ — แสดงเป้าหมาย
    # สารอาหารต่อวันที่ระบบคำนวณจริง (เดิมแสดงช่อง goal ที่ฟอร์มไม่ได้เก็บแล้ว)
    try:
        tg = await asyncio.to_thread(ncd_model.compute_user_targets, user)
        dl = tg["daily_limit"]
        bmi_th = {"underweight": "น้ำหนักน้อย", "normal": "ปกติ",
                  "overweight": "เกินเกณฑ์", "obese": "อ้วน"}.get(tg.get("bmi_category"), "")
        goal_lines = [
            f"\n\n🎯 เป้าหมายต่อวัน",
            f"BMI       : {tg.get('bmi')} ({bmi_th})",
            f"พลังงาน   : {dl.get('energy_kcal',0):.0f} kcal",
            f"คาร์บ      : {dl.get('carb_available_g',0):.0f} g",
            f"โปรตีน    : {dl.get('protein_g',0):.0f} g",
            f"ไขมัน     : {dl.get('fat_g',0):.0f} g",
            f"โซเดียม   : ไม่เกิน {dl.get('sodium_mg',0):.0f} mg",
        ]
        if "ckd" in diseases:
            goal_lines += [f"โพแทสเซียม: ไม่เกิน {dl.get('potassium_mg',0):.0f} mg",
                           f"ฟอสฟอรัส  : ไม่เกิน {dl.get('phosphorus_mg',0):.0f} mg"]
        if "diabetes" in diseases:
            goal_lines.append("คาร์บต่อมื้อ: ไม่เกิน 60 g")
        summary += "\n".join(goal_lines)
    except Exception as e:
        log.warning(f"compute targets for profile failed: {e}")
    form_url  = f"https://liff.line.me/{LIFF_ID}"
    edit_text = f"ต้องการแก้ไขข้อมูลกดลิงก์นี้ได้เลยครับ:\n{form_url}"
    return [text_msg(summary), text_msg(edit_text)]

async def _send_form_link(uid: str, edit: bool = False) -> list[dict]:
    form_url = f"https://liff.line.me/{LIFF_ID}"
    if edit:
        msg = f"แก้ไขข้อมูลสุขภาพได้ที่นี่ครับ:\n{form_url}"
    else:
        msg = (
            f"สวัสดีครับ! ผมคือ อิ่มจัง ผู้ช่วยเรื่องอาหารสำหรับคนที่ดูแลสุขภาพ\n\n"
            f"กรอกข้อมูลสุขภาพเพื่อเริ่มใช้งานได้เลยครับ:\n{form_url}"
        )
    return [text_msg(msg)]


async def _handle_recommend(uid: str, user: dict, meal_override: str | None = None) -> list[dict]:
    history     = await get_recent_food_names(uid, days=3)
    today_used  = await get_today_summary(uid)

    # [DEV_LOG Entry 44] เมนูที่เพิ่งโชว์ไป อ่านจาก DB (recommendation_items)
    # แทน session history ในหน่วยความจำ — รีสตาร์ทแอปแล้วไม่หาย
    try:
        shown = await get_recently_shown_names(uid)
    except Exception as e:
        log.warning(f"get_recently_shown_names failed: {e}")
        shown = []
    combined_history = history + [n for n in reversed(shown) if n not in history]

    # [CHANGE — DEV_LOG Entry 32/33] 3 ตัวเลือกสำหรับ "มื้อปัจจุบัน" (มื้อหลักถัดไป
    # ที่ยังไม่บันทึก) — ผู้ใช้เปลี่ยนมื้อได้ด้วยปุ่มใต้การ์ด
    meal_type = meal_override if meal_override in MEAL_TH else await _current_meal_type(uid)
    if meal_type == "snack":
        tg   = await asyncio.to_thread(ncd_model.compute_user_targets, user)
        goal = float(tg["daily_limit"].get("energy_kcal", 0))
        used = float(today_used.get("total_energy_kcal") or 0)
        if goal - used < SNACK_MIN_REMAINING_KCAL:
            return [text_msg(
                f"วันนี้ได้พลังงานครบตามเป้าแล้วครับ ({used:.0f}/{goal:.0f} kcal)\n"
                f"ถ้ายังหิว แนะนำผักสด ผลไม้หวานน้อย หรือดื่มน้ำเปล่าแทนนะครับ")]

    # [DEV_LOG Entry 45] รอบแนะนำก่อนหน้าที่ยังไม่ได้เลือก: มื้อเดียวกัน = ผู้ใช้
    # ไม่เอาสักจาน (reward 0) / คนละมื้อ = หมดอายุ (ไม่อัปเดต)
    try:
        await bandit.resolve_previous(uid, meal_type)
    except Exception as e:
        log.warning(f"bandit.resolve_previous failed: {e}")

    # Safety ก่อนเสมอ: pool ผู้สมัครทุกตัวผ่าน Disease Override + hard filter แล้ว
    result = await asyncio.to_thread(ncd_model.recommend_next_meal, user, combined_history,
                                     today_used, 3, meal_type != "snack", bandit.N_CANDIDATES)
    candidates = result.get("candidates") or result["meals"]
    if not candidates:
        return [text_msg("ขออภัยครับ ไม่พบเมนูที่เหมาะสม")]

    # [DEV_LOG Entry 69] ทดสอบจริง: ผู้ใช้คนเดิมเห็นจานเดิมซ้ำทุกรอบ (Bandit เลือกจาก pool ที่ยังมีจานที่
    # เพิ่งโชว์ไป) → ตัดจานที่โชว์ไปใน 6 ชม. ล่าสุดออกก่อน ถ้ายังเหลือพอ 3 จาน
    shown_set = set(shown)
    fresh = [c for c in candidates if c.get("food_name_th") not in shown_set]
    if len(fresh) >= 3:
        candidates = fresh

    policy = bandit.policy_for(uid)
    try:
        hist = await get_user_food_history_stats(uid)
    except Exception as e:
        log.warning(f"history stats failed: {e}")
        hist = None
    try:
        meals, items = await asyncio.to_thread(
            bandit.rank, user, meal_type, candidates, result.get("meal_limit", {}), hist, 3, policy)
    except Exception as e:
        log.exception(f"bandit.rank failed → ใช้ลำดับ KNN+MMR เดิม: {e}")
        policy, meals = "knn_fallback", candidates[:3]
        items = [{"food_id": m.get("food_id"), "food_name_th": m["food_name_th"],
                  "portion": m.get("_portion", "normal"), "knn_rank": m.get("_knn_rank")} for m in meals]
    metrics.mark(policy=policy)

    meal_th = MEAL_TH.get(meal_type, "มื้อนี้")
    for m in meals:
        m["meal_label"] = meal_th
        m["meal_limit"] = result.get("meal_limit", {})

    targets = result["targets"]
    dl      = targets["daily_limit"]
    try:
        _, item_ids = await save_recommendation(uid, {
            "bmr": targets["bmr"], "tdee": targets["tdee"],
            "target_energy": dl.get("energy_kcal"),
            "target_carb_g": dl.get("carb_available_g"),
            "target_protein_g": dl.get("protein_g"),
            "target_fat_g": dl.get("fat_g"),
            "target_sodium_mg": dl.get("sodium_mg"),
            "target_potassium_mg": dl.get("potassium_mg"),
            "target_calcium_mg": dl.get("calcium_mg"),
            "target_magnesium_mg": dl.get("magnesium_mg"),
            "pred_cluster": result["cluster_info"]["final"],
            "meal_type": meal_type, "policy": policy,
        }, items)
        for m, iid in zip(meals, item_ids):
            m["_rec_item_id"] = iid
    except Exception as e:
        log.warning(f"save_recommendation failed: {e}")
    intro = await _llm(explain_recommendation, meals, user)
    flex  = build_meal_flex(meals, result, options_for=meal_th)
    used  = float(today_used.get("total_energy_kcal") or 0)
    tip   = (f"เมนูแนะนำสำหรับ{meal_th} {len(meals)} ตัวเลือก เลือกกินได้ 1 เมนู\n"
             f"เป้าหมายพลังงานวันนี้: {dl.get('energy_kcal',0):.0f} kcal "
             f"(กินไปแล้ว {used:.0f} kcal)\n"
             f"ไม่ใช่{meal_th}? กดเปลี่ยนมื้อด้านล่างได้เลยครับ")
    switch = [(MEAL_TH[m], f"__meal__:{m}", f"แนะนำ{MEAL_TH[m]}")
              for m in MEAL_ORDER + ["snack"] if m != meal_type]
    return [text_msg(intro), flex, quick_reply_postback(tip, switch)]


MEAL_ORDER = ["breakfast", "lunch", "dinner"]
SNACK_MIN_REMAINING_KCAL = 150   # งบเหลือน้อยกว่านี้ตอนของว่าง → ไม่แนะนำอาหารเพิ่ม
MEAL_TH    = {"breakfast": "มื้อเช้า", "lunch": "มื้อเที่ยง", "dinner": "มื้อเย็น", "snack": "ของว่าง"}


async def _current_meal_type(uid: str) -> str:
    """[DEV_LOG Entry 33] มื้อที่แนะนำเป็นค่าเริ่มต้น = มื้อหลักถัดไปที่ยังไม่ได้
    บันทึกวันนี้ ตามลำดับ เช้า → เที่ยง → เย็น ครบแล้ว = ของว่าง (ไม่ใช้เวลา
    นาฬิกาแล้ว ตามที่ผู้ใช้ขอ) — ผู้ใช้เปลี่ยนมื้อเองได้ด้วยปุ่มใต้การ์ด"""
    try:
        done = {str(r.get("meal_type")) for r in await get_today_logs(uid)}
    except Exception as e:
        log.warning(f"get_today_logs failed: {e}")
        done = set()
    # เริ่มหาต่อจากมื้อหลักล่าสุดที่บันทึกแล้ว — ถ้าข้ามมื้อเช้าไปบันทึกมื้อเที่ยง
    # เลย มื้อถัดไปต้องเป็นมื้อเย็น ไม่ย้อนกลับไปแนะนำมื้อเช้า
    last = max((MEAL_ORDER.index(m) for m in done if m in MEAL_ORDER), default=-1)
    for mt in MEAL_ORDER[last + 1:]:
        if mt not in done:
            return mt
    return "snack"


async def _meal_warning(fd: dict, portion: str, user: dict) -> str:
    """[DEV_LOG Entry 63] เช็คจาน (คูณขนาดจาน) กับเพดานต่อมื้อตามโรค — เกณฑ์เดียวกับ
    แนะนำอาหาร/ถามแคล ใช้กับบันทึกทุกทาง (พิมพ์ / กดการ์ด / ส่งรูป)"""
    try:
        targets = await asyncio.to_thread(ncd_model.compute_user_targets, user)
        ev = await asyncio.to_thread(ncd_model.evaluate_food_limits,
                                     meal_warnings.scale_food(fd, portion),
                                     set(user.get("diseases") or []), targets["meal_limit"])
        return meal_warnings.format_meal_warnings(ev, user.get("diseases") or [])
    except Exception as e:
        log.warning(f"meal warning failed: {e}")
        return ""


async def _handle_log_meal(uid: str, text: str, user: dict) -> list[dict]:
    # [FIX — DEV_LOG Entry 29] การ์ดจาก recommend_3_meals ใช้ label "เช้า/
    # กลางวัน/เย็น" (ไม่มีคำว่า "มื้อ") เดิม map ไม่เจอ → meal_type = unknown
    MEAL_TYPE_MAP = {"มื้อเช้า":"breakfast","มื้อเที่ยง":"lunch","มื้อเย็น":"dinner","ของว่าง":"snack",
                     "เช้า":"breakfast","กลางวัน":"lunch","มื้อกลางวัน":"lunch","เที่ยง":"lunch","เย็น":"dinner"}
    MEAL_TH_MAP   = {"breakfast":"มื้อเช้า","lunch":"มื้อเที่ยง","dinner":"มื้อเย็น","snack":"ของว่าง"}

    # ── กรณีกดปุ่ม Flex (format: __eat__:food_id:name:meal_label) ──────────
    if text.startswith("__eat__:"):
        # [FIX — DEV_LOG Entry 29] เดิม split(":", 3) แล้วค้นด้วย "ชื่อ" ที่
        # การ์ดต่อท้าย " + ข้าวสวย" ไว้ → search_food (regex) หาไม่เจอ → บันทึก
        # 0 kcal (กระทบ ~24% ของเมนู) และต่อให้เจอก็ได้ค่าไม่รวมข้าว ไม่ตรงกับ
        # การ์ด — ตอนนี้ใช้ food_id ที่ปุ่มส่งมาดึงค่าแบบเดียวกับการ์ด
        # (รวมข้าวถ้าการ์ดรวม) ค้นด้วยชื่อเป็นแค่ทางสำรอง
        _, _, rest   = text.partition("__eat__:")
        fid_str, _, rest = rest.partition(":")
        # [Entry 31] format ใหม่มีขนาดจานต่อจาก food_id (รองรับ format เก่าด้วย)
        portion = "normal"
        head, sep, tail = rest.partition(":")
        if head in ("small", "normal", "large") and sep:
            portion, rest = head, tail
        # [Entry 44] r<item_id> (การ์ดจากรอบแนะนำที่บันทึกไว้) — ใช้ให้ reward Bandit
        rec_item_id = None
        image_pred_id = None              # [Entry 64] i<pred_id> = มาจากรูป (CNN)
        for _ in range(2):
            head, sep, tail = rest.partition(":")
            if sep and head[:1] in ("r", "i") and head[1:].isdigit():
                if head[0] == "r":
                    rec_item_id = int(head[1:])
                else:
                    image_pred_id = int(head[1:])
                rest = tail
        food_name, _, meal_label = rest.rpartition(":")
        if not food_name:                 # ไม่มี meal_label ต่อท้าย
            food_name, meal_label = meal_label, ""
        food_id   = int(fid_str) if fid_str.isdigit() and int(fid_str) > 0 else None
        meal_type = MEAL_TYPE_MAP.get(meal_label, "unknown")

        fd = None
        if food_id is not None:
            fd = await asyncio.to_thread(ncd_model.get_food_by_id, food_id, True)
        if fd is None:
            res = await asyncio.to_thread(ncd_model.search_food, food_name, 1)
            fd = res[0] if res else None
        if fd is None:
            metrics.mark(fallback="food_not_found")
            return [text_msg(f"ขออภัยครับ หาข้อมูลโภชนาการของ \"{food_name}\" ไม่เจอ "
                             f"เลยยังไม่ได้บันทึกให้ ลองพิมพ์บันทึกเองได้เลยครับ")]
        meal_record = {
            "food_name_th": fd["food_name_th"], "food_name_en": fd.get("food_name_en",""),
            "food_id": fd.get("food_id"), "meal_type": meal_type,
            "portion": portion, "energy_kcal": fd["energy_kcal"],
            "carb_available_g": fd["carb_available_g"], "protein_g": fd["protein_g"],
            "fat_g": fd["fat_g"], "sodium_mg": fd["sodium_mg"],
            "potassium_mg": fd.get("potassium_mg",0), "calcium_mg": fd.get("calcium_mg",0),
            "magnesium_mg": fd.get("magnesium_mg",0), "phosphorus_mg": fd.get("phosphorus_mg",0),
            "source": "image" if image_pred_id else "button",
            "recommendation_item_id": rec_item_id, "image_prediction_id": image_pred_id,
        }
        if rec_item_id is not None:
            try:
                meal_record["recommendation_id"] = await get_recommendation_id_of_item(rec_item_id)
            except Exception as e:
                log.warning(f"get_recommendation_id_of_item failed: {e}")
                meal_record["recommendation_item_id"] = None

        set_temp(uid, "pending_meal", meal_record)
        set_state(uid, State.CONFIRM_MEAL)
        # meal_record เก็บค่า "ขนาดปกติ" + portion — save_food_log จะคูณ
        # PORTION_MUL ให้เองตอนบันทึก ตรงนี้คูณแค่เพื่อแสดงผล
        mul     = {"small": 0.75, "normal": 1.0, "large": 1.35}.get(portion, 1.0)
        kcal    = meal_record["energy_kcal"] * mul
        meal_th = MEAL_TH_MAP.get(meal_type, "")
        portion_th = {"small": " (จานเล็ก)", "large": " (จานใหญ่)"}.get(portion, "")
        shown   = meal_record["food_name_th"] + (" + ข้าวสวย" if fd.get("_includes_rice") else "") + portion_th
        confirm = f"บันทึก: {shown} {meal_th}\nพลังงาน: {kcal:.0f} kcal"
        warn    = await _meal_warning(fd, portion, user)
        if warn:
            confirm += "\n\n" + warn
        confirm += "\n\nถูกต้องไหมครับ?"
        return [quick_reply(confirm, [("ใช่ บันทึกเลย","ยืนยัน"),("ไม่ใช่","ยกเลิก")])]

    # ── กรณีพิมพ์เอง → LLM parse ──────────────────────────────────────────
    # [Entry 76] ทดสอบจริง "วันนี้วิ่ง 400 แคล" → ไม่เข้าใจว่ากินอะไร — บอกตรงๆ ว่ายังไม่รองรับ
    if EXERCISE_PATTERN.search(text):
        metrics.mark(fallback="unsupported")
        return [quick_reply("ตอนนี้อิ่มจังยังบันทึกการออกกำลังกายไม่ได้ครับ บันทึกได้เฉพาะอาหาร "
                            "เช่น 'กินข้าวผัดหมูมื้อเที่ยง'", NEXT_STEP_QR)]
    parsed    = await _llm(parse_meal_text, text)
    food_name = parsed.get("food_name_th", "")
    # [Entry 76] ทดสอบจริง "ราดข้าว" → บันทึกเป็น "ข้าวราดแกงไตปลา" — ชื่อกว้างเกินไป ให้ถามกลับ
    if food_name and re.sub(r"\s", "", food_name) in TOO_GENERIC_MEAL:
        metrics.mark(fallback="food_generic")
        return [text_msg(f"\"{food_name}\" กว้างไปนิดครับ ช่วยบอกชื่อกับข้าวด้วย "
                         f"เช่น 'กินข้าวราดผัดกะเพราหมูมื้อเที่ยง'")]
    if not food_name or parsed.get("confidence", 0) < 0.4:
        metrics.mark(fallback="parse_fail")
        return [text_msg("ขออภัยครับ ไม่เข้าใจว่ากินอะไร\nลองพิมพ์ใหม่ เช่น 'กินข้าวผัดหมูมื้อเที่ยง'")]
    food_results = await asyncio.to_thread(ncd_model.search_meal, food_name)
    portion      = parsed.get("portion", "normal")
    multiplier   = {"small":0.75,"normal":1.0,"large":1.35}.get(portion, 1.0)
    if food_results:
        fd = food_results[0]
        meal_record = {
            "food_name_th": fd["food_name_th"], "food_name_en": fd.get("food_name_en",""),
            "food_id": fd.get("food_id"), "meal_type": parsed.get("meal_type","unknown"),
            "portion": portion, "energy_kcal": fd["energy_kcal"],
            "carb_available_g": fd["carb_available_g"], "protein_g": fd["protein_g"],
            "fat_g": fd["fat_g"], "sodium_mg": fd["sodium_mg"],
            "potassium_mg": fd.get("potassium_mg",0), "calcium_mg": fd.get("calcium_mg",0),
            "magnesium_mg": fd.get("magnesium_mg",0), "phosphorus_mg": fd.get("phosphorus_mg",0),
            "source": "typed",
        }
    else:
        # [FIX — DEV_LOG Entry 29] เดิมบันทึกเป็น 0 kcal ได้ถ้าหาเมนูไม่เจอ →
        # ข้อมูลขยะใน food_logs (สรุปวันนี้เพี้ยน และ Bandit จะเอาไปเทรนต่อ)
        metrics.mark(fallback="food_not_found")
        return [text_msg(f"ขออภัยครับ ยังไม่มีข้อมูลโภชนาการของ \"{food_name}\" ในระบบ "
                         f"เลยยังไม่ได้บันทึกให้ ลองพิมพ์ชื่อเมนูที่ใกล้เคียงได้ครับ "
                         f"เช่น 'กินข้าวผัดหมูมื้อเที่ยง'")]
    # [Entry 38] ไม่ได้บอกมื้อ → ใช้มื้อถัดไปตามลำดับ (เหมือนปุ่มแนะนำอาหาร)
    if meal_record.get("meal_type") not in MEAL_TH:
        meal_record["meal_type"] = await _current_meal_type(uid)
    set_temp(uid, "pending_meal", meal_record)
    set_state(uid, State.CONFIRM_MEAL)
    kcal    = meal_record["energy_kcal"] * multiplier
    meal_th = MEAL_TH_MAP.get(meal_record["meal_type"], "")
    shown_name = meal_record["food_name_th"] + (" + ข้าวสวย" if fd.get("_includes_rice") else "")
    confirm = f"บันทึก: {shown_name} {meal_th}\nพลังงาน: {kcal:.0f} kcal"
    # [FIX — DEV_LOG Entry 38] หาเมนูแบบ "จาน" ไม่เจอ แต่ไปเจอวัตถุดิบชื่อคล้าย
    # (เช่น "ก๋วยจั๊บญวน" → "ก๋วยจั๊บญวน, เส้น, ต้มสุก" = แค่เส้น) — บอกผู้ใช้ตรงๆ
    # ว่าค่านี้ไม่ใช่ทั้งจาน ให้ตัดสินใจเองก่อนกดยืนยัน
    if fd.get("_match") == "partial" and fd.get("food_type") != "ingredient":
        metrics.mark(fallback="partial_match")
        confirm += (f"\n\n⚠️ ไม่พบ \"{food_name}\" ตรงตัวในระบบ ใช้ค่าของเมนูใกล้เคียง "
                    f"\"{meal_record['food_name_th']}\" แทน ถ้าไม่ใช่กด 'ไม่ใช่' แล้วพิมพ์ชื่อใหม่ได้ครับ")
    _same = lambda x, y: sorted(re.sub(r"[\s,]", "", x)) == sorted(re.sub(r"[\s,]", "", y))
    if fd.get("food_type") == "ingredient" and not _same(food_name, meal_record["food_name_th"]):
        confirm += (f"\n\n⚠️ ยังไม่มี \"{food_name}\" แบบเป็นจานในระบบ ค่านี้เป็นของ "
                    f"\"{meal_record['food_name_th']}\" (ต่อ {fd.get('_serving_g', 100):.0f} กรัม) อาจต่ำกว่าที่กินจริง")
    warn = await _meal_warning(fd, portion, user)
    if warn:
        confirm += "\n\n" + warn
    confirm += "\n\nถูกต้องไหมครับ?"
    return [quick_reply(confirm, [("ใช่ บันทึกเลย","ยืนยัน"),("ไม่ใช่","ยกเลิก")])]


async def _handle_confirm_meal(uid: str, text: str, user: dict) -> list[dict]:
    if text in CONFIRM_WORDS:
        meal = get_temp(uid).get("pending_meal")
        if not meal:
            set_state(uid, State.READY)
            return [text_msg("ไม่พบข้อมูล ลองบันทึกใหม่ครับ")]
        try:
            await save_food_log(uid, meal)
        except Exception as e:
            # [FIX — DEV_LOG Entry 32] เดิม error ตรงนี้หลุดไปถึง webhook ได้แค่
            # "เกิดข้อผิดพลาด" ไม่รู้สาเหตุ — log ไว้ให้เห็นใน uvicorn และบอก
            # ผู้ใช้ตรงๆ (คงรายการค้างไว้ ให้กดยืนยันซ้ำได้)
            log.exception(f"save_food_log failed uid={uid} meal={meal}: {e}")
            return [text_msg("ขออภัยครับ บันทึกลงฐานข้อมูลไม่สำเร็จ ลองกด 'ยืนยัน' อีกครั้ง "
                             "หรือพิมพ์ 'ยกเลิก' ได้ครับ")]
        clear_temp(uid); set_state(uid, State.READY)
        if meal.get("image_prediction_id"):
            try:
                await resolve_image_prediction(meal["image_prediction_id"], True, meal.get("food_id"))
            except Exception as e:
                log.warning(f"resolve_image_prediction failed: {e}")
        # [DEV_LOG Entry 45] reward ให้ Bandit — กดจากการ์ด = รู้ item ตรงๆ /
        # พิมพ์เองแต่ตรงกับจานในการ์ดรอบล่าสุด = นับว่าเลือกจานนั้นด้วย
        try:
            if meal.get("recommendation_id") and meal.get("recommendation_item_id"):
                await bandit.reward_choice(meal["recommendation_id"], meal["recommendation_item_id"])
            else:
                await bandit.reward_typed_log(uid, meal.get("food_id"))
        except Exception as e:
            log.warning(f"bandit reward failed: {e}")
        today      = await get_today_summary(uid)
        targets    = await asyncio.to_thread(ncd_model.compute_user_targets, user)
        daily_kcal = targets["daily_limit"].get("energy_kcal", 1800)
        mul        = {"small": 0.75, "normal": 1.0, "large": 1.35}.get(meal.get("portion", "normal"), 1.0)
        # [DEV_LOG Entry 63] ยอดรวมวันนี้เพิ่งเกินเป้ารายวันเพราะมื้อนี้ → เตือน + แนะนำมื้อที่เหลือ
        daily_warn = ""
        try:
            daily_warn = meal_warnings.daily_crossed_warnings(
                today, meal, targets["daily_limit"], user.get("diseases") or [])
        except Exception as e:
            log.warning(f"daily warning failed: {e}")
        over = ", ".join(l.split(" ")[1] for l in daily_warn.splitlines() if l.startswith("• "))
        reply = await _llm(confirm_meal_message,
            meal["food_name_th"], meal.get("meal_type",""),
            float(meal.get("energy_kcal",0)) * mul, float(today.get("total_energy_kcal",0)), daily_kcal,
            "", over)
        # [CHANGE — DEV_LOG Entry 32] ไม่แนะนำมื้อถัดไปล่วงหน้าอัตโนมัติแล้ว
        # (ผู้ใช้ต้องการให้แนะนำทีละมื้อ ตอนถึงมื้อนั้นจริง) — บอกแค่ว่ามื้อถัดไป
        # ขอได้เมื่อไหร่
        nxt = await _current_meal_type(uid)
        hint = (f"มื้อถัดไปคือ{MEAL_TH[nxt]} ถึงเวลาแล้วกด 'แนะนำอาหาร' ได้เลยครับ"
                if nxt in MEAL_ORDER and nxt != meal.get("meal_type") else "")
        msgs = [text_msg(reply)] + ([text_msg(daily_warn)] if daily_warn else [])
        last = hint or "ทำอะไรต่อดีครับ"
        return msgs + [quick_reply(last, NEXT_STEP_QR)]
    elif text in CANCEL_WORDS:
        meal = get_temp(uid).get("pending_meal") or {}
        if meal.get("image_prediction_id"):
            try:
                await resolve_image_prediction(meal["image_prediction_id"], False, None)
            except Exception as e:
                log.warning(f"resolve_image_prediction failed: {e}")
        clear_temp(uid); set_state(uid, State.READY)
        if meal.get("image_prediction_id"):
            return [text_msg("ยกเลิกแล้วครับ ถ้าในรูปเป็นเมนูอื่น พิมพ์ชื่อมาได้เลย "
                             "เช่น 'กินข้าวผัดกุ้งมื้อเที่ยง'")]
        return [text_msg("ยกเลิกแล้วครับ")]
    metrics.mark(fallback="confirm_unclear")
    return [text_msg("พิมพ์ 'ยืนยัน' หรือ 'ยกเลิก' ครับ")]


async def _handle_ask_calorie(uid: str, text: str, user: dict) -> list[dict]:
    kw = extract_food_keyword(text)
    food_results = ([] if is_generic_food_term(kw)
                    else await asyncio.to_thread(ncd_model.search_food, kw.strip(), 3))
    targets      = await asyncio.to_thread(ncd_model.compute_user_targets, user)
    user_ctx     = {**user, "meal_limit_kcal": targets["meal_limit"].get("energy_kcal",600)}

    # RAG: ดึงเอกสารแนวทางโภชนาการที่เกี่ยวข้องมาแนบให้ LLM ก่อนตอบ
    # (ลด hallucination — ดู CLAUDE.md / DEV_LOG.md สำหรับรายละเอียด)
    rag_context = ""
    if rag_is_ready():
        rag_context = await query_rag(text, diseases=user.get("diseases", []), n_results=3)

    # [FIX — DEV_LOG Entry 18] เช็คจานแรกที่เจอเทียบกับเกณฑ์เดียวกับตอน
    # "แนะนำเมนู" (_hard_filter) ก่อนส่งให้ LLM ตอบ — กันไม่ให้คำตอบตรงนี้
    # ขัดแย้งกับตอนแนะนำเมนู (เช่น จานที่ระบบกรองออกไปแล้วเพราะโพแทสเซียม/
    # คาร์บเกิน แต่ถ้าถามตรงๆ กลับได้คำตอบว่ากินได้ เพราะ LLM ไม่มีเกณฑ์
    # ตัวเลขอ้างอิง เดาเอาเอง)
    suitability = None
    if food_results:
        diseases = set(user.get("diseases") or [])
        suitability = await asyncio.to_thread(
            ncd_model.evaluate_food_limits, food_results[0], diseases, targets["meal_limit"]
        )

    # [DEV_LOG Entry 66] ไม่พบเมนูที่ถามตรงตัว → บอกผู้ใช้ก่อนเสมอ (กฎ ไม่พึ่ง LLM) ว่าใช้ค่าของเมนูไหน
    match_note, prefix = "", ""
    # [Entry 76] ไม่มีในฐานข้อมูล → บอกผู้ใช้ว่าคำตอบเป็นความรู้ทั่วไป (ทดสอบจริง "คะแหนงหมูกรอบ")
    if not food_results and not is_generic_food_term(kw):
        metrics.mark(fallback="food_not_in_db")
        prefix = f'ℹ️ ยังไม่มี "{kw}" ในฐานข้อมูล คำตอบนี้เป็นความรู้ทั่วไป ไม่ใช่ตัวเลขจากฐานข้อมูลครับ\n\n'
    if food_results and food_results[0].get("_match") == "partial":
        metrics.mark(fallback="partial_match")
        near = food_results[0]["food_name_th"]
        match_note = f'ผู้ใช้ถามถึง "{kw}" แต่ในฐานข้อมูลไม่มีเมนูนี้ตรงๆ ข้อมูลที่ให้มาเป็นของ "{near}" ซึ่งใกล้เคียงที่สุด'
        prefix = f'ℹ️ ไม่พบ "{kw}" ตรงตัวในระบบ ข้อมูลด้านล่างเป็นของ "{near}" ซึ่งใกล้เคียงที่สุดครับ\n\n'

    reply = await _llm(
        answer_calorie_question, food_results, user_ctx, text, rag_context, suitability, match_note
    )
    # [Entry 75] ผู้ทดสอบ: "ตอบแล้วไม่รู้ต้องทำไงต่อ" → แนบปุ่มทำต่อท้ายคำตอบ
    return [quick_reply(prefix + reply, NEXT_STEP_QR)]


async def _handle_summary(uid: str, user: dict) -> list[dict]:
    # [CHANGE — DEV_LOG Entry 36] แสดงการ์ดสรุปเสมอ แม้ยังไม่บันทึกอะไร (0 / เป้า)
    # ให้หน้านี้เป็นที่ดูเป้าหมายต่อวันได้ด้วย (ตัดปุ่ม "เป้าหมาย" ออกจาก Rich Menu
    # แล้ว) + เพิ่มโพแทสเซียม/ฟอสฟอรัสสำหรับผู้ป่วยไต
    today   = await get_today_summary(uid)
    targets = await asyncio.to_thread(ncd_model.compute_user_targets, user)
    budget  = await asyncio.to_thread(ncd_model.budget_summary, targets["daily_limit"], today)
    flex    = build_summary_flex(today, budget, diseases=user.get("diseases") or [],
                                 dashboard_url=f"https://liff.line.me/{LIFF_ID}/dashboard")
    if int(today.get("meal_count", 0)) == 0:
        return [flex, quick_reply("วันนี้ยังไม่ได้บันทึกอาหารครับ ให้ระบบแนะนำเมนูก่อนไหมครับ",
                                  [("แนะนำอาหาร", "แนะนำอาหาร"), ("บันทึกการกิน", "บันทึกการกิน")])]
    return [flex]



@app.get("/get_profile")
async def get_profile_api(uid: str, request: Request):
    """LIFF form ดึงข้อมูล user เดิม เพื่อ prefill form"""
    if not await _liff_uid_ok(request, uid):
        return JSONResponse({"exists": False}, status_code=401)
    user = await get_user(uid)
    if not user or not is_profile_complete(user):
        return JSONResponse({"exists": False})
    return JSONResponse({"exists": True, "profile": {
        "name":           user.get("name", ""),
        "age":            user.get("age"),
        "gender":         user.get("gender", ""),
        "weight_kg":      user.get("weight_kg"),
        "height_cm":      user.get("height_cm"),
        "activity_level": user.get("activity_level"),
        "diseases":       user.get("diseases", []),
        "goal":           user.get("goal", ""),
    }})

@app.get("/")
def health():
    return {"status":"ok","phase":2,"model_ready": ncd_model._ready if ncd_model else False}
