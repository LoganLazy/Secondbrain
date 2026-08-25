<template>
  <div class="reader">
    <!-- 左侧: 原文 -->
    <div class="doc-pane">
      <div class="doc-head">
        <button class="back" @click="$emit('close')">← 返回</button>
        <span class="doc-title">{{ doc.title || doc.filename }}</span>
      </div>

      <!-- 工具栏 -->
      <div class="tools">
        <button @click="prevPage" :disabled="idx <= 0">◀ 上一页</button>
        <span class="page-ind">
          第 <input class="jump" v-model.number="jumpTo" @keydown.enter="goPage(jumpTo)" /> / {{ pages.length }} 页
        </span>
        <button @click="nextPage" :disabled="idx >= pages.length - 1">下一页 ▶</button>
        <span class="sep"></span>
        <button @click="fontSize = Math.max(13, fontSize - 1)" title="缩小字体">A-</button>
        <button @click="fontSize = Math.min(26, fontSize + 1)" title="放大字体">A+</button>
      </div>

      <div class="pages" ref="pagesBox" tabindex="0" @keydown="onKey">
        <div v-if="loadErr" class="load-err">{{ loadErr }}</div>
        <div v-else-if="pages.length" class="page"
             :style="{ fontSize: fontSize + 'px' }"
             @mouseup="onSelect" @touchend="onSelect">
          <div class="page-no">{{ pages[idx].page }}</div>
          <div class="page-text">{{ pages[idx].text }}</div>
        </div>
        <div v-else class="load-err">加载中…</div>

        <!-- 划词浮动按钮 -->
        <div v-if="selection" class="sel-float">
          <button @click="askSelected('解释这段话')">💬 解释这段</button>
          <button @click="askSelected('这段话的重点是什么？')">📌 划重点</button>
          <button @click="askSelected('翻译成中文(如果是外文)或用大白话再讲一遍')">🔁 换个说法</button>
        </div>
      </div>
    </div>

    <!-- 右侧: AI助手 -->
    <div class="ai-pane">
      <div class="quick">
        <span class="q-label">快捷操作:</span>
        <button v-for="a in quicks" :key="a.label" :disabled="busy"
                @click="runQuick(a)">{{ a.label }}</button>
      </div>
      <div class="ai-msgs" ref="aiBox">
        <div v-if="!msgs.length" class="ai-empty">
          选中左侧文字提问，或点上面的快捷操作
        </div>
        <div v-for="(m, i) in msgs" :key="i" :class="['m', m.role]">
          <div class="m-content">{{ m.content }}</div>
          <button v-if="m.role === 'assistant'" class="copy" @click="copy(m)">复制</button>
        </div>
        <div v-if="busy" class="m assistant"><div class="m-content thinking">思考中…</div></div>
      </div>
      <div class="ask-bar">
        <input v-model="draft" placeholder="针对当前页提问…" @keydown.enter="askDraft" />
        <button :disabled="busy" @click="askDraft">问</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, onUnmounted } from "vue"

const props = defineProps({ doc: Object })
defineEmits(["close"])

const pages = ref([])
const msgs = ref([])
const busy = ref(false)
const selection = ref("")
const selPage = ref(null)
const draft = ref("")
const aiBox = ref(null)
const idx = ref(0)
const jumpTo = ref(1)
const fontSize = ref(16)
const loadErr = ref("")

const quicks = [
  { label: "📝 总结全文", question: "请总结这份文档的核心内容", scope: "all" },
  { label: "💡 解释本页", question: "用大白话解释这一页的内容", scope: "page" },
  { label: "📌 提取重点", question: "提取这一页的关键要点，分条列出", scope: "page" },
  { label: "📓 生成笔记", question: "把这一页整理成结构化学习笔记(markdown要点式)", scope: "page" },
  { label: "❓ 出3道题", question: "基于这一页内容出3道自测题并附答案", scope: "page" }
]

async function load() {
  try {
    const res = await fetch(`/api/docs/${props.doc.id}/content`)
    const r = await res.json()
    if (!res.ok) throw new Error(r.detail || "加载失败")
    pages.value = r.pages
    jumpTo.value = pages.value[0]?.page ?? 1
  } catch (e) {
    loadErr.value = "原文加载失败: " + e.message + "（可能已被删除或丢失，请重新上传）"
  }
}
load()

function goPage(n) {
  if (!n || n < 1 || n > pages.value.length) return
  const target = pages.value.findIndex((p) => p.page === n)
  if (target >= 0) {
    idx.value = target
    selection.value = ""
    aiBox.value?.scrollTo?.(0, 0)
  }
}
function prevPage() { goPage(pages.value[Math.max(0, idx.value - 1)].page) }
function nextPage() { goPage(pages.value[Math.min(pages.value.length - 1, idx.value + 1)].page) }

function onKey(e) {
  if (e.key === "ArrowLeft") prevPage()
  else if (e.key === "ArrowRight") nextPage()
}
onMounted(() => window.addEventListener("keydown", onKey))
onUnmounted(() => window.removeEventListener("keydown", onKey))

function onSelect(e) {
  const s = window.getSelection().toString().trim()
  if (s.length > 1) {
    selection.value = s.slice(0, 2000)
    selPage.value = pages.value[idx.value]?.page ?? null
  } else {
    selection.value = ""
  }
}

