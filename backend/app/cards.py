"""闪卡: AI生成 + 间隔复习调度 + 统计"""
import json
from pathlib import Path

from . import db, ingest, parser

# 各掌握等级的复习间隔(天): box 0..5
INTERVALS = [0, 1, 2, 4, 7, 15]
MASTER_BOX = 4


def ensure_table():
    db.get().execute(
        """CREATE TABLE IF NOT EXISTS flashcards(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER,
            q TEXT, a TEXT,
            box INTEGER DEFAULT 0,
            reviews INTEGER DEFAULT 0,
            wrongs INTEGER DEFAULT 0,
            last_result TEXT DEFAULT '',
            last_reviewed REAL DEFAULT 0,
            created REAL
        )"""
    )
    db.get().commit()


def _due_after(row) -> float:
    return (row["last_reviewed"] or 0) + INTERVALS[min(row["box"], 5)] * 86400


def generate(doc_id: int, num: int = 10) -> int:
    """基于文档内容让LLM出题"""
    row = ingest.get_doc(doc_id)
    fp = row["file_path"]
    if not fp:
        raise ValueError("该文档缺少原文(旧数据), 请删除后重新上传")
    pages = parser.parse(Path(fp))
    text = "\n".join(t for t, _ in pages)[:9000]

    prompt = (
        f"你是出题老师。根据下面的文档内容, 出{num}张复习闪卡。"
        "覆盖关键概念、容易混淆的对比、重要命令/步骤。"
        '只返回JSON数组, 元素格式: {"q":"问题","a":"简短答案"}\n\n'
        f"文档《{row['title'] or row['filename']}》:\n{text}"
    )
    raw = ingest.call_chat(
        [{"role": "system", "content": "你只输出JSON数组, 不要任何多余文字。"},
         {"role": "user", "content": prompt}],
        temperature=0.5,
    )
    s = raw[raw.find("["): raw.rfind("]") + 1]
    cards = json.loads(s)
    ensure_table()
    now = db.now()
    n = 0
    exist_qs = {r[0].lower() for r in db.get().execute(
        "SELECT q FROM flashcards WHERE doc_id=?", (doc_id,))}
    for c in cards[:20]:
        if isinstance(c, dict) and c.get("q") and c.get("a"):
            q = str(c["q"]).strip()
            if q.lower() in exist_qs:  # 去重
                continue
            exist_qs.add(q.lower())
            db.get().execute(
                "INSERT INTO flashcards(doc_id,q,a,created) VALUES(?,?,?,?)",
                (doc_id, q, str(c["a"]).strip(), now),
            )
            n += 1
    db.get().commit()
    return n


def list_cards(doc_id: int | None = None):
    ensure_table()
    sql = ("SELECT * FROM flashcards" +
           (" WHERE doc_id=?" if doc_id else "") +
           " ORDER BY id DESC")
    cur = db.get().execute(sql, (doc_id,) if doc_id else ())
    return [dict(r) for r in cur]


def due_queue():
    ensure_table()
    rows = db.get().execute("SELECT * FROM flashcards ORDER BY id").fetchall()
    now = db.now()
    due = [dict(r) for r in rows if now >= _due_after(r)]
    # 新卡优先, 其次快到期的
    due.sort(key=lambda r: (r["reviews"], r["box"]))
    return due


def answer(card_id: int, result: str):
    """result: correct | fuzzy | wrong"""
    ensure_table()
    row = db.get().execute("SELECT * FROM flashcards WHERE id=?", (card_id,)).fetchone()
    if not row:
        raise ValueError("卡片不存在")
    box = row["box"]
    if result == "correct":
        box = min(box + 1, 5)
    elif result == "fuzzy":
        pass
    else:
        box = 0
    db.get().execute(
        "UPDATE flashcards SET box=?, reviews=reviews+1,"
        " wrongs=wrongs+(?), last_result=?, last_reviewed=? WHERE id=?",
        (box, 1 if result == "wrong" else 0, result, db.now(), card_id),
    )
    db.get().commit()


def delete(card_id: int):
    ensure_table()
    db.get().execute("DELETE FROM flashcards WHERE id=?", (card_id,))
    db.get().commit()


def stats() -> dict:
    ensure_table()
    rows = db.get().execute("SELECT * FROM flashcards").fetchall()
    total = len(rows)
    due = len([r for r in rows if db.now() >= _due_after(r)])
    mastered = len([r for r in rows if r["box"] >= MASTER_BOX])
    reviews = sum(r["reviews"] for r in rows)
    wrongs = sum(r["wrongs"] for r in rows)
    acc = round((reviews - wrongs) / reviews * 100) if reviews else None
    return {"total": total, "due": due, "mastered": mastered,
            "reviews": reviews, "accuracy": acc}
