<template>
  <div class="fc">
    <p v-if="loading" role="status">正在加载复习资料…</p>
    <div v-if="loadError" class="fc-error" role="alert">{{ loadError }} <button @click="load">重新加载</button></div>
    <div v-if="reviewMessage" class="review-message" role="status">{{ reviewMessage }}</div>
    <div class="stats-row">
      <div class="st"><b>{{ st.total }}</b><span>{{ L("fc_total") }}</span></div>
      <div class="st hot"><b>{{ st.due }}</b><span>{{ L("fc_due") }}</span></div>
      <div class="st"><b>{{ st.mastered }}</b><span>{{ L("fc_mastered") }}</span></div>
      <div class="st"><b>{{ st.accuracy === null ? "—" : st.accuracy + "%" }}</b><span>{{ L("fc_acc") }}</span></div>
    </div>
    <p class="stats-note">统计为当前知识库全部卡片；到期及掌握数量不含已确认来源失效的卡片。</p>
    <p class="source-note" v-if="st.paused">{{ st.paused }} 张卡片的来源已更新或删除，暂停复习；卡片和历史记录仍保留。</p>
    <p class="source-note" v-if="st.unverified">{{ st.unverified }} 张旧卡片没有资料版本记录，无法判断是否过期；仍可复习，请先核对原文。</p>

    <!-- 复习模式 -->
    <template v-if="reviewing">
      <div class="progress">
        第 {{ idx + 1 }} / {{ queue.length }} 张 · 本轮成功提交 {{ done }} 张
        <button class="quit" :disabled="submitting" @click="stopReview">{{ L("fc_quit") }}</button>
      </div>
      <p class="source-note">{{ sourceLabel(current?.source_state) }} <button v-if="current?.source_doc_id" class="source-link" @click="openSource(current)">核对原文</button></p>
      <div v-if="reviewError" class="fc-error" role="alert">{{ reviewError }} <button v-if="conflict" @click="refreshReview">刷新复习队列</button></div>
      <div class="bigcard" :class="{ flipped: showAns }" @click="showAns = true">
        <div class="q-side">
          <div class="tag">{{ L("fc_q_tag") }}</div>
          <div class="text">{{ queue[idx]?.q }}</div>
          <div class="hint">{{ L("fc_flip_hint") }}</div>
        </div>
        <div v-if="showAns" class="a-side">
          <div class="tag">{{ L("fc_a_tag") }}</div>
          <div class="text">{{ queue[idx]?.a }}</div>
        </div>
      </div>
      <div v-if="showAns" class="grade">
        <button class="g wrong" :disabled="submitting || conflict" @click="grade('wrong')">{{ L("g_wrong") }}</button>
        <button class="g fuzzy" :disabled="submitting || conflict" @click="grade('fuzzy')">{{ L("g_fuzzy") }}</button>
        <button class="g ok" :disabled="submitting || conflict" @click="grade('correct')">{{ submitting ? '提交中…' : L("g_ok") }}</button>
      </div>
    </template>

    <!-- 管理面板 -->
    <template v-else>
      <div class="gen card">
        <h4>{{ L("fc_gen_h") }}</h4>
        <div class="gen-row">
          <select v-model="docId" aria-label="出题资料" :disabled="generating || loading">
            <option v-for="d in docs" :key="d.id" :value="d.id">{{ d.title || d.filename }}</option>
          </select>
          <select v-model.number="num" aria-label="闪卡数量" :disabled="generating || loading">
            <option :value="6">6张</option>
            <option :value="10">10张</option>
            <option :value="15">15张</option>
          </select>
          <button :disabled="generating || loading || starting || !!loadError || !docId" @click="generate">
            {{ generating ? L("fc_generating") : L("fc_gen") }}
          </button>
        </div>
        <p class="source-note">生成会调用当前对话模型，可能产生费用；使用文档前 9000 字符以内的节选，题目和答案请核对原文。</p>
        <div v-if="genMsg" :class="['msg', { bad: !genOk }]" role="status">{{ genMsg }}</div>
      </div>
      <label class="review-filter">按资料复习 <select v-model="docFilter" :disabled="loading || starting || generating" aria-label="复习资料"><option value="">全部资料</option><option v-for="doc in docs" :key="doc.id" :value="String(doc.id)">{{ doc.title || doc.filename }}</option></select></label>
      <button class="btn-review" :disabled="loading || starting || generating || !!loadError || !filteredDue.length" @click="startReview">
        🔔 {{ starting ? '正在加载队列…' : L("fc_start") }} ({{ filteredDue.length }})
      </button>

      <div class="list">
        <div v-for="c in filteredCards" :key="c.id" class="card item">
          <div class="item-main">
            <b>{{ c.q }}</b>
            <span class="ans">{{ c.a }}</span>
            <span class="meta">
              {{ langv === "zh" ? `复习${c.reviews}次` : `${c.reviews} reviews` }} · {{ langv === "zh" ? "掌握度" : "Mastery" }}
              {{ c.box }} / {{ st.max_box }}
              <em v-if="c.last_result === 'wrong'" class="wrong-tag">{{ langv === "zh" ? "上次答错" : "Missed last time" }}</em>
            </span>
            <span class="source-note">{{ sourceLabel(c.source_state) }} · {{ c.source_title || c.source_filename || '原资料已不存在' }} <button v-if="c.source_doc_id" class="source-link" @click="openSource(c)">原文</button></span>
            <span class="meta" v-if="!['missing','changed'].includes(c.source_state)">到期时间：{{ c.reviews ? fmtDue(c.next_due) : '新卡片，随时可复习' }}</span>
          </div>
          <button class="del" :disabled="deleting.has(c.id)" @click="del(c.id)">🗑</button>
        </div>
        <div v-if="!filteredCards.length && !loading" class="none">{{ L("fc_none") }}</div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue"