async function run(question, passage, page) {
  if (busy.value) return
  busy.value = true
  msgs.value.push({ role: "user",
    content: passage ? `【选中的内容】${passage.slice(0, 120)}…\n${question}` : question })
  scroll()
  try {
    const r = await fetch("/api/assist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        passage: passage || "",
        title: props.doc.title || props.doc.filename,
        page: page ?? null
      })
    })
    const d = await r.json()
    msgs.value.push({ role: "assistant", content: d.answer || d.detail || "失败" })
  } catch (e) {
    msgs.value.push({ role: "assistant", content: "网络错误: " + e.message })
  }
  busy.value = false
  scroll()
}

function askSelected(q) {
  run(q, selection.value, selPage.value)
  selection.value = ""
  window.getSelection().removeAllRanges()
}

function runQuick(a) {
  const page = pages.value[idx.value]?.page ?? 1
  const passage = a.scope === "all"
    ? pages.value.map((p) => p.text).join("\n").slice(0, 12000)
    : (pages.value[idx.value]?.text || "")
  const q = a.scope === "all" ? a.question : `${a.question}（当前是第${page}页）`
  run(q, passage, a.scope === "all" ? null : page)
}

function askDraft() {
  const q = draft.value.trim()
  if (!q) return
  draft.value = ""
  const page = pages.value[idx.value]?.page ?? 1
  const passage = pages.value[idx.value]?.text || ""
  run(q, passage, page)
}

function copy(m) { navigator.clipboard.writeText(m.content) }
function scroll() { nextTick(() => aiBox.value && (aiBox.value.scrollTop = aiBox.value.scrollHeight)) }
</script>

<style scoped>
.reader { display: flex; height: 100%; }

.doc-pane { flex: 1.4; display: flex; flex-direction: column; border-right: 1px solid var(--border); min-width: 0; }
.doc-head {
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 14px;
}
.back { background: var(--panel2); color: var(--text); border: none; border-radius: 8px; padding: 8px 14px; cursor: pointer; }
.doc-title { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.tools {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--border);
}
.tools button {
  background: var(--panel2); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 7px 13px; cursor: pointer; font-size: 13.5px;
}
.tools button:hover:not(:disabled) { border-color: var(--accent); }
.tools button:disabled { opacity: .35; cursor: default; }
.page-ind { color: var(--muted); font-size: 13.5px; display: flex; align-items: center; gap: 5px; }
.jump {
  width: 52px; text-align: center;
  background: var(--bg); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 4px; outline: none;
}
.sep { width: 1px; height: 18px; background: var(--border); margin: 0 4px; }

.pages { flex: 1; overflow-y: auto; padding: 24px 30px; position: relative; outline: none; }
.page {
  max-width: 720px;
  margin: 0 auto;
  background: #fdfbf7;
  color: #2a2a2a;
  border-radius: 12px;
  box-shadow: 0 3px 14px rgba(0,0,0,.25);
  padding: 44px 48px;
  line-height: 2.0;
  white-space: pre-wrap;
  min-height: 60vh;
}
.page-no { color: #b9b2a5; font-size: 12px; margin-bottom: 14px; user-select: none; text-align: center; }

.load-err {
  background: #3a2226; color: #ff9b9b;
  border-radius: 10px; padding: 16px 20px; font-size: 14px;
}

.sel-float {
  position: sticky;
  bottom: 14px;
  margin: 0 auto;
  width: fit-content;
  z-index: 20;
  background: var(--panel);
  border: 1px solid var(--accent);
  border-radius: 10px;
  padding: 6px;
  display: flex;
  gap: 6px;
  box-shadow: 0 6px 18px rgba(0,0,0,.45);
}
.sel-float button {
  background: var(--panel2); color: var(--text);
  border: none; border-radius: 7px;
  padding: 7px 11px; cursor: pointer; font-size: 13px;
}
.sel-float button:hover { background: #2b3550; }

.ai-pane { flex: 1; display: flex; flex-direction: column; min-width: 380px; }
.quick {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
}
.q-label { color: var(--muted); font-size: 12.5px; }
.quick button {
  background: var(--panel2); color: var(--text);
  border: 1px solid var(--border); border-radius: 16px;
  padding: 6px 13px; cursor: pointer; font-size: 13px;
}
.quick button:hover:not(:disabled) { border-color: var(--accent); }
.quick button:disabled { opacity: 0.5; }

.ai-msgs { flex: 1; overflow-y: auto; padding: 16px; }
.ai-empty { color: var(--muted); text-align: center; margin-top: 40px; font-size: 13.5px; }
.m { margin-bottom: 14px; }
.m.user .m-content { background: #274067; }
.m.assistant .m-content { background: var(--panel2); }
.m-content {
  border-radius: 10px;
  padding: 11px 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  font-size: 14px;
}
.thinking { color: var(--muted); animation: blink 1.2s infinite; }
@keyframes blink { 50% { opacity: .5; } }
.copy {
  background: none; border: none; color: var(--muted);
  font-size: 12px; cursor: pointer; margin-top: 4px;
}

.ask-bar { display: flex; gap: 10px; padding: 14px 16px; border-top: 1px solid var(--border); }
.ask-bar input {
  flex: 1;
  background: var(--panel2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 13px;
  color: var(--text);
  outline: none;
}
.ask-bar input:focus { border-color: var(--accent); }
.ask-bar button {
  background: var(--accent); color: #fff; border: none;
  border-radius: 10px; padding: 0 22px; cursor: pointer;
}
</style>
