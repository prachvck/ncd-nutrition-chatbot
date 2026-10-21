# แหล่งอ้างอิงของโปรเจกต์ (สำหรับทำรูปเล่มรายงาน)

รวบรวมเมื่อ 2026-10-09 — **ทุกครั้งที่ใช้แหล่งใหม่ในโค้ด/ข้อมูล ให้เพิ่มที่ไฟล์นี้ด้วย**
คอลัมน์ "ใช้ที่ไหน" บอกตำแหน่งในโค้ด ใช้ตรวจย้อนได้ว่าตัวเลขในระบบมาจากไหน
ก่อนใส่ในรายงานให้เปิดลิงก์ยืนยันปี/ฉบับอีกครั้ง และจัดรูปแบบตามที่ภาควิชากำหนด (APA/IEEE)

---

## 1. แนวทางโภชนาการและการแพทย์ (ฐานความรู้ RAG + เกณฑ์ในระบบ)

| # | แหล่งอ้างอิง | ลิงก์ | ใช้ที่ไหน |
|---|---|---|---|
| R1 | World Health Organization. *Healthy diet* (Fact sheet), 2026. | https://www.who.int/news-room/fact-sheets/detail/healthy-diet | RAG `gen_who_001` (ไขมันรวม ≤30%, อิ่มตัว <10%, ทรานส์ <1%); ต้นฉบับใน `rag/sources/english/` |
| R2 | World Health Organization. *Sodium reduction* (Fact sheet), 11 May 2026. | https://www.who.int/news-room/fact-sheets/detail/sodium-reduction | RAG `gen_who_sodium`, `gen_who_sodium_tips` (โซเดียม <2,000 mg/วัน, เกลือ 1 g = Na 400 mg) |
| R3 | World Health Organization. *Guideline: Sugars intake for adults and children*. Geneva: WHO; 2015. | https://www.who.int/publications/i/item/9789241549028 (ข่าวประกาศ: https://www.who.int/news/item/04-03-2015-who-calls-on-countries-to-reduce-sugars-intake-among-adults-and-children) | RAG `gen_who_sugar`, `ob_who_sugar`; นิยาม "น้ำตาลอิสระ" ที่ใช้กรองเบาหวาน (`free_sugar_flag`) |
| R4 | National Heart, Lung, and Blood Institute (NIH). *DASH Eating Plan*. | https://www.nhlbi.nih.gov/education/dash-eating-plan | RAG `ht_dash_001`, `ht_dash_sodium`, `hd_dash_001`; เพดานโซเดียม 1,500 mg สำหรับความดัน/หัวใจ/ไต |
| R5 | National Institute of Diabetes and Digestive and Kidney Diseases (NIH). *Healthy Living with Diabetes*. Last reviewed Oct 2023. | https://www.niddk.nih.gov/health-information/diabetes/overview/healthy-living-with-diabetes | RAG `dm_niddk_001`, `dm_niddk_plate`, `dm_niddk_weight`, `ob_niddk_001` |
| R6 | National Institute of Diabetes and Digestive and Kidney Diseases (NIH). *Healthy Eating for Adults with Chronic Kidney Disease*. Last reviewed Jan 2025. | https://www.niddk.nih.gov/health-information/kidney-disease/chronic-kidney-disease-ckd/healthy-eating-adults-chronic-kidney-disease | RAG `ckd_niddk_potassium`, `ckd_niddk_phosphorus`, `ckd_niddk_general` |
| R7 | Ikizler TA, Burrowes JD, Byham-Gray LD, et al. KDOQI Clinical Practice Guideline for Nutrition in CKD: 2020 Update. *Am J Kidney Dis*. 2020;76(3 Suppl 1):S1–S107. | https://www.kidney.org/press-room/national-kidney-foundation-academy-nutrition-and-dietetics-release-kdoqi-clinical | RAG `ckd_kdoqi_protein`, `ckd_kdoqi_sodium` (ใช้ประกอบ — ตัวเลขในโค้ดยึดแนวทางไทย T3) |
| R8 | American Heart Association. *Saturated Fats*. Last reviewed Aug 2024. | https://www.heart.org/en/healthy-living/healthy-eating/eat-smart/fats/saturated-fats | RAG `hd_aha_satfat` (<6% ของพลังงาน); รายการอาหารไขมันอิ่มตัวสูง → `HEART_HIGH_SATFAT_NAME_PATTERN` |
| R9 | กรมอนามัย กระทรวงสาธารณสุข. หลัก 6:6:1 ลดหวาน มัน เค็ม (อ้างผ่านข่าวมติชน). | https://www.matichon.co.th/economy/news_3758290 | RAG `gen_th_661` — **ควรหาเอกสารต้นฉบับของกรมอนามัยมาแทนข่าว** |
| R10 | กรมการแพทย์แผนไทยและการแพทย์ทางเลือก. *DASH Diet* (เอกสารเผยแพร่). | https://thaicam.dtam.moph.go.th/wp-content/uploads/2020/07/DASH-Diet.pdf | RAG `ht_th_dash` |

