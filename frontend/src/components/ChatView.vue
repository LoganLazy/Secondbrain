<template>
  <div class="chat">
    <div class="sess-bar">
      <button class="sb-new" :disabled="thinking || loading" @click="newSession">{{ L("sess_new") }}</button>
      <select v-model="currentSid" :disabled="thinking || loading" @change="switchSession" class="sb-select">
        <option v-for="ss in sessions" :key="ss.id" :value="ss.id">{{ ss.title }}</option>
      </select>
      <button class="sb-icon" :disabled="thinking || loading || !currentSid" :title="L('sess_rename_t')" @click="renameSession">✏</button>
      <button class="sb-icon" :disabled="thinking || loading || !currentSid" :title="t('sess_del_c')" @click="delSession">🗑</button>
    </div>

    <div class="messages" ref="box">
      <div v-if="review && (review.due_cards || review.picks?.length)" class="review-banner">
        <div class="rb-line">
          🔔 {{ L("review_today") }}
          <button v-if="review.due_cards" class="rb-btn"
                  @click="$emit('switchTab', 'cards')">
            {{ review.due_cards }} {{ L("cards_due") }}
          </button>
        </div>
        <div v-if="review.picks?.length" class="rb-picks">
          {{ L("reread") }}
          <button v-for="p in review.picks" :key="p.id" class="rb-btn"
                  @click="$emit('openDoc', p)">
            《{{ p.title }}》
          </button>
        </div>
      </div>

      <div v-if="list.length === 0" class="empty">
        <div class="e-icon">💬</div>
        <h3>{{ L("empty_h") }}</h3>
        <p>{{ L("empty_p") }}</p>
      </div>

      <div v-for="(m, i) in list" :key="i" :class="['msg', m.role]">
        <div class="avatar">{{ m.role === "user" ? (lang === "zh" ? "我" : "Me") : "AI" }}</div>
        <div class="bubble">
          <div class="content">{{ m.content }}</div>
          <div v-if="m.sources && m.sources.length" class="sources">
            <span class="s-title">{{ L("sources") }}</span>
            <button v-for="(s, si) in m.sources" :key="si" class="chip" :disabled="!s.doc_id && !s.id"
               @click="$emit('openDoc', s)">
              [{{ si + 1 }}] 📄 {{ s.title }} <em>{{ L("page_n") }}{{ s.page }}<template v-if="Number.isFinite(s.score)"> · {{ lang === 'zh' ? '相关度' : 'Relevance' }} {{ Math.round(s.score * 100) }}%</template></em>
            </button>
            <details class="cite-details">
              <summary>{{ L("view_passages") }}</summary>
              <div v-for="(s, si) in m.sources" :key="'t' + si" class="cite-item">
                <b>《{{ s.title }}》 {{ s.page }}</b>
                <p>{{ s.text || '-' }}</p>
              </div>
            </details>
          </div>
        </div>
      </div>

      <div v-if="thinking" class="msg assistant">
        <div class="avatar">AI</div>
        <div class="bubble thinking">{{ L("thinking") }}</div>
      </div>
    </div>

    <div class="inputbar">
      <input
        v-model="draft"
        :placeholder="L('chat_ph')"
        :disabled="thinking || loading || !currentSid"
        @keydown.enter="send"
      />
      <button v-if="thinking" class="stop-answer" @click="controller?.abort()">{{ lang === 'zh' ? '停止接收' : 'Stop receiving' }}</button>
      <button v-else :disabled="loading || !currentSid || !draft.trim()" @click="send">{{ L("send") }}</button>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, nextTick, onMounted, onBeforeUnmount } from "vue"
import { api } from "../api"
import { t, lang } from "../i18n"
const L = computed(() => {
  void lang.value  // 依赖语言, 切换时刷新所有文案
  return (k, v) => t(k, v)
})

defineEmits(["openDoc", "switchTab"])
const list = ref([])
const draft = ref("")
const thinking = ref(false)
const loading = ref(true)
let controller = null
const box = ref(null)
const review = ref(null)
const sessions = ref([])
const currentSid = ref("")

function kbKey() { return "chatSid_" + (localStorage.getItem("kb") || "default") }

async function loadSessions() {
  try {
    sessions.value = await api.sessions()
    const saved = localStorage.getItem(kbKey())
    if (sessions.value.some((x) => x.id === saved)) currentSid.value = saved
    else if (sessions.value.length) currentSid.value = sessions.value[0].id
    else { await newSession(true); return }
    localStorage.setItem(kbKey(), currentSid.value)
  } catch (e) {
    list.value = [{ role: 'assistant', content: lang.value === 'zh' ? '会话加载失败，请刷新页面重试。' : 'Could not load sessions. Please refresh.' }]
  }
}

async function newSession(silent = false) {
  const r = await api.newSession()
  sessions.value.unshift(r)
  currentSid.value = r.id
  localStorage.setItem(kbKey(), r.id)
  list.value = []
}

async function switchSession() {
  localStorage.setItem(kbKey(), currentSid.value)
  loading.value = true
  try { await loadHistory() } finally { loading.value = false }
}