import { t as _t, lang as _lang } from "../i18n"
import { api } from "../api"

const emit = defineEmits(['openDoc'])
const st = ref({total:0, due:0, mastered:0, accuracy:null, max_box:6, paused:0, unverified:0})
const docs = ref([])
const docId = ref(null)
const docFilter = ref('')
const num = ref(10)
const generating = ref(false)
const genMsg = ref("")
const genOk = ref(false)
const all = ref([])
const queue = ref([])
const reviewing = ref(false)
const idx = ref(0)
const done = ref(0)
const showAns = ref(false)
const loading = ref(true)
const starting = ref(false)
const loadError = ref('')
const submitting = ref(false)
const reviewError = ref('')
const reviewMessage = ref('')
const conflict = ref(false)
const deleting = ref(new Set())
let disposed = false, sequence = 0, controller = null
const L = (key) => _t(key)
const langv = _lang
const current = computed(() => queue.value[idx.value])
const filteredCards = computed(() => all.value.filter(card => !docFilter.value || card.doc_id === Number(docFilter.value)))
const filteredDue = computed(() => queue.value.filter(card => !docFilter.value || card.doc_id === Number(docFilter.value)))

onMounted(load)
onUnmounted(() => { disposed = true; sequence++; controller?.abort() })

async function load() {
  const request = ++sequence
  loading.value = true
  try {
    const [stats, cards, due, sources] = await Promise.all([api.fcStats(), api.fcList(), api.fcDue(), api.docs()])
    if (disposed || request !== sequence) return
    st.value = stats; all.value = cards; queue.value = due; docs.value = sources
    if (!sources.some(doc => doc.id === docId.value)) docId.value = sources[0]?.id ?? null
    if (docFilter.value && !sources.some(doc => doc.id === Number(docFilter.value))) docFilter.value = ''
    loadError.value = ''
  } catch (e) {
    if (!disposed && request === sequence) loadError.value = '复习资料加载失败，请重新加载；已有卡片不会清除。'
  } finally {
    if (request === sequence) loading.value = false
  }
}

function sourceLabel(state) {
  return ({current:'已关联生成时的资料版本', unverified:'旧卡片：资料版本未记录',
    changed:'资料已更新，暂停旧卡复习', missing:'资料已删除，暂停复习并保留历史'})[state] || ''
}
function openSource(card) {
  if (submitting.value) return
  emit('openDoc', {doc_id:card.source_doc_id, title:card.source_title, filename:card.source_filename})
}
function fmtDue(value) { return new Date(value * 1000).toLocaleString() }

async function generate() {
  if (generating.value || loading.value || !docId.value) return
  generating.value = true; genMsg.value = ''; genOk.value = false
  controller = new AbortController()
  try {
    const result = await api.generateCards(docId.value, num.value, controller.signal)
    if (disposed) return
    genMsg.value = result.count ? '✓ 新增了 ' + result.count + ' 张卡片' : '没有新增卡片：同版本资料已有相同问题。'
    genOk.value = true
    await load()
  } catch (e) {
    if (!disposed && e.name !== 'AbortError') genMsg.value = '出题未完成：' + e.message
  } finally { generating.value = false; controller = null }
}

async function startReview() {
  if (starting.value || loading.value || generating.value) return
  starting.value = true
  reviewError.value = ''; reviewMessage.value = ''
  try {
    const due = await api.fcDue(docFilter.value)
    if (disposed) return
    queue.value = due
    idx.value = 0; done.value = 0; showAns.value = false; conflict.value = false
    reviewing.value = due.length > 0
    if (!due.length) reviewMessage.value = '当前范围没有到期卡片，请稍后刷新。'
  } catch (e) { reviewMessage.value = '复习队列读取失败，请重试。' }
  finally { starting.value = false }
}
async function refreshReview() {
  if (submitting.value) return
  reviewing.value = false
  await load()
  if (!loadError.value) await startReview()
}
async function stopReview() {
  if (submitting.value) return
  reviewing.value = false
  reviewError.value = ''
  reviewMessage.value = '本轮已成功提交 ' + done.value + ' 张；未提交的卡片仍在到期队列。'
  await load()
}
async function grade(result) {
  if (submitting.value || conflict.value || !showAns.value || !current.value) return
  const card = current.value
  submitting.value = true; reviewError.value = ''
  controller = new AbortController()
  try {
    await api.answerCard(card.id, result, card.reviews, controller.signal)
    if (disposed) return
    // 只有收到服务器成功确认后才推进；网络失败或版本冲突保留当前卡片。
    done.value++; idx.value++; showAns.value = false
    if (idx.value >= queue.value.length) {
      reviewing.value = false
      reviewMessage.value = '本轮完成，成功提交 ' + done.value + ' 张。间隔为 0 天的卡片可能立即再次到期。'
      await load()
    }
  } catch (e) {
    if (!disposed && e.name !== 'AbortError') {
      conflict.value = e.status === 409 || e.status === 404
      reviewError.value = conflict.value ? '卡片或来源已变化，请刷新复习队列；不会重复计次。' : '提交未得到确认，仍保留当前卡片，请重试。'
    }
  } finally { submitting.value = false; controller = null }
}
async function del(id) {
  if (deleting.value.has(id) || !confirm(langv.value === 'zh' ? '删除这张卡片及其复习统计？此操作无法撤销。' : 'Delete this card and its study statistics? This cannot be undone.')) return
  deleting.value.add(id)
  try { await api.delCard(id); await load() }
  catch (e) { loadError.value = '删除失败：' + e.message }
  finally { deleting.value.delete(id) }
}
</script>