### เอกสารไทยฉบับเต็ม (ได้ไฟล์แล้ว 2026-10-09 — เก็บที่ `rag/sources/thai/pdf/`, สรุปเข้า RAG ที่ `rag/sources/thai/*.md`)

| # | แหล่งอ้างอิง | ลิงก์ | หน้าที่ใช้ / ใช้ที่ไหน |
|---|---|---|---|
| T1 | ราชวิทยาลัยอายุรแพทย์แห่งประเทศไทย, สมาคมโรคเบาหวานแห่งประเทศไทยฯ, สมาคมต่อมไร้ท่อแห่งประเทศไทย, กรมการแพทย์ และ สปสช. *แนวทางเวชปฏิบัติสำหรับโรคเบาหวาน 2566*. กรุงเทพฯ: ศรีเมืองการพิมพ์; 2566. (ไฟล์ `Thai-DM-CPG-2566.pdf`) | https://www.dmthai.org/new/index.php/activities-and-news/news-pr/naewthang-wech-ptibati-sahrab-rokh-bea-hwan-2566-chbab-prabprung-kph-67 | หน้า 49-56 (บทโภชนบำบัด) → RAG `th_dm_cpg2566_01-06`; โปรตีนเบาหวาน 20% (`adjust_features_by_disease`), น้ำหนักอุดมคติ |
| T2 | สมาคมความดันโลหิตสูงแห่งประเทศไทย. *แนวทางการรักษาโรคความดันโลหิตสูงในเวชปฏิบัติทั่วไป พ.ศ. 2567*. พิมพ์ครั้งที่ 1; ส.ค. 2567. (ไฟล์ `Guideline HT 2024.pdf`) | https://www.thaihypertension.org/guideline.html (สำเนา PDF: https://fakthahospital.moph.go.th/images/PDF/PCT/Guideline%20HT%202024.pdf) | หน้า 25-28 (ปรับพฤติกรรม) → RAG `th_ht_2567_01-05`; โซเดียม ≤1.5 g |
| T3 | สมาคมโรคไตแห่งประเทศไทย. *ข้อแนะนำเวชปฏิบัติการดูแลผู้ป่วยโรคไตเรื้อรังก่อนการบำบัดทดแทนไต พ.ศ. 2565 (ฉบับปรับปรุงเพิ่มเติม)*. ISBN 978-616-8032-17-6. (ไฟล์ `CKD-guideline-2565-revised-edition.pdf`) | https://www.nephrothai.org/wp-content/uploads/2023/03/CKD-guideline-2565-revised-edition.pdf | หน้า 22 (ข้อ 6.9-6.11), 53-56 (บทที่ 10 โภชนบำบัด, ตาราง 10.1-10.3) → RAG `th_ckd_2565_01-05`; โปรตีน CKD 0.6 / 0.8 (DM) g/กก. น้ำหนักอุดมคติ (`CKD_PROTEIN_G_PER_KG`), รายการผักผลไม้โพแทสเซียมสูง (`CKD_HIGH_K_NAME_PATTERN`, `CKD_SAFETY_RULE`) |
| T4 | สมาคมโรคไตแห่งประเทศไทย และสมาคมผู้ให้อาหารทางหลอดเลือดดำและทางเดินอาหารแห่งประเทศไทย. *คำแนะนำแนวทางเวชปฏิบัติโภชนบำบัดสำหรับผู้ป่วยโรคไตในผู้ใหญ่ พ.ศ. 2561*. (ไฟล์ `Clinical_Practice_Recommendation_for_Nutritional_Management_in_Adult_Kidney_Patients_2.pdf`) | https://www.nephrothai.org/wp-content/uploads/2020/08/Clinical_Practice_Recommendation_for_Nutritional_Management_in_Adult_Kidney_Patients_2.pdf | หน้า 22-31 (คำแนะนำที่ 4-5) → RAG `th_renal_nut2561_01-06`; K ≤2,000 mg, P ≤1,000 mg (ขอบบนของช่วงในแนวทาง) |
| T5 | ปริมาณสารอาหารอ้างอิงที่ควรได้รับประจำวันสำหรับคนไทย พ.ศ. 2563 (กรมอนามัย) — อ้างผ่าน T1 (สัดส่วน คาร์บ:โปรตีน:ไขมัน 45-65:10-15:20-35, ใยอาหาร 25 g/วัน) | — | ควรหาฉบับเต็มถ้าจะอ้างตรง |

