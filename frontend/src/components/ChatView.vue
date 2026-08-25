<template>
  <div class="chat">
    <div class="messages" ref="box">
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
import { ref, nextTick } from "vue"
import { api } from "../api"

defineEmits(["openDoc"])
const list = ref([])
const draft = ref("")
const thinking = ref(false)
const box = ref(null)

async function send() {
  const q = draft.value.trim()
  if (!q || thinking.value) return
  draft.value = ""
  list.value.push({ role: "user", content: q })
  thinking.value = true
  scroll()
  try {
    const r = await api.chat(q)
    list.value.push({ role: "assistant", content: r.answer, sources: r.sources })
  } catch (e) {
    list.value.push({ role: "assistant", content: "出错了: " + e.message })
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
