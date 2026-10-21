# CLAUDE.md — Context for AI assistants working on this repo

This file is auto-loaded by Claude Code (and similar tools) when working in this
repository. It exists so that decisions made in planning conversations (e.g. with
Claude in Cowork) carry over into coding sessions here, without having to
re-explain the whole project every time.

**Keep this file updated** whenever an architecture decision, scope change, or
integration contract is agreed on — either person, either tool.

## Project

Senior thesis (ปริญญานิพนธ์), KMITL Faculty of IT. LINE chatbot for personalized
food/nutrition recommendations targeting NCD (non-communicable disease) patients.
Team: Kittipong Phuangsin (66070016) — CNN image classification; Prach Vichiankrua
(66070115, "Phone") — Contextual Bandit (LinUCB) + RAG pipeline.

- **Project 1 (done, defended):** LINE chatbot, Dialogflow-free intent routing,
  ML pipeline KMeans → ANN → KNN+MMR reranking, Typhoon LLM for NL explanation,
  PostgreSQL storage. Report + slides submitted (`รายงานขอสอบ_66070016_66070015.pdf`,
  `CHATBOT_NCD_PRESENTATION.pdf`).
- **Project 2 (in progress):** adds CNN food image classification (THFOOD-100),
  Contextual Bandit (LinUCB) recommendation layer, RAG pipeline. This is
  officially committed in the submitted Project 1 report (บทที่ 5.4, ข้อ 1-4) —
  not optional scope, already presented to the exam committee.

## Architecture — single app, no separate web pages per feature

Everything lives in **one FastAPI app** (`app/main.py`) behind **one LINE
webhook** (`/webhook`). `classify_intent()` in `app/state.py` routes incoming
text to a handler function (`_handle_recommend`, `_handle_log_meal`,
`_handle_ask_calorie`, `_handle_summary`, ...). New capabilities (CNN, RAG,
Bandit) are **not** separate deployed apps or LIFF pages — they plug into this
same flow as backend logic:

- **CNN**: new LINE event type handler for `message.type == "image"` in the
  webhook loop (currently only `"text"` is handled) → download image via LINE
  Content API → run inference → return a `food_id` matching the existing
  `foods` table → feed into the same `_handle_log_meal` flow.
- **RAG**: not user-facing at all. Injected into `_handle_ask_calorie` /
  `llm_service.answer_calorie_question` — call `rag_service.query_rag()` to
  retrieve grounded context (กรมอนามัย / สมาคมเบาหวานแห่งประเทศไทย / WHO docs)
  before building the LLM prompt, so answers are grounded instead of
  hallucinated. User sees no UI change, just better answers.
- **Bandit (LinUCB)**: not user-facing. Replaces/augments the food-selection
  step inside `_handle_recommend` (currently a static `ncd_model.recommend_3_meals`
  call). Treats each candidate food as an arm, uses user profile + history as
  context, updates from reward signal derived from `__eat__:` confirmations in
  `_handle_log_meal`. **Disease Override rule must run before the bandit ever
  sees candidate foods** — safety filtering takes priority over personalization,
  always.
- The only real web page in the app is the LIFF onboarding form
  (`/form`, `profile/templates/form.html`) — used because a health profile has
  too many fields to type in chat. Second page (owner decision, Entry 61): the
  history/weekly-analysis dashboard (`/form/dashboard`, `profile/templates/dashboard.html`,
  logic in `app/dashboard.py`, opened via `https://liff.line.me/<LIFF_ID>/dashboard`).
  Nothing else should need its own page.

## Current implementation status

- **RAG: wired in, using pgvector + bge-m3 (decision made — migrated off ChromaDB).**
  `rag/rag_service.py` rewritten to use `pgvector` + `asyncpg` against the same
  Postgres DB as everything else (shared pool from `db/database.py`), embedding
  model `BAAI/bge-m3` via `sentence-transformers`. Migration in
  `db/rag_schema.sql` (run once, after `schema.sql`, before first app start —
  not run automatically). `main.py` calls `init_rag()` on startup (lifespan)
  and `query_rag()` inside `_handle_ask_calorie` before building the LLM
  prompt; `llm_service.answer_calorie_question` takes an optional
  `rag_context` param now.
  **Local Postgres (Docker, port 5433) is the production DB** — no cloud deploy (advisor decision).
  **Knowledge base (DEV_LOG Entry 49):** `rag/ncd_knowledge.py` v2 = 25 docs
  rewritten from official sources (WHO, NIDDK, NHLBI DASH, KDOQI 2020, AHA,
  กรมอนามัย) with `source` + `url`. `init_rag` reseeds automatically when the
  KB hash changes (`rag_meta`). Extra docs: drop front-matter `.md` files in
  `rag/sources/` (see `rag/source_loader.py`). Thai guidelines added (Entry 50):
  `rag/sources/thai/*.md` = 22 docs summarised from DM CPG 2566, Thai HT 2567,
  Thai CKD 2565, Thai renal nutrition 2561 (PDFs in `rag/sources/thai/pdf/`,
  gitignored). Code thresholds aligned to them (CKD protein 0.6/0.8 g/kg IBW,
  IBW = height−100/−105, DM protein 20%, Thai high-K food list).
  Hallucination eval (Entry 52): 24% → 16% with RAG, retrieval recall@3 100% — see `eval/RESULTS.md`.
