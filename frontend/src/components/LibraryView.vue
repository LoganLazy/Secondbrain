<template>
  <div class="lib">
    <div class="toolbar">
      <label class="upbtn" :class="{ busy }">
        {{ busy ? L("uploading") : L("upload_btn") }}
        <input type="file" accept=".pdf,.docx,.txt,.md,.jpg,.png,.webp" multiple hidden @change="onFile" />
      </label>
      <button class="webbtn" @click="linkModal = true">{{ L("web_import") }}</button>
      <input v-model="q" class="search" :placeholder="L('search_ph')"
             maxlength="1000" aria-label="全文搜索"
             @keydown.enter="doSearch" />
      <select v-model="searchMode" aria-label="检索模式" class="mode-select">
        <option value="hybrid">混合检索</option><option value="keyword">本地关键词</option>
      </select>
      <button class="webbtn search-submit" :disabled="!q.trim()" @click="doSearch">{{ searching ? '重新搜索' : '搜索' }}</button>
    </div>

    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="searching" class="search-status" role="status">正在搜索《{{ pendingQuery }}》… <button class="linkbtn" @click="cancelSearch">取消</button></div>
    <div v-if="searchError" class="err search-error" role="alert">{{ searchError }} <button class="linkbtn" @click="doSearch">重试当前搜索</button></div>
    <div v-if="searchWarning" class="search-warning" role="status">{{ searchWarning }}</div>
    <section v-if="jobs.length" class="card import-jobs" aria-label="文档导入任务">
      <h4>文档导入任务</h4>
      <p>上传后在后台解析、向量化并生成摘要。刷新页面可查看进度；服务重启后需手动继续。</p>
      <details v-for="job in jobs" :key="job.id" :open="['running','queued','stopping','interrupted','stopped'].includes(job.state)">
        <summary>{{ jobLabel(job.state) }} · {{ job.done }} / {{ job.total }} 个文件 · 成功 {{ job.items.filter(i => i.status === 'success').length }} · 失败 {{ job.items.filter(i => i.status === 'failed').length }}</summary>
        <progress :value="job.done" :max="job.total || 1"></progress>
        <p v-if="job.error" class="up-err">{{ job.error }}</p>
        <div v-for="(item, i) in job.items" :key="i" class="up-line">
          {{ item.file }} · {{ stageLabel(item) }} <span v-if="item.title">→ {{ item.title }}</span>
          <span v-if="item.msg"> · {{ item.msg }}</span>
        </div>
        <button v-if="['running','queued'].includes(job.state)" class="linkbtn" @click="jobAction(job,'stop')">完成当前文件后停止</button>
        <button v-if="['stopped','interrupted'].includes(job.state) && job.items.some(i => i.status === 'pending')" class="linkbtn" @click="jobAction(job,'resume')">继续未完成文件</button>
        <button v-if="!['running','queued','stopping'].includes(job.state) && job.items.some(i => i.status === 'failed')" class="linkbtn" @click="jobAction(job,'retry')">重试失败文件</button>
      </details>
    </section>

    <div v-if="linkModal" class="mask">
      <div class="card modal">
        <h4 style="margin:0 0 10px">{{ L("link_modal_h") }}</h4>
        <textarea v-model="linksText" rows="5"
          placeholder="每行一个链接，如：&#10;https://某博客.com/文章&#10;https://mp.weixin.qq.com/s/xxx"></textarea>
        <div class="modal-btns">
          <button class="mbtn cancel" @click="linkModal = false">{{ L("cancel") }}</button>
          <button class="mbtn ok" :disabled="importing || !linksText.trim()"
                  @click="doImportLinks">{{ importing ? L("importing") : L("start_import") }}</button>
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

    <div v-if="editing" class="mask" @keydown.esc="!saving && (editing = null)">
      <form class="card modal edit-modal" role="dialog" aria-modal="true" aria-label="编辑资料信息" @submit.prevent="saveEdit">
        <h4>编辑资料信息</h4>
        <p>只修改展示信息，不改原文或重新生成向量。原文件：{{ editing.filename }}</p>
        <label>标题<input v-model="editForm.title" maxlength="160" required :disabled="saving" /></label>
        <label>分类<input v-model="editForm.category" maxlength="80" :disabled="saving" /></label>
        <label>标签（用逗号分隔，最多 20 个）<input v-model="editForm.tags" maxlength="1000" :disabled="saving" /></label>
        <div v-if="editError" class="err" role="alert">{{ editError }}</div>
        <div class="modal-btns"><button type="button" class="mbtn cancel" :disabled="saving" @click="editing = null">取消</button><button class="mbtn ok" :disabled="saving || !editForm.title.trim()">{{ saving ? '保存中…' : '保存' }}</button></div>
      </form>
    </div>

    <div v-if="hits !== null" class="hits">
      <h4>《{{ searchedQuery }}》搜索结果（{{ hits.length }}） · {{ resultMode === 'hybrid' ? '混合检索' : '关键词检索' }}<button class="linkbtn" @click="clearSearch">{{ L("back_list") }}</button></h4>
      <small>相关度只用于检索排序，不代表答案可信度。资料列表筛选不影响此处的全文搜索。</small>
      <div v-for="(h, i) in hits" :key="i" class="hit card" style="cursor:pointer" role="button" tabindex="0"
           @click="$emit('openDoc', h)" @keydown.enter.self="$emit('openDoc', h)">
        <div class="hit-head">
          📄 {{ h.title }} · {{ L("page_n") }}{{ h.page }}
          <span v-if="Number.isFinite(h.score)" class="score">相关度 {{ Math.round(h.score * 100) }}%</span>
          <button class="dbg-btn" @click.stop="h._dbg = !h._dbg">🔬</button>
        </div>
        <div v-if="h._dbg" class="dbg">
          {{ L("dbg_sem") }} {{ h.semantic?.toFixed?.(3) ?? "-" }} ·
          {{ L("dbg_kw") }} {{ h.keyword?.toFixed?.(3) ?? "-" }} ·
          {{ L("dbg_fuse") }}
        </div>
        <p class="hit-snippet"><template v-for="(part, n) in searchSnippet(h.text, searchedQuery)" :key="n"><mark v-if="part.hit">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></p>
      </div>
      <div v-if="!hits.length" class="none">{{ L("none_found") }}</div>
    </div>

    <div v-else class="docs">
      <div class="list-filters">
        <input v-model="nameFilter" aria-label="筛选资料" placeholder="按标题、文件名或标签筛选" />
        <select v-model="categoryFilter" aria-label="筛选分类"><option value="">全部分类</option><option v-for="category in categories" :key="category" :value="category">{{ category }}</option></select>
        <select v-model="tagFilter" aria-label="筛选标签"><option value="">全部标签</option><option v-for="tag in tags" :key="tag" :value="tag">{{ tag }}</option></select>
        <select v-model="sortOrder" aria-label="资料排序"><option value="newest">最新导入</option><option value="oldest">最早导入</option><option value="title">标题排序</option></select>
        <button class="linkbtn" @click="resetFilters">重置筛选</button>
      </div>
      <p class="list-count">资料 {{ filteredDocs.length }} / {{ docs.length }} · 筛选仅作用于资料列表</p>
      <div v-for="d in visibleDocs" :key="d.id" class="card doc" style="cursor:pointer" role="button" tabindex="0" @click="$emit('openDoc', d)" @keydown.enter.self="$emit('openDoc', d)">
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
        <button class="edit" title="编辑资料信息" @click.stop="startEdit(d)">✏️</button>
        <button class="del" title="删除" :disabled="deleting.has(d.id)" @click.stop="del(d)">🗑</button>
      </div>
      <div v-if="!docs.length && !busy" class="none">{{ L("kb_empty") }}</div>
      <div v-else-if="!filteredDocs.length" class="none">没有符合筛选条件的资料。</div>
      <div v-if="filteredDocs.length > pageSize" class="pagination"><button :disabled="listPage <= 1" @click="listPage--">上一页</button><span>{{ listPage }} / {{ pageCount }}</span><button :disabled="listPage >= pageCount" @click="listPage++">下一页</button></div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from "vue"
