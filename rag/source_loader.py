"""
rag/source_loader.py — โหลดสรุปเอกสารจากไฟล์ rag/sources/**/*.md [DEV_LOG Entry 49]

ใช้ตอนได้เอกสารทางการฉบับเต็มมาเพิ่ม (เช่น PDF แนวทางเวชปฏิบัติเบาหวาน 2566)
ให้สรุปเป็นไฟล์ .md ที่มี front-matter แบบนี้ (ไฟล์ที่ไม่มี front-matter จะถูกข้าม):

    ---
    id_prefix: th_dm_cpg2566
    disease: diabetes            # diabetes|hypertension|heart|ckd|obesity|general
    source: แนวทางเวชปฏิบัติสำหรับโรคเบาหวาน พ.ศ. 2566 (สมาคมโรคเบาหวานแห่งประเทศไทย)
    url: https://...
    ---
    ## หัวข้อที่ 1
    เนื้อหา...
    ## หัวข้อที่ 2
    เนื้อหา...

แต่ละหัวข้อ "## " = เอกสาร 1 ชิ้นใน RAG (id = <id_prefix>_<ลำดับ>)
แก้ไฟล์แล้วรีสตาร์ทแอป → init_rag เห็น hash เปลี่ยน → embed ใหม่ให้อัตโนมัติ
"""
import os
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_CHARS = 60
VALID_DISEASES = {"diabetes", "hypertension", "heart", "ckd", "obesity", "general"}


def _parse_front_matter(text: str):
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end < 0:
        return None, text
    meta = {}
    for line in text[3:end].strip().splitlines():
        line = line.split("#", 1)[0] if not line.strip().startswith("url") else line
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text[end + 4:]


def load_source_documents(root: str | None = None) -> list[dict]:
    root = root or os.path.join(HERE, "sources")
    docs = []
    for path in sorted(glob.glob(os.path.join(root, "**", "*.md"), recursive=True)):
        if os.path.basename(path).lower() == "readme.md":
            continue
        with open(path, encoding="utf-8") as f:
            meta, body = _parse_front_matter(f.read())
        if not meta or meta.get("disease") not in VALID_DISEASES or not meta.get("source"):
            continue
        prefix = meta.get("id_prefix") or os.path.splitext(os.path.basename(path))[0]
        sections, title, buf = [], None, []
        for line in body.splitlines():
            if line.startswith("## "):
                if title and buf:
                    sections.append((title, "\n".join(buf).strip()))
                title, buf = line[3:].strip(), []
            elif title is not None:
                buf.append(line)
        if title and buf:
            sections.append((title, "\n".join(buf).strip()))
        for i, (t, content) in enumerate(sections, 1):
            if len(content) < MIN_CHARS:
                continue
            docs.append({"id": f"{prefix}_{i:02d}", "disease": meta["disease"], "topic": t,
                         "content": content, "source": meta["source"], "url": meta.get("url")})
    return docs