async function renameSession() {
  const cur = sessions.value.find((x) => x.id === currentSid.value)
  const _pt = prompt(t("sess_rename_t"), cur?.title || "")
  if (!_pt?.trim()) return
  await fetch(`/api/sessions/${currentSid.value}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: _pt.trim() })
  })
  if (cur) cur.title = _pt.trim()
}

async function delSession() {
  if (!confirm(t("sess_del_c"))) return
  await fetch(`/api/sessions/${currentSid.value}`, { method: "DELETE" })
  sessions.value = sessions.value.filter((x) => x.id !== currentSid.value)
  if (sessions.value.length) {
    currentSid.value = sessions.value[0].id
    await switchSession()
  } else {
    await newSession()
  }
}

onMounted(async () => {
  try {
    await loadSessions()
    if (currentSid.value) await loadHistory()
  } finally { loading.value = false }
  try {
    const r = await fetch("/api/review/today")
    review.value = await r.json()
  } catch (e) {}
})
onBeforeUnmount(() => controller?.abort())

async function send() {
  const q = draft.value.trim()
  if (!q || thinking.value || loading.value || !currentSid.value) return
  draft.value = ""
  list.value.push({ role: "user", content: q })
  thinking.value = true
  controller = new AbortController()
  const cur = reactive({ role: 'assistant', content: '', sources: [] })
  list.value.push(cur)
  let reader
  let completed = false
  scroll()
  try {
    const resp = await fetch("/api/chat/stream", {
      method: "POST",
      signal: controller.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, session_id: currentSid.value })
    })
    if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status)
    reader = resp.body.getReader()
    const dec = new TextDecoder()
    let buf = ""
    while (!completed) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      buf = buf.replace(/\r\n/g, '\n')
      let i
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i).trim()
        buf = buf.slice(i + 2)
        if (!line.startsWith("data:")) continue
        let ev
        try { ev = JSON.parse(line.slice(5)) } catch (err) { continue }
        if (ev.type === "sources") {
          cur.sources = ev.sources || []
        } else if (ev.type === "delta") {
          cur.content += ev.text
          scroll()
        } else if (ev.type === "replace") {
          cur.content = ev.text
          scroll()
        } else if (ev.type === "done") {
          completed = true
          break
        }
      }
    }
    if (!completed || !cur.content.trim()) throw new Error('Incomplete stream')
  } catch (e) {
    const note = e.name === 'AbortError'
      ? (lang.value === 'zh' ? '已停止接收，以上内容可能不完整。重新加载后以服务端记录为准。' : 'Stopped receiving. The answer may be incomplete; reload to check saved history.')
      : (lang.value === 'zh' ? '连接中断，回答可能不完整。请检查网络后重试；已接收的内容和来源保留在此页。' : 'Connection interrupted. This answer may be incomplete. Please retry.')
    cur.content += (cur.content ? '\n\n' : '') + note
  } finally {
    if (reader) {
      await reader.cancel().catch(() => {})
      reader.releaseLock()
    }
    controller = null
    thinking.value = false
    scroll()
  }
}

async function loadHistory(sid) {
  try {
    list.value = await api.history(sid ?? currentSid.value)
    scroll()
  } catch (e) {
    list.value = [{ role: 'assistant', content: lang.value === 'zh' ? '历史记录加载失败，请刷新页面重试。' : 'Could not load history. Please refresh.' }]
  }
}
function scroll() {
  nextTick(() => box.value && (box.value.scrollTop = box.value.scrollHeight))
}
</script>

<style scoped>
.chat { display: flex; flex-direction: column; height: 100%; }

.sess-bar {
  display: flex; gap: 8px; align-items: center;
  padding: 12px 16px 4px;
}
.sb-new {
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  color: #fff; border: none; border-radius: 9px;
  padding: 9px 15px; cursor: pointer; font-size: 13.5px;
  white-space: nowrap;
}
.sb-select {
  flex: 1; min-width: 0;
  background: var(--panel2); color: var(--text);
  border: 1px solid var(--border); border-radius: 9px;
  padding: 9px 10px; font-size: 13.5px; outline: none;
}
.sb-icon {
  background: var(--panel2); color: var(--muted);
  border: 1px solid var(--border); border-radius: 9px;
  width: 36px; height: 36px; cursor: pointer; flex-shrink: 0;
}
.sb-icon:hover { color: var(--text); border-color: var(--accent); }
.sess-bar :disabled, .chip:disabled { opacity: .5; cursor: default; }

.messages { flex: 1; overflow-y: auto; padding: 26px 34px; }

.empty { text-align: center; margin-top: 15vh; color: var(--muted); }
.e-icon { font-size: 52px; }
.empty h3 { color: var(--text); }

.msg { display: flex; gap: 12px; margin-bottom: 20px; }
.avatar {
  width: 36px; height: 36px; border-radius: 10px;
  background: var(--panel2);
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; color: var(--muted); flex-shrink: 0;
}
.msg.user .avatar { background: #2b4a8f; color: #fff; }
.bubble {
  max-width: 72%;
  background: var(--panel2);
  border-radius: 12px;
  padding: 13px 16px;
  line-height: 1.65;
  white-space: pre-wrap;
}
.msg.user .bubble { background: #274067; }

.sources { margin-top: 12px; border-top: 1px dashed var(--border); padding-top: 10px; }
.s-title { color: var(--muted); font-size: 12px; display: block; margin-bottom: 6px; }
.chip {
  display: inline-block;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 3px 9px;
  margin: 0 6px 6px 0;
  font-size: 12.5px;
  cursor: pointer;
  color: var(--text);
}
.chip em { color: var(--muted); font-style: normal; }
.chip:hover { border-color: var(--accent); }

.thinking { color: var(--muted); animation: blink 1.2s infinite; }
@keyframes blink { 50% { opacity: 0.5; } }

.inputbar {
  display: flex;
  gap: 12px;
  padding: 16px 34px;
  border-top: 1px solid var(--border);
}
.inputbar input {
  flex: 1;
  background: var(--panel2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 16px;
  color: var(--text);
  font-size: 15px;
  outline: none;
}
.inputbar input:focus { border-color: var(--accent); }
.inputbar button {
  background: var(--accent);
  border: none;
  color: #fff;
  border-radius: 12px;
  padding: 0 26px;
  font-size: 15px;
  cursor: pointer;
}
.inputbar button:disabled { opacity: 0.4; cursor: default; }
</style>