import { api } from "../api"
import { t as _t, lang as _lang } from "../i18n"
import { libraryViews, searchSnippet } from '../libraryUtils'

const L = (k) => _t(k)
const langv = _lang
defineEmits(["openDoc", "uploaded"])

const kb = localStorage.getItem('kb') || 'default'
const cached = libraryViews.get(kb) || {}
const docs = ref([])
const q = ref(cached.q || '')
const hits = ref(cached.hits ?? null)
const searchMode = ref(cached.searchMode || 'hybrid')
const searchedQuery = ref(cached.searchedQuery || '')
const resultMode = ref(cached.resultMode || 'hybrid')
const searchWarning = ref(cached.searchWarning || '')
const searchError = ref('')
const searching = ref(false)
const pendingQuery = ref('')
const nameFilter = ref(cached.nameFilter || '')
const categoryFilter = ref(cached.categoryFilter || '')
const tagFilter = ref(cached.tagFilter || '')
const sortOrder = ref(cached.sortOrder || 'newest')
const listPage = ref(cached.listPage || 1)
const pageSize = 30
const editing = ref(null)
const editForm = ref({title:'', category:'', tags:''})
const editError = ref('')
const saving = ref(false)
const deleting = ref(new Set())
let searchController = null, searchSequence = 0, loadSequence = 0
const categories = computed(() => [...new Set(docs.value.map(d => d.category).filter(Boolean))].sort())
const tags = computed(() => [...new Set(docs.value.flatMap(d => d.tags || []))].sort())
const filteredDocs = computed(() => {
  const needle = nameFilter.value.trim().toLocaleLowerCase()
  const rows = docs.value.filter(doc =>
    (!needle || [doc.title, doc.filename, ...(doc.tags || [])].join(' ').toLocaleLowerCase().includes(needle)) &&
    (!categoryFilter.value || doc.category === categoryFilter.value) &&
    (!tagFilter.value || (doc.tags || []).includes(tagFilter.value)))
  return rows.sort((a,b) => sortOrder.value === 'title'
    ? (a.title || a.filename).localeCompare(b.title || b.filename)
    : sortOrder.value === 'oldest' ? a.created - b.created || a.id - b.id : b.created - a.created || b.id - a.id)
})
const pageCount = computed(() => Math.max(1, Math.ceil(filteredDocs.value.length / pageSize)))
const visibleDocs = computed(() => filteredDocs.value.slice((listPage.value - 1) * pageSize, listPage.value * pageSize))
watch([nameFilter, categoryFilter, tagFilter, sortOrder], () => { listPage.value = 1 })
watch(pageCount, value => { listPage.value = Math.min(listPage.value, value) })
watch(q, value => { if (!value.trim()) clearSearch() })
const busy = ref(false)
const err = ref("")
const results = ref([])
const linkModal = ref(false)
const linksText = ref("")
const importing = ref(false)
const jobs = ref([])
let jobTimer, disposed = false, lastDone = ''

