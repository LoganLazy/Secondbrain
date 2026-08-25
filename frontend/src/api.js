const BASE = ""

async function jfetch(url, opts = {}) {
  const r = await fetch(BASE + url, {
    headers: { "Content-Type": "application/json" },
    ...opts
  })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try { msg = (await r.json()).detail || msg } catch (e) {}
    throw new Error(msg)
  }
  return r.json()
}

export const api = {
  kbs: () => jfetch("/api/kbs"),
  createKb: (name) => jfetch("/api/kbs", { method: "POST", body: JSON.stringify({ name }) }),
  delKb: (id) => jfetch(`/api/kbs/${id}`, { method: "DELETE" }),
  stats: () => jfetch("/api/stats"),
  docs: () => jfetch("/api/docs"),
  delDoc: (id) => jfetch(`/api/docs/${id}`, { method: "DELETE" }),
  search: (query, k) => jfetch("/api/search", { method: "POST", body: JSON.stringify({ query, k }) }),
  chat: (question) => jfetch("/api/chat", { method: "POST", body: JSON.stringify({ question }) }),
  history: () => jfetch("/api/history"),
  memoryList: () => jfetch("/api/memory"),
  addMemory: (content) => jfetch("/api/memory", { method: "POST", body: JSON.stringify({ content }) }),
  delMemory: (id) => jfetch(`/api/memory/${id}`, { method: "DELETE" }),
  fcList: (docId) => jfetch(`/api/flashcards${docId ? `?doc_id=${docId}` : ""}`),
  fcDue: () => jfetch("/api/flashcards/due"),
  fcStats: () => jfetch("/api/flashcards/stats"),
  delCard: (id) => jfetch(`/api/flashcards/${id}`, { method: "DELETE" }),

  async uploadFiles(files) {
    const fd = new FormData()
    files.forEach((f) => fd.append("files", f))
    const r = await fetch(BASE + "/api/upload", { method: "POST", body: fd })
    if (!r.ok) {
      let msg = `HTTP ${r.status}`
      try { msg = (await r.json()).detail || msg } catch (e) {}
      throw new Error(msg)
    }
    return r.json()
  }
}