- **Intent classification: now LLM-based (Typhoon), not pure keyword matching.**
  `app/state.py`'s `classify_intent()` (keyword-based) is kept only as a
  fallback for when the LLM call itself fails outright. Primary path is
  `llm_service.classify_intent_llm()` → confidence ≥ 0.65 routes directly,
  below that shows a postback quick-reply so the user disambiguates instead
  of the bot silently misrouting. See `DEV_LOG.md` Entry 2 for why (keyword
  matching couldn't generalize to unseen phrasing, and misrouting was
  polluting `food_logs` with bad data that Bandit would have trained on).
- **Contextual Bandit: implemented (DEV_LOG Entry 45).** `bandit/linucb.py`
  (shared LinUCB, d=94, warm-started from KNN rank) + `bandit/service.py`.
  Pipeline returns a safety-filtered candidate pool (≤20) → bandit picks 3.
  Every shown card is logged in `recommendation_items` (context + reward);
  reward from "กินเมนูนี้" (`r<item_id>` in postback) or matching typed log;
  re-request same meal = 0 for all. Model persisted in `bandit_model`.
  `BANDIT_POLICY=linucb|knn|ab`. Simulation: acceptance 0.58 vs KNN 0.48.
- **Evaluation (`eval/`, Entry 44/53, results in `eval/RESULTS.md`):** intent (136 sentences),
  meal parsing (50), diversity (ILD/coverage/novelty), food search (45),
  safety compliance (72 profiles, 100%), bandit simulation, RAG hallucination,
  latency from `interaction_logs` (every message logs server/e2e/LLM ms).
- **Disease warnings on meal logging (Entry 63):** `app/meal_warnings.py` — typed/card/photo logs
  get per-meal warnings from `evaluate_food_limits` (disease-relevant only) + daily-limit-crossed
  warning after confirm (same thresholds as the dashboard). Rule-based, no LLM.
- **Pilot with 3 real users (Entry 68) → fixes Entry 66-70:** ask-calorie states when a near
  match is used (never present another dish's numbers under the user's dish name); colloquial
  suffix stripping in `extract_food_keyword`; heart disease now also blocks fried dishes
  (`ทอด|ไข่เจียว` in `HEART_HIGH_SATFAT_NAME_PATTERN`); per-user recently-shown dishes removed
  before the bandit; typed correction of CNN results (`_image_correction`). `eval/review_replies.py`
  flags suspicious replies (kcal mismatch, silent partial match, retries) for human review.
- **Real-user evaluation logging (Entry 64):** `interaction_logs.fallback/reply_text/cnn_ms`,
  CNN confirm tracking (`i<pred_id>` in `__eat__`), `eval/usage_report.py` (fallback rate, task
  completion, CNN top-1/3, latency), tester script `docs/USER_TEST_SCRIPT.md`.
- **Meal reminders + weekly summary (Entry 54):** `app/reminders.py`, opt-in per user
  ("เปิดแจ้งเตือน"), background loop in lifespan, dedup via `UPDATE ... RETURNING` on
  `user_reminders`. `REMINDERS_ENABLED=0` disables globally (LINE push quota).
- **Webhook:** returns 200 immediately, processes in BackgroundTasks, dedups by
  `webhookEventId`; unsigned requests rejected; LIFF endpoints verify the LINE
  access token. Image messages → `app/cnn_service.py` (THFOOD-100 model loaded
  in-process from `CNN_PACKAGE_DIR`, Entry 62).
