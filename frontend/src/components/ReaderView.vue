<template>
  <div class="reader">
    <!-- 左侧: 原文 -->
    <div class="doc-pane">
      <div class="doc-head">
        <button class="back" @click="$emit('close')">← {{ langv === "zh" ? "返回" : "Back" }}</button>
        <span class="doc-title">{{ doc.title || doc.filename }}</span>
        <a v-if="sourceUrl" class="src-link" :href="sourceUrl" target="_blank" rel="noopener noreferrer">🌐 原网页</a>
      </div>

      <!-- 工具栏 -->
      <div class="tools">
        <button @click="prevPage" :disabled="loading || idx <= 0">{{ L("prev") }}</button>
        <span class="page-ind">
          <span class="page-ind-txt">{{ L("page_n") }}</span> <input class="jump" aria-label="跳转页码" :disabled="loading" v-model.number="jumpTo" @keydown.enter="goPage(jumpTo)" /> / {{ pageTotal }}
          <small v-if="pageTotal !== pages.length">（可读 {{ pages.length }} 页）</small>
        </span>
        <button @click="nextPage" :disabled="loading || idx >= pages.length - 1">{{ L("next") }}</button>
        <template v-if="kind === 'pdf'">
          <span class="sep"></span>
          <button :class="{ on: viewMode === 'text' }" @click="viewMode = 'text'">{{ L("view_text") }}</button>
          <button :class="{ on: viewMode === 'original' }" @click="viewMode = 'original'; renderOriginal()">{{ L("view_original") }}</button>
        </template>
        <span class="sep"></span>
        <button @click="fontSize = Math.max(13, fontSize - 1)" title="缩小字体">A-</button>
        <button @click="fontSize = Math.min(26, fontSize + 1)" title="放大字体">A+</button>
      </div>

      <div class="findbar">
        <input v-model="findText" :disabled="loading" maxlength="256" placeholder="文内查找（区分大小写）" aria-label="文内查找" @keydown.enter="findNext(1)" />
        <span>{{ matches.length === 1000 ? '≥' : '' }}{{ matches.length ? activeFind + 1 : 0 }} / {{ matches.length }}</span>
        <button :disabled="!matches.length" @click="findNext(-1)" aria-label="上一个匹配">↑</button>
        <button :disabled="!matches.length" @click="findNext(1)" aria-label="下一个匹配">↓</button>
      </div>
      <div v-if="navigationNotice" class="reader-notice" role="status">{{ navigationNotice }}</div>
      <div v-if="renderErr" class="reader-notice" role="alert">{{ renderErr }}</div>
      <div class="pages" ref="pagesBox" tabindex="0">
        <div v-if="loadErr" class="load-err">{{ loadErr }}</div>

        <template v-else-if="viewMode === 'original' && kind === 'pdf'">
          <canvas id="pdf-canvas" class="pdf-canvas"></canvas>
          <div v-if="rendering" class="rendering">渲染中…</div>
        </template>

        <template v-else-if="kind === 'image'">
          <img :src="`/api/docs/${doc.id}/file`" class="img-view" />
        </template>

        <div v-else-if="pages.length" class="page"
             :style="{ fontSize: fontSize + 'px' }"
             @mouseup="onSelect" @touchend="onSelect">
          <div class="page-no">{{ pages[idx].page }}</div>
          <div class="page-text"><template v-for="(part, n) in pageParts" :key="n"><mark v-if="part.hit" :class="{ active: part.active }">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></div>
        </div>
        <div v-else class="load-err">{{ L("loading") }}</div>

        <!-- 划词浮动按钮 -->
        <div v-if="selection" class="sel-float">
          <button @click="askSelected(langv === 'zh' ? '解释这段话' : 'Explain this passage')">💬 {{ langv === "zh" ? "解释这段" : "Explain" }}</button>
          <button @click="askSelected(langv === 'zh' ? '这段话的重点是什么？' : 'What are the key points here?')">📌 {{ langv === "zh" ? "划重点" : "Points" }}</button>
          <button @click="askSelected(langv === 'zh' ? '翻译成中文(如果是外文)或用大白话再讲一遍' : 'Translate to English if foreign, or rephrase simply')">🔁 {{ langv === "zh" ? "换个说法" : "Rephrase" }}</button>
        </div>
      </div>
    </div>

    <!-- 右侧: AI助手 -->
    <div class="ai-pane">
      <div class="quick">
        <span class="q-label">快捷操作:</span>
        <button v-for="a in quicks" :key="a.label" :disabled="busy || loading || !!loadErr"
                @click="runQuick(a)">{{ a.label }}</button>
      </div>
      <div class="ai-msgs" ref="aiBox">
        <div v-if="!msgs.length" class="ai-empty">
          {{ L("ai_empty") }}
        </div>
        <div v-for="(m, i) in msgs" :key="i" :class="['m', m.role]">
          <div class="m-content">{{ m.content }}</div>
          <div v-if="m.notice" class="scope-notice">{{ m.notice }}</div>
          <button v-for="(source, n) in m.sources || []" :key="n" class="reader-source" @click="goPage(source.page)">[{{ n + 1 }}] {{ source.filename }} · 第{{ source.page }}页</button>
          <button v-if="m.role === 'assistant'" class="copy" @click="copy(m)">{{ L("copy") }}</button>
        </div>
        <div v-if="busy" class="m assistant"><div class="m-content thinking">思考中…</div></div>
      </div>
      <div class="ask-bar">
        <input v-model="draft" :disabled="busy || loading || !!loadErr" :placeholder="L('ask_page_ph')" @keydown.enter="askDraft" />
        <button :disabled="busy || loading || !!loadErr || !draft.trim()" @click="askDraft">{{ L("ask") }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from "vue"
import { t as _t, lang as _lang } from "../i18n"
import * as pdfjsLib from "pdfjs-dist"
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url"

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl
const props = defineProps({ doc: Object })
const L = (k) => _t(k)
const langv = _lang
defineEmits(["close"])

const pages = ref([])
const msgs = ref([])
const busy = ref(false)
const loading = ref(true)
const selection = ref("")
const selPage = ref(null)
const draft = ref("")
const aiBox = ref(null)
const pagesBox = ref(null)
const idx = ref(0)
const jumpTo = ref(1)
const fontSize = ref(16)
const loadErr = ref("")
const sourceUrl = ref("")
const kind = ref("text")
const viewMode = ref("text")
const rendering = ref(false)
const renderErr = ref("")
const navigationNotice = ref("")
const physicalPages = ref(0)
const findText = ref("")
const activeFind = ref(0)
const kb = localStorage.getItem("kb") || "default"
let progressKey = "", disposed = false, renderSequence = 0
let pdfTask = null, pdfPromise = null, renderTask = null, assistantController = null
const loadController = new AbortController()
const pageTotal = computed(() => physicalPages.value || pages.value.reduce((total, p) => Math.max(total, p.page), 0))

const quicks = computed(() => [
  { label: L("qa_sum_all"), question: langv.value === "zh" ? "请总结提供的文档范围内的核心内容" : "Summarize the provided document context", scope: "document" },
  { label: L("qa_explain_page"), question: langv.value === "zh" ? "用大白话解释这一页的内容" : "Explain this page in plain language", scope: "page" },
  { label: L("qa_key_points"), question: langv.value === "zh" ? "提取这一页的关键要点，分条列出" : "Extract the key points of this page", scope: "page" },
  { label: L("qa_notes"), question: langv.value === "zh" ? "把这一页整理成结构化学习笔记" : "Turn this page into structured study notes", scope: "page" },
  { label: L("qa_quiz"), question: langv.value === "zh" ? "基于这一页内容出3道自测题并附答案" : "Create 3 self-test questions with answers from this page", scope: "page" }
])

const matches = computed(() => {
  const needle = findText.value
  const result = []
  if (!needle) return result
  for (let pageIndex = 0; pageIndex < pages.value.length; pageIndex++) {
    const text = pages.value[pageIndex].text
    let start = 0
    while ((start = text.indexOf(needle, start)) !== -1) {
      result.push({ pageIndex, start, end: start + needle.length })
      if (result.length >= 1000) return result
      start += needle.length
    }
  }
  return result
})
const pageParts = computed(() => {
  const text = pages.value[idx.value]?.text || ""
  const parts = []
  let cursor = 0
  matches.value.forEach((match, n) => {
    if (match.pageIndex !== idx.value) return
    parts.push({ text: text.slice(cursor, match.start) })
    parts.push({ text: text.slice(match.start, match.end), hit: true, active: n === activeFind.value })
    cursor = match.end
  })
  parts.push({ text: text.slice(cursor) })
  return parts
})
watch(findText, () => {
  activeFind.value = 0
  showMatch()
})

async function showMatch() {
  const match = matches.value[activeFind.value]
  if (!match) return
  await goPage(pages.value[match.pageIndex].page)
  await nextTick()
  pagesBox.value?.querySelector("mark.active")?.scrollIntoView({ block: "center" })
}
function findNext(direction) {
  if (!matches.value.length) return
  activeFind.value = (activeFind.value + direction + matches.value.length) % matches.value.length
  showMatch()
}
function saveProgress() {
  if (loading.value || !progressKey || !pages.value[idx.value]) return
  try { localStorage.setItem(progressKey, JSON.stringify({ page: pages.value[idx.value].page })) } catch {}
}
watch(idx, saveProgress)

async function load() {
  try {
    const res = await fetch("/api/docs/" + props.doc.id + "/content", { signal: loadController.signal })
    if (!res.ok) throw new Error("文档不存在或无法读取")
    const r = await res.json()
    if (disposed) return
    pages.value = r.pages || []
    if (!pages.value.length) throw new Error("文档没有可读文字")
    sourceUrl.value = r.source_url || ""
    kind.value = r.kind || "text"
    progressKey = "memoryReader:" + kb + ":" + props.doc.id + ":" + (r.revision || "")
    let savedPage
    try { savedPage = JSON.parse(localStorage.getItem(progressKey) || "null")?.page } catch {}
    // 明确的来源页码优先于阅读进度；版本变化后不沿用旧位置。
    const target = props.doc.page ?? savedPage
    const selected = pages.value.findIndex(p => p.page === target)
    idx.value = selected >= 0 ? selected : 0
    jumpTo.value = pages.value[idx.value].page
  } catch (e) {
    if (e.name !== "AbortError") loadErr.value = L("load_fail") + e.message
  } finally {
    loading.value = false
  }
}

async function goPage(value) {
  if (loading.value || !pages.value.length) return
  const page = Number(value)
  const target = Number.isInteger(page) ? pages.value.findIndex(p => p.page === page) : -1
  if (target < 0) {
    navigationNotice.value = "该页没有可读文字或页码无效，请选择已有文字的页码。"
    jumpTo.value = pages.value[idx.value].page
    return
  }
  navigationNotice.value = ""
  idx.value = target
  selection.value = ""
  jumpTo.value = page
  saveProgress()
  if (pagesBox.value) pagesBox.value.scrollTop = 0
  if (viewMode.value === "original") await renderOriginal()
}

function ensurePdf() {
  if (!pdfPromise) {
    pdfTask = pdfjsLib.getDocument({
      url: "/api/docs/" + props.doc.id + "/file",
      httpHeaders: { "X-KB-ID": kb }
    })
    pdfPromise = pdfTask.promise.then(pdf => {
      physicalPages.value = pdf.numPages
      return pdf
    }).catch(error => { pdfPromise = null; throw error })
  }
  return pdfPromise
}
async function renderOriginal() {
  if (kind.value !== "pdf" || !pages.value.length || disposed) return
  const sequence = ++renderSequence
  renderTask?.cancel()
  rendering.value = true
  renderErr.value = ""
  const pageNo = pages.value[idx.value].page
  try {
    await nextTick()
    const pdf = await ensurePdf()
    if (disposed || sequence !== renderSequence || viewMode.value !== "original") return
    const page = await pdf.getPage(pageNo)
    if (disposed || sequence !== renderSequence) return
    const canvas = pagesBox.value?.querySelector("canvas")
    if (!canvas) return
    const viewport = page.getViewport({ scale: 2 })
    canvas.width = viewport.width
    canvas.height = viewport.height
    renderTask = page.render({ canvasContext: canvas.getContext("2d"), viewport })
    await renderTask.promise
  } catch (e) {
    if (!disposed && sequence === renderSequence && e?.name !== "RenderingCancelledException") {
      renderErr.value = "PDF 原件显示失败，可切回文字模式阅读或重新打开文档。"
    }
  } finally {
    if (sequence === renderSequence) rendering.value = false
  }
}
function prevPage() { if (idx.value > 0) goPage(pages.value[idx.value - 1].page) }
function nextPage() { if (idx.value + 1 < pages.value.length) goPage(pages.value[idx.value + 1].page) }
function onKey(e) {
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey ||
      e.target?.closest?.("input,textarea,select,button,[contenteditable]")) return
  if (e.key === "ArrowLeft") { e.preventDefault(); prevPage() }
  else if (e.key === "ArrowRight") { e.preventDefault(); nextPage() }
}
onMounted(() => { load(); window.addEventListener("keydown", onKey) })
onUnmounted(() => {
  saveProgress()
  disposed = true
  renderSequence++
  loadController.abort()
  assistantController?.abort()
  renderTask?.cancel()
  if (pdfTask) Promise.resolve(pdfTask.destroy()).catch(() => {})
  window.removeEventListener("keydown", onKey)
})