---

## 2. ข้อมูลอาหาร

| # | แหล่งอ้างอิง | ลิงก์ | ใช้ที่ไหน |
|---|---|---|---|
| D1 | สถาบันโภชนาการ มหาวิทยาลัยมหิดล (INMU). *Thai Food Composition Database (Thai FCD)* | https://inmu.mahidol.ac.th/thaifcd/ | food_id 20000/21000, `scripts/scrape_thaifcd.py`, `data/raw/thaifcd_foods_raw.csv` |
| D2 | CalForLife — ฐานข้อมูลแคลอรี่อาหารไทย | https://www.calforlife.com | food_id 22000, `scripts/scrape_calforlife.py` (0 = ไม่มีข้อมูล แก้แล้วใน `fix_calforlife_zeros.py`) |
| D3 | U.S. Department of Agriculture, Agricultural Research Service. *FoodData Central* (SR Legacy). | https://fdc.nal.usda.gov/ | เติมโพแทสเซียม/ฟอสฟอรัส/ข้าวสวยอ้างอิง (`RICE_REF_PER100G`, `scripts/fill_ckd_minerals_39.py`, คอลัมน์ `mineral_source`); หอยนางรมสด "Mollusks, oyster, Pacific, raw" (`scripts/add_cnn_near_dishes.py`, Entry 58) |
| D4 | ข้อมูล Project 1: `nutritionaddsugar.csv` (ต้นทางจาก Thai FCD + ข้อมูลน้ำตาลเพิ่ม) | — | `data/raw/nutritionaddsugar.csv`, food_id 11000 |
| D5 | THFOOD-100 (ชุดภาพอาหารไทย 100 คลาส) — **Kittipong เป็นผู้ระบุการอ้างอิง** | — | `cnn_class_labels.csv`, `cnn_label_food_mapping.csv` |
| D6 | กรมอนามัย กระทรวงสาธารณสุข. ข่าว: กรมอนามัยเผยคุณค่าทางโภชนาการอาหารสตรีทฟู้ด ปาท่องโก๋-ชาไทย (ชาไทยเย็น 1 แก้วมีน้ำตาล ~53 g / ~13 ช้อนชา; แนะนำสั่งหวานน้อย น้ำตาลไม่เกิน 2 ช้อนชา) | https://multimedia.anamai.moph.go.th/news/020366/ | ใช้ตรวจเทียบสูตรเครื่องดื่ม `scripts/add_drinks.py` (Entry 70) — ค่าโภชนาการคำนวณจากวัตถุดิบ D1 |