<style scoped>
.fc { padding: 22px 30px; max-width: 860px; margin: 0 auto; }
.fc-error { color:#ff9b9b; background:#3a2226; padding:12px; border-radius:8px; margin-bottom:12px; }
.review-message { color:var(--ok); margin-bottom:12px; }
.source-note { color:var(--muted); font-size:13px; line-height:1.7; }
.stats-note { color:var(--muted); font-size:12px; }
.source-link, .fc-error button { border:0; background:none; color:var(--accent); cursor:pointer; }
.review-filter { display:flex; gap:10px; align-items:center; margin:15px 0; }
.review-filter select { background:var(--panel2); color:var(--text); border:1px solid var(--border); border-radius:8px; padding:8px; }
.fc button:disabled { opacity:.45; cursor:default; }
.msg.bad { color:#ff9b9b; }

.stats-row { display: flex; gap: 14px; margin-bottom: 22px; }
.st {
  flex: 1;
  background: var(--panel2);
  border-radius: 12px;
  padding: 14px;
  display: flex; flex-direction: column; align-items: center;
}
.st b { font-size: 24px; }
.st span { color: var(--muted); font-size: 12px; }
.st.hot b { color: #ffb454; }

.gen h4 { margin: 0 0 12px; }
.gen-row { display: flex; gap: 12px; }
.gen select, .gen button {
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 14px;
  font-size: 14px;
}
.gen button {
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  border: none; cursor: pointer; color: #fff;
}
.gen button:disabled { opacity: .5; cursor: default; }
.msg { margin-top: 10px; color: var(--ok); font-size: 13.5px; }

.btn-review {
  width: 100%;
  background: linear-gradient(90deg, #ff9a3c, #ff6a3c);
  color: #fff; border: none; border-radius: 14px;
  padding: 17px; font-size: 17px; font-weight: 700;
  cursor: pointer; margin-bottom: 22px;
}

.progress {
  display: flex; justify-content: space-between; align-items: center;
  color: var(--muted); margin-bottom: 16px; font-size: 14px;
}
.quit { background: none; border: none; color: var(--accent); cursor: pointer; }

.bigcard {
  min-height: 300px;
  border-radius: 18px;
  padding: 34px;
  cursor: pointer;
  display: flex; flex-direction: column; gap: 20px;
  background: linear-gradient(160deg, #1d2330, #171c26);
  border: 2px solid #333c4d;
}
.bigcard.flipped { border-color: var(--accent); }
.tag { color: var(--muted); font-size: 12.5px; letter-spacing: 2px; }
.text { font-size: 21px; line-height: 1.7; white-space: pre-wrap; }
.hint { margin-top: auto; color: var(--muted); font-size: 13px; text-align: center; }
.a-side { border-top: 1px dashed var(--border); padding-top: 18px; }
.a-side .text { font-size: 18px; color: #b7e3c1; }

.grade { display: flex; gap: 16px; margin-top: 18px; }
.g {
  flex: 1; padding: 15px; font-size: 16px;
  border-radius: 12px; border: none; cursor: pointer; color: #fff;
}
.g.wrong { background: #e5484d; }
.g.fuzzy { background: #b8860b; }
.g.ok { background: #2e9e5b; }

.item { display: flex; align-items: center; gap: 14px; margin-bottom: 12px; }
.card { background: var(--panel2); border-radius: 12px; padding: 15px 18px; }
.item-main { flex: 1; display: flex; flex-direction: column; gap: 5px; }
.ans { color: var(--muted); font-size: 13.5px; }
.meta { display: flex; align-items: center; gap: 4px; font-size: 12px; color: var(--muted); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #333a46; display: inline-block; }
.dot.on { background: var(--ok); }
.wrong-tag { color: #ff8a8a; font-style: normal; margin-left: 8px; }
.del { background: none; border: none; cursor: pointer; opacity: .5; font-size: 16px; }
.none { text-align: center; color: var(--muted); padding: 40px; }
</style>
