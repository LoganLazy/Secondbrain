"""RAG 问答: 检索用户资料 -> 带引用回答; 以及个人记忆"""
import json

from . import db, ingest


RAG_PROMPT = """你是"Memory AI", 用户专属的私人知识助手。严格遵守:
1. 只根据<资料>内容回答, 资料里没有的就直说"你的资料里没有找到相关内容", 不要编造
2. 回答末尾标注来源, 格式: 「来源: 文件名 第N页」, 多个来源都列出
3. 用简洁中文, 直接给结论和细节
4. 可以结合资料给出建议, 但要说明哪些是资料里的、哪些是你的补充

<资料>
{context}
</资料>"""


def build_context(hits: list[dict]) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        blocks.append(f"[{i}] 《{h['title']}》 第{h['page']}页:\n{h['text']}")
    return "\n\n".join(blocks)


def chat_stream(question: str, kb_id: str = "default", session_id: str = ""):
    """流式RAG问答生成器: 先发sources事件, 再逐段delta, 最后done"""
    hits = search_with_threshold(question, kb_id)

    if not hits:
        yield {"type": "sources", "sources": []}
        text = "你的知识库里还没有找到相关内容，先上传一些资料吧。"
        yield {"type": "delta", "text": text}
        save_chat("user", question, kb_id=kb_id, session_id=session_id)
        save_chat("assistant", text, kb_id=kb_id, session_id=session_id)
        yield {"type": "done"}
        return

    yield {"type": "sources",
           "sources": [{"doc_id": h["doc_id"], "title": h["title"],
                        "filename": h["filename"], "page": h["page"],
                        "score": round(h["score"], 3),
                        "text": h["text"][:400]} for h in hits]}

    context = build_context(hits)
    conds, args = ["kb_id=?"], [kb_id]
    if session_id:
        conds.append("session_id=?")
        args.append(session_id)
    history = [
        {"role": r["role"], "content": r["content"]}
        for r in db.get().execute(
            "SELECT role,content FROM chats WHERE " + " AND ".join(conds) +
            " ORDER BY id DESC LIMIT 6", args)
    ][::-1]
    memories = [r["content"] for r in db.get().execute(
        "SELECT content FROM memories ORDER BY id DESC LIMIT 20")]

    system = RAG_PROMPT.format(context=context)
    if memories:
        system += "\n\n你还长期记得用户的这些情况(可自然参考): " + "；".join(memories)

    messages = [{"role": "system", "content": system}, *history,
                {"role": "user", "content": question}]

    full = []
    try:
        for piece in ingest.call_chat_stream(messages):
            full.append(piece)
            yield {"type": "delta", "text": piece}
    except Exception as e:
        piece = f"\n\n(AI连接中断: {e})"
        full.append(piece)
        yield {"type": "delta", "text": piece}

    answer = "".join(full).strip() or "(AI未能给出有效回答，请重试)"
    save_chat("user", question, kb_id=kb_id, session_id=session_id)
    save_chat("assistant", answer,
              [{"title": h["title"], "filename": h["filename"],
                "page": h["page"]} for h in hits],
              kb_id=kb_id, session_id=session_id)
    yield {"type": "done"}


def search_with_threshold(question: str, kb_id: str = "default"):
    hits = ingest.search(question, kb_id=kb_id)
    if hits:
        best = max(h["score"] for h in hits)
        hits = [h for h in hits if h["score"] >= best * 0.55 and h["score"] > 0.05]
    return hits


def chat(question: str, kb_id: str = "default") -> dict:
    hits = search_with_threshold(question, kb_id)
    if not hits:
        answer = "你的知识库里还没有任何资料，先上传一些文档吧。"
        return {"answer": answer, "sources": []}

    context = build_context(hits)
    history = [
        {"role": r["role"], "content": r["content"]}
        for r in db.get().execute(
            "SELECT role,content FROM chats WHERE kb_id=? ORDER BY id DESC LIMIT 6"
        )
    ][::-1]
    memories = [r["content"] for r in db.get().execute(
        "SELECT content FROM memories ORDER BY id DESC LIMIT 20")]

    system = RAG_PROMPT.format(context=context)
    if memories:
        system += "\n\n你还长期记得用户的这些情况(可自然参考): " + "；".join(memories)

    messages = [{"role": "system", "content": system}, *history,
                {"role": "user", "content": question}]
    try:
        answer = ingest.call_chat(messages, temperature=0.4)
    except Exception as e:
        return {"answer": f"AI调用失败({e}), 请检查网络或Key配置", "sources": []}

    sources = [{"doc_id": h["doc_id"], "title": h["title"], "filename": h["filename"],
                "page": h["page"], "score": round(h["score"], 3)}
               for h in hits]
    save_chat("user", question)
    save_chat("assistant", answer, sources)
    return {"answer": answer, "sources": sources}


def save_chat(role: str, content: str, sources: list | None = None,
              kb_id: str = "default", session_id: str = ""):
    db.get().execute(
        "INSERT INTO chats(role,content,sources,created,kb_id,session_id)"
        " VALUES(?,?,?,?,?,?)",
        (role, content, json.dumps(sources or [], ensure_ascii=False),
         db.now(), kb_id, session_id),
    )
    if session_id:
        db.get().execute("UPDATE sessions SET updated=? WHERE id=?",
                         (db.now(), session_id))
    db.get().commit()