---

## 3. วิธีการ / อัลกอริทึม

| # | แหล่งอ้างอิง | ใช้ที่ไหน |
|---|---|---|
| M1 | Mifflin MD, St Jeor ST, Hill LA, Scott BJ, Daugherty SA, Koh YO. A new predictive equation for resting energy expenditure in healthy individuals. *Am J Clin Nutr*. 1990;51(2):241–247. doi:10.1093/ajcn/51.2.241 | `calculate_bmr` |
| M2 | WHO Expert Consultation. Appropriate body-mass index for Asian populations and its implications for policy and intervention strategies. *Lancet*. 2004;363(9403):157–163. doi:10.1016/S0140-6736(03)15268-3 | `bmi_category` (เกณฑ์ BMI เอเชีย 23/25) |
| M3 | Li L, Chu W, Langford J, Schapire RE. A contextual-bandit approach to personalized news article recommendation. In: *Proc. 19th Int. Conf. World Wide Web (WWW 2010)*. ACM; 2010. p. 661–670. doi:10.1145/1772690.1772758 | `bandit/linucb.py` (LinUCB, hybrid/shared model) |
| M4 | Carbonell J, Goldstein J. The use of MMR, diversity-based reranking for reordering documents and producing summaries. In: *Proc. 21st Annu. Int. ACM SIGIR Conf. (SIGIR '98)*. ACM; 1998. p. 335–336. doi:10.1145/290941.291025 | `_knn_mmr` |
| M5 | Pedregosa F, Varoquaux G, Gramfort A, et al. Scikit-learn: Machine learning in Python. *J Mach Learn Res*. 2011;12(85):2825–2830. | KMeans, StandardScaler, NearestNeighbors, metrics ใน eval |
| M6 | Chen J, Xiao S, Zhang P, Luo K, Lian D, Liu Z. M3-Embedding: Multi-linguality, multi-functionality, multi-granularity text embeddings through self-knowledge distillation. In: *Findings of the Association for Computational Linguistics: ACL 2024*. 2024. p. 2318–2335. doi:10.18653/v1/2024.findings-acl.137 (preprint: arXiv:2402.03216) | `rag/rag_service.py` (BAAI/bge-m3) |
| M7 | Lewis P, Perez E, Piktus A, et al. Retrieval-augmented generation for knowledge-intensive NLP tasks. In: *Advances in Neural Information Processing Systems 33 (NeurIPS 2020)*. 2020. p. 9459–9474. | แนวคิด RAG |
| M8 | Pipatanakul K, Manakul P, Nitarach N, et al. Typhoon 2: A family of open text and multimodal Thai large language models. arXiv:2412.13702. 2024. (รุ่นแรก: Pipatanakul K, et al. Typhoon: Thai large language models. arXiv:2312.13951. 2023.) | `app/llm_service.py` ใช้ `typhoon-v2.5-30b-a3b-instruct` ผ่าน API — รุ่น 2.5 ยังไม่มี paper ของตัวเอง อ้าง Typhoon 2 + ระบุชื่อรุ่น/วันที่ใช้ในรายงาน |
| M9 | pgvector — open-source vector similarity search for Postgres. | https://github.com/pgvector/pgvector |
| M10 | Holmes S, Moorhead A, Bond R, Zheng H, Coates V, McTear M. Usability testing of a healthcare chatbot: Can we use conventional methods to assess conversational user interfaces? In: *Proc. 31st European Conf. Cognitive Ergonomics (ECCE 2019)*. ACM; 2019. p. 207–214. doi:10.1145/3335082.3335094 | แบบสอบถาม CUQ |
| M11 | Zheng L, Chiang WL, Sheng Y, et al. Judging LLM-as-a-judge with MT-Bench and Chatbot Arena. In: *Advances in Neural Information Processing Systems 36 (NeurIPS 2023) Datasets and Benchmarks Track*. 2023. (arXiv:2306.05685) | วิธี LLM-as-judge ใน `eval/eval_rag.py` |

> M1–M8, M10–M11 ตรวจยืนยันกับ Crossref / หน้าสำนักพิมพ์ / arXiv แล้ว (2026-10-21) — M9 เป็นซอฟต์แวร์ อ้างเป็น URL

---

## 4. งานวิจัยรองรับตัวชี้วัดประสิทธิภาพ (ตามข้อเสนอแนะอาจารย์ 2026-10-15)

แบ่งเป็น 2 ส่วนตามที่อาจารย์ให้แยก: (ก) ประสิทธิภาพแชทบอท (ข) ประสิทธิภาพโมเดลแนะนำอาหาร
รายการในส่วนนี้ค้นยืนยันชื่อ/ผู้แต่ง/แหล่งตีพิมพ์/DOI แล้ว (2026-10-15)

### 4ก. ประสิทธิภาพแชทบอท

| # | แหล่งอ้างอิง | ใช้รองรับตัวชี้วัด |
|---|---|---|
| E1 | Abd-Alrazaq A, Safi Z, Alajlani M, Warren J, Househ M, Denecke K. Technical metrics used to evaluate health care chatbots: Scoping review. *J Med Internet Res*. 2020;22(6):e18301. doi:10.2196/18301 | กรอบหลัก: 27 ตัวชี้วัด (usability, classifier performance, speed, response understanding/generation); แนะนำให้ใช้ตัวชี้วัดจาก conversation log → intent accuracy/F1, เวลาตอบ, fallback rate |
| E2 | Denecke K, Abd-Alrazaq A, Househ M, Warren J. Evaluation metrics for health chatbots: A Delphi study. *Methods Inf Med*. 2021;60(05/06):171–179. doi:10.1055/s-0041-1736664 | ผู้เชี่ยวชาญเห็นพ้อง 24 ตัวชี้วัด (ease of use, ความถูกต้องของเนื้อหา, ความเหมาะสมของคำตอบ) → รองรับการเลือกตัวชี้วัด |
| E3 | Ding H, Simmich J, Vaezipour A, Andrews N, Russell T. Evaluation framework for conversational agents with artificial intelligence in health interventions: a systematic scoping review. *J Am Med Inform Assoc*. 2024;31(3):746–761. doi:10.1093/jamia/ocad222 | กรอบประเมินแชทบอทสุขภาพ (ใหม่) |
| E4 | Hua Y, Xia W, Bates D, et al., Torous J. Standardizing and scaffolding health care AI-chatbot evaluation: Systematic review (HAICEF). *JMIR AI*. 2025;4:e69006. doi:10.2196/69006 | กรอบล่าสุด 3 ด้าน: safety/privacy/fairness, trustworthiness/usefulness, design & operational effectiveness → รองรับ safety compliance + latency |
| E5 | Casas J, Tricot MO, Abou Khaled O, Mugellini E, Cudré-Mauroux P. Trends & methods in chatbot evaluation. In: *ICMI '20 Companion*. 2020. p. 280–286. doi:10.1145/3395035.3425319 | จัดตัวชี้วัดตาม ISO 9241-11: effectiveness / efficiency / satisfaction |
| E6 | Li CH, Yeh SF, Chang TJ, Tsai MH, Chen K, Chang YJ. A conversation analysis of non-progress and coping strategies with a banking task-oriented chatbot. In: *Proc. CHI 2020*. | วิเคราะห์ log จริง 1,685 ผู้ใช้ 3 เดือน: บทสนทนาที่ "ไปต่อไม่ได้" (non-progress) → รองรับ fallback rate จาก log การใช้จริง |
| E7 | Larson S, et al. An evaluation dataset for intent classification and out-of-scope prediction. In: *EMNLP-IJCNLP 2019*. p. 1311–1316. doi:10.18653/v1/D19-1131 | intent accuracy + การตรวจจับข้อความนอกขอบเขต (unknown/disambiguation) |
| E8 | CUQ: Holmes et al. ECCE 2019 (= M10) และ Holmes S, Bond R, Moorhead A, Zheng J, Coates V, McTear M. Towards validating a chatbot usability scale. In: *Design, User Experience, and Usability (DUXU 2023)*. LNCS. Springer; 2023. p. 321–339. doi:10.1007/978-3-031-35708-4_24 · คู่มือ: https://www.ulster.ac.uk/__data/assets/pdf_file/0009/478809/Chatbot-Usability-Questionnaire.pdf | แบบสอบถาม CUQ 16 ข้อ คะแนน 0–100 (`docs/QUESTIONNAIRE.md`, `eval/cuq_score.py`) |
| E9 | Es S, James J, Espinosa-Anke L, Schockaert S. RAGAs: Automated evaluation of retrieval augmented generation. In: *EACL 2024 System Demonstrations*. p. 150–158 | faithfulness / answer relevance / context relevance ของ RAG |
| E10 | Thongyoo P, Anantapanya P, Jamsri P, Chotipant S. A personalized food recommendation chatbot system for diabetes patients. In: *Cooperative Design, Visualization, and Engineering (CDVE 2020)*. LNCS. Springer; 2020. p. 19–28. doi:10.1007/978-3-030-60816-3_3 | งานใกล้เคียง (สจล.) ประเมินความพึงพอใจด้านเนื้อหา/การออกแบบ/การใช้งาน |
| E11 | Fhakfaipouk B, Tangjitwattanakorn W, Baiklai S, Phetmanee S, Phetmanee T. Development of a LINE chatbot (CAREBOTX) for providing information on specialized medications. *Interprof J Health Sci*. 2025;23(1):IJHS-0730. https://li05.tci-thaijo.org/index.php/IJHS/article/view/730 | งานไทยบน LINE ประเมินความพึงพอใจผู้ใช้ 221 คน |
| E12 | Laranjo L, Dunn AG, Tong HL, et al. Conversational agents in healthcare: a systematic review. *J Am Med Inform Assoc*. 2018;25(9):1248–1258. doi:10.1093/jamia/ocy072 | ภาพรวมงานวิจัยแชทบอทสุขภาพ (บทที่ 2) |
| E13 | Wu Y, Zhang J, Ge P, et al. Application of chatbots to help patients self-manage diabetes: Systematic review and meta-analysis. *J Med Internet Res*. 2024;26:e60380. doi:10.2196/60380 | แชทบอทสำหรับผู้ป่วยเบาหวาน (บทที่ 2) |

> E12–E13 ยืนยันจากรายการอ้างอิงของ E11 (มี DOI) ยังไม่ได้เปิดอ่านฉบับเต็ม

### 4ข. ประสิทธิภาพโมเดลแนะนำอาหาร (B = เลขอ้างอิงหัวข้อนี้ ไม่ซ้ำกับ R ในหัวข้อ 1)

| # | แหล่งอ้างอิง | ใช้รองรับตัวชี้วัด |
|---|---|---|
| B1 | Li L, Chu W, Langford J, Schapire RE. (= M3) WWW 2010 | acceptance rate (CTR) ของ LinUCB |
| B2 | Li L, Chu W, Langford J, Wang X. Unbiased offline evaluation of contextual-bandit-based news article recommendation algorithms. In: *Proc. 4th ACM Int. Conf. Web Search and Data Mining (WSDM '11)*. ACM; 2011. p. 297–306. doi:10.1145/1935826.1935878 | การประเมิน bandit แบบ offline/simulation, regret |
| B3 | Ziegler CN, McNee SM, Konstan JA, Lausen G. Improving recommendation lists through topic diversification. In: *WWW 2005*. p. 22–32. doi:10.1145/1060745.1060754 | intra-list similarity/diversity (ILD) |
| B4 | Kaminskas M, Bridge D. Diversity, serendipity, novelty, and coverage: A survey and empirical analysis of beyond-accuracy objectives in recommender systems. *ACM TiiS*. 2016;7(1):2:1–2:42. doi:10.1145/2926720 | ILD, coverage, novelty |

