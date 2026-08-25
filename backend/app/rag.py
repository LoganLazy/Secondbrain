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


def chat(question: str) -> dict:
    hits = ingest.search(question)
    if not hits:
        answer = "你的知识库里还没有任何资料，先上传一些文档吧。"
        return {"answer": answer, "sources": []}

    context = build_context(hits)
    history = [
        {"role": r["role"], "content": r["content"]}
        for r in db.get().execute(
            "SELECT role,content FROM chats ORDER BY id DESC LIMIT 6"
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

    sources = [{"title": h["title"], "filename": h["filename"],
                "page": h["page"], "score": round(h["score"], 3)}
               for h in hits]
    save_chat("user", question)
    save_chat("assistant", answer, sources)
    return {"answer": answer, "sources": sources}


def save_chat(role: str, content: str, sources: list | None = None):
    db.get().execute(
        "INSERT INTO chats(role,content,sources,created) VALUES(?,?,?,?)",
        (role, content, json.dumps(sources or [], ensure_ascii=False), db.now()),
    )
    db.get().commit()
