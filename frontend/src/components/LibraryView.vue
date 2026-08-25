<template>
  <div class="lib">
    <div class="toolbar">
      <label class="upbtn" :class="{ busy }">
        {{ busy ? "处理中…" : "＋ 上传文档/图片 (可多选)" }}
        <input type="file" accept=".pdf,.docx,.txt,.md,.jpg,.png,.webp" multiple hidden @change="onFile" />
      </label>
      <button class="webbtn" @click="linkModal = true">🔗 导入网页</button>
      <input v-model="q" class="search" placeholder="🔍 语义搜索：用大白话描述你要找的东西，Enter 搜索"
             @keydown.enter="doSearch" />
    </div>

    <div v-if="err" class="err">{{ err }}</div>

    <div v-if="linkModal" class="mask">
      <div class="card modal">
        <h4 style="margin:0 0 10px">🔗 导入网页</h4>
        <textarea v-model="linksText" rows="5"
          placeholder="每行一个链接，如：&#10;https://某博客.com/文章&#10;https://mp.weixin.qq.com/s/xxx"></textarea>
        <div class="modal-btns">
          <button class="mbtn cancel" @click="linkModal = false">取消</button>
          <button class="mbtn ok" :disabled="importing || !linksText.trim()"
                  @click="doImportLinks">{{ importing ? "抓取中…" : "开始导入" }}</button>
        </div>
      </div>
    </div>
    <div v-if="results.length" class="up-results card">
      <div v-for="(r, i) in results" :key="i" class="up-line">
        {{ r.ok ? "✅" : "❌" }} {{ r.file }}
        <span v-if="r.ok">→ 《{{ r.title }}》</span>
        <span v-else class="up-err">{{ r.msg }}</span>
      </div>
      <button class="linkbtn" @click="results = []">知道了</button>
    </div>

    <div v-if="hits !== null" class="hits">
      <h4>搜索结果（{{ hits.length }}）<button class="linkbtn" @click="clearSearch">返回列表</button></h4>
      <div v-for="(h, i) in hits" :key="i" class="hit card" style="cursor:pointer"
           @click="$emit('openDoc', h)">
        <div class="hit-head">
          📄 {{ h.title }} · 第{{ h.page }}页
          <span class="score">{{ Math.round(h.score * 100) }}% 匹配</span>
          <button class="dbg-btn" @click.stop="h._dbg = !h._dbg">🔬</button>
        </div>
        <div v-if="h._dbg" class="dbg">
          语义分 {{ h.semantic?.toFixed?.(3) ?? h.semantic }} ·
          关键词分 {{ h.keyword?.toFixed?.(3) ?? h.keyword }} ·
          融合 = 语义×0.65 + 关键词×0.35
        </div>
        <p>{{ h.text.slice(0, 260) }}…</p>
      </div>
      <div v-if="!hits.length" class="none">没找到相关内容</div>
    </div>

    <div v-else class="docs">
      <div v-for="d in docs" :key="d.id" class="card doc" style="cursor:pointer" @click="$emit('openDoc', d)">
        <div class="doc-main">
          <div class="doc-title">
            📄 {{ d.title || d.filename }}
            <span class="cat">{{ d.category }}</span>
          </div>
          <div class="doc-summary">{{ d.summary || "（暂无摘要）" }}</div>
          <div class="doc-meta">
            <span v-for="t in d.tags" :key="t" class="tag">#{{ t }}</span>
            <span class="meta">{{ d.chunks }} 条知识 · {{ fmtTime(d.created) }}</span>
          </div>
        </div>
        <button class="del" title="删除" @click="del(d)">🗑</button>
      </div>
      <div v-if="!docs.length && !busy" class="none">知识库还是空的，上传第一份文档吧</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { api } from "../api"

defineEmits(["openDoc", "uploaded"])

const docs = ref([])
const q = ref("")
const hits = ref(null)
const busy = ref(false)
const err = ref("")
const results = ref([])
const linkModal = ref(false)
const linksText = ref("")
const importing = ref(false)

async function doImportLinks() {
  const urls = linksText.value.split("\n").map((x) => x.trim()).filter(Boolean)
  if (!urls.length) return
  importing.value = true
  try {
    const r = await fetch("/api/import/links", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls })
    })
    const d = await r.json()
    results.value = d.results || []
    linkModal.value = false
    load()
    window.dispatchEvent(new CustomEvent("kb-updated"))
  } catch (e) {
    err.value = "导入失败: " + e.message
  }
  importing.value = false
}

onMounted(load)
async function load() {
  docs.value = await api.docs()
}

