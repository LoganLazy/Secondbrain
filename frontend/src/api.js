const BASE = ""

async function jfetch(url, opts = {}) {
  const r = await fetch(BASE + url, {
    headers: { "Content-Type": "application/json" },
    ...opts
  })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try { msg = (await r.json()).detail || msg } catch (e) {}
    const error = new Error(typeof msg === 'string' ? msg : `HTTP ${r.status}`)
    error.status = r.status
    throw error
  }
  return r.json()
}

export const api = {
  health: () => jfetch('/api/health'),
  kbs: () => jfetch("/api/kbs"),
  createKb: (name) => jfetch("/api/kbs", { method: "POST", body: JSON.stringify({ name }) }),
  delKb: (id) => jfetch(`/api/kbs/${id}`, { method: "DELETE" }),
  stats: () => jfetch("/api/stats"),
  rebuildIndex: () => jfetch("/api/index/rebuild", { method: "POST" }),
  importJobs: () => jfetch('/api/import/jobs'),
  importControl: (id, action) => jfetch(`/api/import/jobs/${id}/${action}`, {method:'POST'}),
  restoreStatus: () => jfetch('/api/backup/restore-status'),
  restoreBackup: (value) => jfetch('/api/backup/restore', {method:'POST', body:JSON.stringify(value)}),
  cancelRestore: () => jfetch('/api/backup/restore-cancel', {method:'POST'}),
  async previewBackup(file) {
    const fd = new FormData(); fd.append('file', file)
    return jfetch('/api/backup/preview', {method:'POST', headers:{}, body:fd})
  },
  docs: () => jfetch("/api/docs"),
  delDoc: (id) => jfetch(`/api/docs/${id}`, { method: "DELETE" }),
  updateDoc: (id, changes) => jfetch(`/api/docs/${id}`, {method:'PATCH', body:JSON.stringify(changes)}),
  search: (query, k) => jfetch("/api/search", { method: "POST", body: JSON.stringify({ query, k }) }),
  searchDetails: (query, mode, signal) => jfetch('/api/search/details', {method:'POST', signal, body:JSON.stringify({query, mode})}),
  chat: (question) => jfetch("/api/chat", { method: "POST", body: JSON.stringify({ question }) }),
  history: (sessionId = "") => jfetch(`/api/history${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`),
  memoryList: () => jfetch("/api/memory"),
  addMemory: (content) => jfetch("/api/memory", { method: "POST", body: JSON.stringify({ content }) }),
  delMemory: (id) => jfetch(`/api/memory/${id}`, { method: "DELETE" }),
  fcList: (docId) => jfetch(`/api/flashcards${docId ? `?doc_id=${docId}` : ""}`),
  fcDue: (docId) => jfetch(`/api/flashcards/due${docId ? `?doc_id=${docId}` : ''}`),
  generateCards: (doc_id, num, signal) => jfetch('/api/flashcards/generate', {method:'POST', signal, body:JSON.stringify({doc_id, num})}),
  answerCard: (id, result, expected_reviews, signal) => jfetch(`/api/flashcards/${id}/answer`, {method:'POST', signal, body:JSON.stringify({result, expected_reviews})}),
  fcStats: () => jfetch("/api/flashcards/stats"),
  delCard: (id) => jfetch(`/api/flashcards/${id}`, { method: "DELETE" }),
  importLinks: (urls) => jfetch("/api/import/links", { method: "POST", body: JSON.stringify({ urls }) }),
  sessions: () => jfetch("/api/sessions"),
  newSession: () => jfetch("/api/sessions", { method: "POST", body: "{}" }),

  async uploadFiles(files) {
    const fd = new FormData()
    files.forEach((f) => fd.append("files", f))
    const r = await fetch(BASE + "/api/import/jobs", { method: "POST", body: fd })
    if (!r.ok) {
      let msg = `HTTP ${r.status}`
      try { msg = (await r.json()).detail || msg } catch (e) {}
      throw new Error(msg)
    }
    return r.json()
  }
}