function jobLabel(value) {
  return ({queued:'等待导入', running:'正在导入', stopping:'等待当前文件完成', completed:'导入完成', stopped:'已停止', interrupted:'服务中断，等待继续'})[value] || value
}
function stageLabel(item) {
  if (item.status !== 'running') return ({pending:'等待处理',success:'成功',failed:'失败',duplicate:'已存在，跳过'})[item.status] || item.status
  return ({checking:'检查文件',parsing:'解析文档',embedding:'生成向量',summarizing:'生成摘要',saving:'保存知识'})[item.stage] || '处理中'
}
async function refreshJobs() {
  clearTimeout(jobTimer)
  try {
    const result = await api.importJobs()
    if (disposed) return
    jobs.value = result.jobs || []
    const fingerprint = jobs.value.map(job => `${job.id}:${job.done}`).join(',')
    if (lastDone !== fingerprint) {
      lastDone = fingerprint
      await load()
      window.dispatchEvent(new CustomEvent('kb-updated'))
    }
  } catch (e) { if (!disposed) err.value = '导入任务状态读取失败：' + e.message }
  if (!disposed) jobTimer = setTimeout(refreshJobs, jobs.value.some(j => ['queued','running','stopping'].includes(j.state)) ? 800 : 5000)
}
async function jobAction(job, action) {
  try { await api.importControl(job.id, action); await refreshJobs() }
  catch (e) { err.value = e.message }
}
onUnmounted(() => {
  libraryViews.set(kb, {q:q.value, hits:hits.value, searchMode:searchMode.value,
    searchedQuery:searchedQuery.value, resultMode:resultMode.value, searchWarning:searchWarning.value,
    nameFilter:nameFilter.value, categoryFilter:categoryFilter.value, tagFilter:tagFilter.value,
    sortOrder:sortOrder.value, listPage:listPage.value})
  disposed = true
  cancelSearch()
  clearTimeout(jobTimer)
})

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
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : '网页导入请求失败')
    results.value = d.results || []
    linkModal.value = false
    await load()
    window.dispatchEvent(new CustomEvent("kb-updated"))
  } catch (e) {
    err.value = L("import_fail") + e.message
  }
  importing.value = false
}

onMounted(async () => { try { await load(); await refreshJobs() } catch (e) { err.value = e.message } })
async function load() {
  const sequence = ++loadSequence
  const rows = await api.docs()
  if (disposed || sequence !== loadSequence) return
  docs.value = rows
  if (hits.value !== null) {
    const byId = new Map(rows.map(row => [row.id, row]))
    const previous = hits.value.length
    hits.value = hits.value.filter(hit => {
      const doc = byId.get(hit.doc_id)
      return doc && (!hit.revision || !doc.revision || hit.revision === doc.revision)
    }).map(hit => ({...hit, title:byId.get(hit.doc_id).title || byId.get(hit.doc_id).filename}))
    if (previous !== hits.value.length) searchWarning.value = '部分资料已更新或删除，已移除过期结果；请重新搜索获取最新内容。'
  }
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
    await refreshJobs()
    await load()
  } catch (ex) {
    err.value = "上传失败: " + ex.message
  }
  busy.value = false
  window.dispatchEvent(new CustomEvent("kb-updated"))
}