function onSelect() {
  const chosen = window.getSelection()
  if (!chosen || !pagesBox.value?.contains(chosen.anchorNode) || !pagesBox.value?.contains(chosen.focusNode)) {
    selection.value = ""
    return
  }
  const text = chosen.toString().trim()
  selection.value = text.length > 1 ? text.slice(0, 2000) : ""
  selPage.value = pages.value[idx.value]?.page ?? null
}

async function run(question, scope = "page", passage = "", page = pages.value[idx.value]?.page) {
  if (busy.value || loading.value || loadErr.value) return
  busy.value = true
  assistantController = new AbortController()
  msgs.value.push({ role: "user", content: (scope === "document" ? "【文档范围】" : "【第" + page + "页】") + question })
  scroll()
  try {
    const r = await fetch("/api/assist", {
      method: "POST",
      signal: assistantController.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id: props.doc.id, question, scope, passage, page: scope === "document" ? null : page })
    })
    const d = await r.json()
    if (disposed) return
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "请求参数无效")
    msgs.value.push({ role: "assistant", content: d.answer, sources: d.sources, notice: d.notice })
  } catch (e) {
    if (!disposed && e.name !== "AbortError") msgs.value.push({
      role: "assistant", content: "阅读助手暂时无法完成请求，请检查网络或重新选择原文后重试。"
    })
  } finally {
    assistantController = null
    busy.value = false
    scroll()
  }
}
function askSelected(question) {
  run(question, "selection", selection.value, selPage.value)
  selection.value = ""
  window.getSelection()?.removeAllRanges()
}
function runQuick(action) { run(action.question, action.scope) }
function askDraft() {
  const question = draft.value.trim()
  if (!question || busy.value || loading.value || loadErr.value) return
  draft.value = ""
  run(question)
}
async function copy(message) {
  try { await navigator.clipboard.writeText(message.content) }
  catch { navigationNotice.value = "复制失败，请手动选择文字复制。" }
}
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
  flex-wrap: wrap;
  padding: 10px 20px;
  border-bottom: 1px solid var(--border);
}
.tools button {
  background: var(--panel2); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 7px 13px; cursor: pointer; font-size: 13.5px;
}
.tools button:hover:not(:disabled) { border-color: var(--accent); }
.tools button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.pdf-canvas { max-width: 100%; margin: 0 auto; display: block; box-shadow: 0 3px 14px rgba(0,0,0,.35); border-radius: 8px; }
.rendering { text-align: center; color: var(--muted); padding: 20px; }
.img-view { max-width: 100%; max-height: 75vh; display: block; margin: 0 auto; border-radius: 10px; }
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
.findbar { display:flex; align-items:center; gap:8px; padding:10px 20px; border-bottom:1px solid var(--border); }
.findbar input { flex:1; min-width:80px; padding:8px; border:1px solid var(--border); border-radius:8px; background:var(--panel2); color:var(--text); }
.findbar span { font-size:12px; color:var(--muted); white-space:nowrap; }
.findbar button, .reader-source { background:var(--panel2); color:var(--text); border:1px solid var(--border); border-radius:7px; padding:5px 9px; cursor:pointer; }
.findbar button:disabled { opacity:.4; cursor:default; }
.reader-source { font-size:12px; margin:6px 6px 0 0; }
.reader-notice, .scope-notice { padding:8px 16px; font-size:13px; color:var(--muted); }
.page-text mark { background:#ffe89a; color:inherit; border-radius:2px; }
.page-text mark.active { background:#ffc14d; outline:2px solid #c48416; }
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