- **Status as of 2026-10-13 (DEV_LOG Entries 19-59, full flow re-tested in real LINE OK):**
  - RAG retrieval actually works now (Entry 38-42: transformers forced to
    PyTorch via `USE_TF=0`, model preloaded at startup). Knowledge base = 47
    official-source docs (Entry 49-50).
  - Recommendation flow: 3 options for the *current* meal (next unlogged meal
    in order; quick-reply to switch meal), portion scaling small/normal/large,
    snacks excluded from main meals, CKD/sodium fail-safes for missing or
    estimated minerals. Rich Menu: แนะนำอาหาร / บันทึกการกิน / ถามแคล /
    สรุปวันนี้ / โปรไฟล์ผู้ใช้ (LIFF link) / วิธีใช้.
  - Food data: `foods_master_v2.csv` (2,608 rows, 749 dishes — Entry 58/59; +8 Thai drinks
    90200-90207 via recipe method `scripts/add_drinks.py`, Entry 70). Every filled or
    corrected value has its provenance in the `mineral_source` column and a
    re-runnable script in `scripts/`. CNN label → food_id contract:
    `cnn_label_food_mapping.csv` (100/100 labels map to the actual dish, Entry 58;
    ก๋วยเตี๋ยวเรือ = ก๋วยเตี๋ยวน้ำตก by owner decision). `food_aliases.csv` = alternate
    names checked first by `search_food` so typed and photo logging hit the same food_id.
  - ANN auto-retrains when training data changes (`models/ann_model.meta.json`
    fingerprint); cluster ids are relabelled by energy to match the report
    (2 = low-cal, 0 = mid, 1 = high).
- CNN: owned by Kittipong. **Delivered + wired in (Entry 62):** SwinV2-T (PyTorch),
  Top-1 92.19% / Top-3 98.05% on 13,376 test images. Runs as a separate localhost
  service `THFOOD100_Chatbot_Inference/thfood100_inference/server.py` (port 8081,
  gitignored, 107MB checkpoint); chatbot sets `CNN_API_URL` and POSTs raw image
  bytes to `/api/predict` → top-3 `class_id` 00..99 = `Directory_Name` in
  `cnn_label_food_mapping.csv`. **Default = in-process:** `cnn_service` imports
  `FoodPredictor` from `CNN_PACKAGE_DIR/inference.py` (no separate server; needs
  torch + torchvision in the chatbot env). `CNN_API_URL` = optional server mode;
  old `.keras` mode kept as last fallback.
- DB: PostgreSQL, schema in `db/schema.sql` (`users`, `foods`, `recommendations`,
  `food_logs` + views); extra tables are auto-created by `init_db()`
  (`MIGRATION_V44_SQL`), incl. `food_image_predictions` — image files go to
  object storage, never into the relational DB directly (currently not stored at all).
  `import_foods.py --prune` syncs `foods` with the CSV (never TRUNCATE CASCADE).
- Git (2026-10-21): team remote `origin` = `github.com/KittipongPhuangsin/chabot.git`;
  all Project 2 work pushed to branch `feature/rag-bandit` (PR into `main`). Work on
  `feature/rag-bandit`, not `main`. Personal portfolio copy: remote `mine` =
  `github.com/prachvck/ncd-nutrition-chatbot` from orphan branch `portfolio` (no old
  history — commit `acbf406` on the team repo contains old secrets; never push that history
  to a public repo). Portfolio excludes `data/raw/`, `test.ipynb`, `.env`, `eval/results/`,
  guideline PDFs, CNN checkpoint. Kittipong consented to portfolio use of all parts.
- **Deployment (advisor decision, 2026-10-21): no cloud deploy.** The system runs on Phone's
  machine (Docker Postgres + uvicorn + ngrok) for user testing and the exam demo. Supabase/Railway
  plan is dropped — don't propose it again. Report this as a limitation/future work (Project 1
  exam feedback: "ยังไม่ทราบเสถียรภาพเมื่อใช้งานพร้อมกันหลายคน" → answer with latency measured
  from real multi-user testing via `eval/usage_report.py`).

## Working agreements

- Don't put raw training data (THFOOD-100 images) or unstructured files in git
  or the shared DB. Train externally (Colab/Kaggle), commit only the trained
  model artifact — via Git LFS or Supabase Storage if it's large (CNN backbones
  are much bigger than the existing `models/ann_model.keras`, which is only 61KB).
- `foods.food_id` is the single source of truth for food identity — CNN
  predictions, RAG answers, and Bandit recommendations should all resolve to
  this table rather than inventing parallel food records.

- `docs/REFERENCES.md` — รายการแหล่งอ้างอิงทั้งหมด (ใช้ทำรูปเล่ม) อัปเดตทุกครั้งที่ใช้แหล่งใหม่
