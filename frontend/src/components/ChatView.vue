<template>
  <div class="chat">
    <div class="messages" ref="box">
      <div v-if="review && (review.due_cards || review.picks?.length)" class="review-banner">
        <div class="rb-line">
          🔔 今日回顾:
          <button v-if="review.due_cards" class="rb-btn"
                  @click="$emit('switchTab', 'cards')">
            {{ review.due_cards }} 张闪卡待复习 →
          </button>
        </div>
        <div v-if="review.picks?.length" class="rb-picks">
          推荐重读:
          <button v-for="p in review.picks" :key="p.id" class="rb-btn"
                  @click="$emit('openDoc', p)">
            《{{ p.title || '未命名' }}》
          </button>
        </div>
      </div>

      <div v-if="list.length === 0" class="empty">
        <div class="e-icon">💬</div>
        <h3>问点你资料里的事</h3>
        <p>比如：「我之前是怎么配置网络代理的？」</p>
      </div>

      <div v-for="(m, i) in list" :key="i" :class="['msg', m.role]">
        <div class="avatar">{{ m.role === "user" ? "我" : "AI" }}</div>
        <div class="bubble">
          <div class="content">{{ m.content }}</div>
          <div v-if="m.sources && m.sources.length" class="sources">
            <span class="s-title">参考资料</span>
            <a v-for="(s, si) in m.sources" :key="si" class="chip"
               @click="$emit('openDoc', s)">
              📄 {{ s.title }} <em>第{{ s.page }}页 · {{ Math.round(s.score * 100) }}%匹配</em>
            </a>
          </div>
        </div>
      </div>

      <div v-if="thinking" class="msg assistant">
        <div class="avatar">AI</div>
        <div class="bubble thinking">正在检索你的知识库…</div>
      </div>
    </div>

    <div class="inputbar">
      <input
        v-model="draft"
        placeholder="输入问题，Enter 发送…"
        :disabled="thinking"
        @keydown.enter="send"
      />
      <button :disabled="thinking || !draft.trim()" @click="send">发送</button>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from "vue"
import { api } from "../api"

defineEmits(["openDoc", "switchTab"])
const list = ref([])
const draft = ref("")
const thinking = ref(false)
const box = ref(null)
const review = ref(null)

onMounted(async () => {
  loadHistory()
  try {
    const r = await fetch("/api/review/today")
    review.value = await r.json()
  } catch (e) {}
})

async function send() {
  const q = draft.value.trim()
  if (!q || thinking.value) return
  draft.value = ""
  list.value.push({ role: "user", content: q })
  thinking.value = true
  scroll()
  try {
    const resp = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q })
    })
    if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status)
    const reader = resp.body.getReader()
    const dec = new TextDecoder()
    let buf = ""
    let cur = null
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let i
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i).trim()
        buf = buf.slice(i + 2)
        if (!line.startsWith("data:")) continue
        let ev
        try { ev = JSON.parse(line.slice(5)) } catch (err) { continue }
        if (ev.type === "sources") {
          cur = { role: "assistant", content: "", sources: ev.sources }
          list.value.push(cur)
        } else if (ev.type === "delta") {
          if (!cur || list.value[list.value.length - 1] !== cur) {
            cur = cur && list.value.includes(cur) ? cur : { role: "assistant", content: "" }
            list.value.push(cur)
          }
          cur.content += ev.text
          scroll()
        }
      }
    }
    if (cur && !cur.content) cur.content = "(AI未能给出有效回答，请重试)"
  } catch (e) {
    list.value.push({ role: "assistant", content: "网络错误: " + e.message })
  }
  thinking.value = false
  scroll()
}

async function loadHistory() {
  try { list.value = await api.history() } catch (e) {}
}
loadHistory()

function scroll() {
  nextTick(() => box.value && (box.value.scrollTop = box.value.scrollHeight))
}
</script>

<style scoped>
.chat { display: flex; flex-direction: column; height: 100%; }
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