async function onFile(e) {
  const files = [...e.target.files]
  e.target.value = ""
  if (!files.length) return
  busy.value = true
  err.value = ""
  results.value = []
  try {
    const r = await api.uploadFiles(files)
    results.value = r.results || []
    await load()
  } catch (ex) {
    err.value = "上传失败: " + ex.message
  }
  busy.value = false
  window.dispatchEvent(new CustomEvent("kb-updated"))
}

async function doSearch() {
  if (!q.value.trim()) return
  hits.value = null
  hits.value = await api.search(q.value.trim())
}
function clearSearch() { hits.value = null; q.value = "" }

async function del(d) {
  if (!confirm(`删除《${d.title || d.filename}》及其全部知识条目？`)) return
  await api.delDoc(d.id)
  load()
}

function fmtTime(t) {
  const d = new Date((t || 0) * 1000)
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
}
</script>

<style scoped>
.lib { padding: 22px 30px; max-width: 980px; margin: 0 auto; }
.dbg-btn { background: none; border: none; cursor: pointer; opacity: .55;
           font-size: 13px; margin-left: 8px; }
.dbg { background: var(--bg); border-radius: 8px; padding: 7px 10px;
       margin-top: 6px; font-size: 12.5px; color: var(--muted); font-family: monospace; }

.webbtn {
  background: var(--panel2); color: var(--text);
  border: 1px solid var(--border); border-radius: 12px;
  padding: 13px 18px; cursor: pointer; font-size: 14px;
}
.webbtn:hover { border-color: var(--accent); }

.mask { position: fixed; inset: 0; background: rgba(0,0,0,.55);
        z-index: 30; display: flex; align-items: center; justify-content: center; }
.modal { width: 86%; max-width: 560px; display: flex; flex-direction: column; gap: 12px; }
.modal textarea {
  background: var(--bg); color: var(--text);
  border: 1px solid var(--border); border-radius: 10px;
  padding: 12px; font-size: 14px; outline: none; resize: vertical;
}
.modal textarea:focus { border-color: var(--accent); }
.modal-btns { display: flex; gap: 12px; }
.mbtn { flex: 1; padding: 11px; border-radius: 10px; border: none;
        font-size: 15px; cursor: pointer; }
.mbtn.cancel { background: #3a3f4a; color: var(--text); }
.mbtn.ok { background: var(--accent); color: #fff; }
.mbtn.ok:disabled { opacity: .5; }

.toolbar { display: flex; gap: 14px; margin-bottom: 20px; }
.upbtn {
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  color: #fff;
  border-radius: 12px;
  padding: 13px 20px;
  cursor: pointer;
  white-space: nowrap;
  font-size: 14px;
}
.upbtn.busy { opacity: 0.6; pointer-events: none; }
.search {
  flex: 1;
  background: var(--panel2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 13px 16px;
  color: var(--text);
  outline: none;
}
.search:focus { border-color: var(--accent); }

.card {
  background: var(--panel2);
  border-radius: 14px;
  padding: 18px 20px;
  margin-bottom: 14px;
}

.doc { display: flex; align-items: center; gap: 14px; }
.doc-main { flex: 1; }
.doc-title { font-weight: 700; font-size: 16px; }
.cat {
  font-size: 12px;
  background: #24304f;
  color: #9db7ff;
  border-radius: 6px;
  padding: 2px 8px;
  margin-left: 8px;
  vertical-align: 2px;
}
.doc-summary { color: var(--muted); margin-top: 5px; font-size: 13.5px; }
.doc-meta { margin-top: 8px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.tag { color: #7fb0ff; font-size: 12.5px; }
.meta { color: var(--muted); font-size: 12.5px; }
.del { background: none; border: none; cursor: pointer; font-size: 17px; opacity: 0.5; }
.del:hover { opacity: 1; }

.hit-head { font-weight: 600; }
.score { color: var(--ok); font-size: 12.5px; margin-left: 8px; }
.hit p { color: var(--muted); font-size: 13.5px; line-height: 1.6; margin: 8px 0 0; }
.none { text-align: center; color: var(--muted); padding: 40px; }
.err {
  background: #3a2226;
  border: 1px solid #5c3036;
  color: #ff9b9b;
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 16px;
}
.linkbtn {
  background: none; border: none; color: var(--accent);
  cursor: pointer; margin-left: 12px; font-size: 13px;
}
.up-results { border: 1px solid var(--border); }
.up-line { padding: 4px 0; font-size: 14px; }
.up-err { color: #ff9b9b; }
</style>