async function doSearch() {
  const query = q.value.trim()
  if (!query) { clearSearch(); return }
  cancelSearch()
  const sequence = ++searchSequence
  searchController = new AbortController()
  searching.value = true
  pendingQuery.value = query
  searchError.value = ''
  try {
    const result = await api.searchDetails(query, searchMode.value, searchController.signal)
    if (disposed || sequence !== searchSequence) return
    hits.value = result.hits
    searchedQuery.value = result.query
    resultMode.value = result.mode
    searchWarning.value = result.warning || ''
  } catch (e) {
    if (!disposed && sequence === searchSequence && e.name !== 'AbortError') {
      searchError.value = '搜索未完成，请检查连接后重试。已有结果暂时保留。'
    }
  } finally {
    if (sequence === searchSequence) { searching.value = false; searchController = null }
  }
}
function cancelSearch() {
  searchSequence++
  searchController?.abort()
  searchController = null
  searching.value = false
}
function clearSearch() {
  cancelSearch()
  hits.value = null; q.value = ''; searchedQuery.value = ''; searchError.value = ''; searchWarning.value = ''
}
function resetFilters() { nameFilter.value = ''; categoryFilter.value = ''; tagFilter.value = ''; sortOrder.value = 'newest'; listPage.value = 1 }
function startEdit(doc) {
  editing.value = doc
  editForm.value = {title:doc.title || doc.filename, category:doc.category || '', tags:(doc.tags || []).join(', ')}
  editError.value = ''
}
async function saveEdit() {
  if (saving.value || !editing.value) return
  const tags = editForm.value.tags.split(/[,，]/u).map(tag => tag.trim()).filter(Boolean)
  if (tags.length > 20 || tags.some(tag => tag.length > 40)) { editError.value = '最多 20 个标签，每个标签最多 40 个字符。'; return }
  saving.value = true
  editError.value = ''
  try {
    await api.updateDoc(editing.value.id, {title:editForm.value.title, category:editForm.value.category, tags})
    await load()
    editing.value = null
    window.dispatchEvent(new CustomEvent('kb-updated'))
  } catch (e) { editError.value = '保存失败：' + e.message }
  finally { saving.value = false }
}

async function del(d) {
  if (deleting.value.has(d.id)) return
  if (!confirm(langv.value === "zh" ? `删除《${d.title || d.filename}》及其全部知识条目？` : `Delete "${d.title || d.filename}" and all its chunks?`)) return
  deleting.value.add(d.id)
  try {
    await api.delDoc(d.id)
    await load()
    window.dispatchEvent(new CustomEvent('kb-updated'))
  } catch (e) { err.value = '删除失败：' + e.message }
  finally { deleting.value.delete(d.id) }
}

function fmtTime(t) {
  const d = new Date((t || 0) * 1000)
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
}
</script>

<style scoped>
.import-jobs p{font-size:13px;color:var(--muted);line-height:1.6}.import-jobs details{padding:12px 0;border-top:1px solid var(--border)}.import-jobs progress{width:100%;margin-top:12px}.import-jobs .up-line{overflow-wrap:anywhere}
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

.toolbar { display: flex; gap: 10px; flex-wrap:wrap; margin-bottom: 20px; }
.mode-select, .list-filters select, .list-filters input, .edit-modal input { background:var(--panel2); color:var(--text); border:1px solid var(--border); border-radius:8px; padding:10px; min-width:0; }
.mode-select { max-width:150px; }
.list-filters { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
.list-filters input { flex:1; min-width:180px; }
.list-count, .hits small, .edit-modal p { color:var(--muted); font-size:13px; }
.edit-modal label { display:flex; flex-direction:column; gap:7px; font-size:14px; }
.edit-modal h4, .edit-modal p { margin:0; }
.edit-modal { max-height:85vh; overflow:auto; }
.edit { background:none; border:none; color:var(--text); cursor:pointer; font-size:16px; }
.pagination { display:flex; justify-content:center; align-items:center; gap:16px; padding:15px; }
.pagination button { background:var(--panel2); color:var(--text); padding:8px 12px; border:1px solid var(--border); border-radius:8px; cursor:pointer; }
.pagination button:disabled { opacity:.4; cursor:default; }
.search-status, .search-warning { color:var(--muted); background:var(--panel2); padding:12px; border-radius:9px; margin-bottom:12px; }
.hit-snippet mark { color:var(--text); background:#69511d; border-radius:2px; }
.hit { margin-top:12px; }
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
