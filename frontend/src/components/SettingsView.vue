<template>
  <div class="settings">
    <h3>{{ L("set_h") }}</h3>
    <p class="tip">{{ L("set_tip") }}</p>
    <p v-if="loading" role="status">正在加载配置…</p>
    <div v-if="loadError" class="msg bad" role="alert">{{ loadError }} <button class="test" @click="loadSettings">重新加载</button></div>
    <div v-for="warning in warnings" :key="warning" class="vector-warning">{{ warning }}</div>
    <p class="health-status" role="status">本机服务：{{ healthStatus === 'ok' ? '运行正常' : healthStatus === 'checking' ? '检查中…' : '暂时无法连接，请检查服务' }}</p>
    <fieldset :disabled="loading || saving || rebuilding || restoring || testing !== ''">

    <div class="group card">
      <h4>{{ L("g_chat") }}</h4>
      <label>接口地址</label>
      <input v-model="cfg.CHAT_BASE_URL" placeholder="https://api.deepseek.com" />
      <label>模型名</label>
      <input v-model="cfg.CHAT_MODEL" placeholder="deepseek-chat" />
      <label>API Key</label>
      <small>{{ keySet.DEEPSEEK_KEY ? '已保存密钥，留空保持不变' : '尚未保存密钥' }}</small>
      <input v-model="cfg.DEEPSEEK_KEY" type="password" :placeholder="keyPlaceholder()" />
      <button class="test" :disabled="testing==='chat'" @click="test('chat')">
        {{ testing === "chat" ? L("testing") : L("test_conn") }}
      </button>
    </div>

    <div class="group card">
      <h4>{{ L("g_embed") }}</h4>
      <label>接口地址</label>
      <input v-model="cfg.EMBED_BASE_URL" />
      <label>模型名</label>
      <input v-model="cfg.EMBED_MODEL" />
      <label>API Key</label>
      <small>{{ keySet.ZHIPU_KEY ? '已保存密钥，留空保持不变' : '尚未保存密钥' }}</small>
      <input v-model="cfg.ZHIPU_KEY" type="password" :placeholder="keyPlaceholder()" />
      <div class="hint">支持兼容接口及本机模型服务，例如 http://127.0.0.1:11434/v1。密钥只用于你配置的服务；测试可能产生供应商费用，且不会保存配置。</div>
      <button class="test" :disabled="testing==='embed'" @click="test('embed')">
        {{ testing === "embed" ? L("testing") : L("test_conn") }}
      </button>
    </div>

    <div class="group card">
      <h4>{{ L("g_net") }}</h4>
      <label><input type="radio" value="auto" v-model="cfg.NET_MODE" /> {{ L("net_auto") }}</label>
      <label><input type="radio" value="online" v-model="cfg.NET_MODE" /> {{ L("net_online") }}</label>
      <label><input type="radio" value="offline" v-model="cfg.NET_MODE" />
        {{ L("net_offline") }}</label>
    </div>

    <div class="group card">
      <h4>{{ L("g_review") }}</h4>
      <label>{{ L("rv_intervals_l") }}</label>
      <input v-model="cfg.FC_INTERVALS" placeholder="0,1,2,4,7,15,30" />
      <label>{{ L("rv_master_l") }}</label>
      <input v-model="cfg.FC_MASTER_BOX" type="number" min="1" max="9" />
    </div>

    <div class="group card">
      <h4>{{ L("g_cap") }}</h4>
      <p class="cap-line">📄 <b>{{ cap.docs }}</b> · 🧩 <b>{{ cap.chunks }}</b> · 💾 <b>{{ cap.db_size_mb }}MB</b></p>
      <p class="cap-line">{{ L("cap_perf") }}{{ cap.perf_estimate || '尚无检索记录' }}</p>
        <p v-if="cap.vector && cap.vector.warning" class="vector-warning">⚠ {{ cap.vector.warning }}</p>
        <button class="test" :disabled="rebuilding || restoreState.pending || !!loadError" @click="rebuildIndex">
          {{ rebuilding ? "正在重建，请勿关闭…" : "重建向量索引" }}
        </button>
    </div>

    <button class="save" :disabled="saving || !!loadError || restoreState.pending" @click="save">{{ saving ? L("saving") : L("save") }}</button>
    <div :class="['msg', msgOk ? 'ok' : 'bad']" role="status" v-if="msg">{{ msg }}</div>

    <div class="card ocr-card">
      <h4>{{ L("ocr_h") }}</h4>
      <template v-if="ocrOk">
        <p class="okline">{{ L("ocr_on") }}</p>
      </template>
      <template v-else>
        <p class="okline bad">{{ L("ocr_off") }}</p>
        <p>{{ L("ocr_cmd_hint") }}<code>.venv/bin/pip install -r requirements-ocr.txt</code></p>
      </template>
    </div>

    <div class="card inbox-card">
      <h4>{{ L("inbox_h") }}</h4>
      <p>{{ L("inbox_p1") }}</p>
      <p class="mono">{{ L("inbox_p2") }}</p>
    </div>

    <div class="card inbox-card">
      <h4>🛟 数据备份</h4>
      <p>导出数据库、原始文档和应用配置。向量缓存可随时重建，因此不放进备份。</p>
      <p class="vector-warning">备份可能包含已保存的 API Key，请像保管密码一样妥善保管。</p>
      <button class="test" :disabled="backingUp" @click="downloadBackup">
        {{ backingUp ? "正在生成备份…" : "下载完整备份" }}
      </button>
    </div>
    <div class="card inbox-card" id="restore-panel">
      <h4>恢复备份</h4>
      <p>选择 Nebula Memory ZIP 备份，先检查资料数量和完整性。确认后在下次启动时恢复，当前数据目录会完整保留。</p>
      <input id="restore-file" type="file" accept=".zip" :disabled="restoring || restoreState.pending" @change="previewRestore" />
      <template v-if="restorePreview">
        <p id="restore-preview">文档 {{ restorePreview.docs }} · 对话消息 {{ restorePreview.chats }} · 长期记忆 {{ restorePreview.memories }}</p>
        <p v-if="restorePreview.legacy" class="vector-warning">旧版备份没有逐文件校验值，已检查 ZIP 与数据库结构。</p>
        <label><input id="restore-settings" type="checkbox" v-model="restoreSettings" :disabled="!restorePreview.has_settings" />同时恢复备份内配置和密钥（默认保留本机配置）</label>
        <button id="confirm-restore" class="test" :disabled="restoring || restoreState.pending" @click="confirmRestore">确认恢复，下次启动生效</button>
      </template>
      <p v-if="restoreState.pending" class="vector-warning">恢复已准备就绪，请关闭并重新启动知识库服务；随后点击「重建向量索引」。</p>
      <button v-if="restoreState.pending" class="test" @click="cancelRestore">取消等待恢复</button>
      <p v-if="restoreState.report">上次恢复时间：{{ new Date(restoreState.report.restored_at * 1000).toLocaleString() }}。原数据保留在 {{ restoreState.report.previous_data }}。{{ restoreState.report.needs_rebuild ? '恢复后请重建索引。' : '向量索引已重建。' }}</p>
      <p id="restore-message" role="status">{{ restoreMsg }}</p>
    </div>
    </fieldset>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { t as _t, lang as _lang } from "../i18n"

import { api } from "../api"

const cfg = ref({
  CHAT_BASE_URL: "", CHAT_MODEL: "", DEEPSEEK_KEY: "",
  EMBED_BASE_URL: "", EMBED_MODEL: "", ZHIPU_KEY: "",
  NET_MODE: "auto", FC_INTERVALS: "0,1,2,4,7,15,30", FC_MASTER_BOX: 4
})
const testing = ref("")
const loading = ref(true)
const loadError = ref('')
const warnings = ref([])
const keySet = ref({})
const healthStatus = ref('checking')
const saving = ref(false)
const rebuilding = ref(false)
const backingUp = ref(false)
const restoring = ref(false)
const restorePreview = ref(null)
const restoreSettings = ref(false)
const restoreState = ref({pending:false})
const restoreMsg = ref('')
const msg = ref("")
const msgOk = ref(false)

const L = (k) => _t(k)
const langv = _lang
const ocrOk = ref(false)
const cap = ref({ docs: 0, chunks: 0, db_size_mb: 0, perf_estimate: "" })

async function loadSettings() {
  loading.value = true
  loadError.value = ''
  try {
    const response = await fetch('/api/config')
    if (!response.ok) throw new Error('配置加载失败')
    const c = await response.json()
    ocrOk.value = !!c.ocr_available
    warnings.value = c.warnings || []
    for (const key of Object.keys(cfg.value)) {
      if (key.endsWith('KEY')) { keySet.value[key] = !!c[key]?.set; continue }
      if (c[key] !== undefined) cfg.value[key] = c[key]
    }
  } catch (e) { loadError.value = '配置读取失败，已禁用保存，避免覆盖原配置。请重新加载。' }
  finally { loading.value = false }
}
onMounted(async () => {
  await loadSettings()
  try {
    const health = await api.health()
    healthStatus.value = health.status
  } catch { healthStatus.value = 'unavailable' }
  try { restoreState.value = await api.restoreStatus() } catch (e) { restoreMsg.value = e.message }
  try { cap.value = await api.stats() } catch (e) {}
})

async function previewRestore(event) {
  const file = event.target.files[0]; event.target.value = ''
  if (!file) return
  restoring.value = true; restorePreview.value = null; restoreMsg.value = '正在检查备份…'
  restoreSettings.value = false
  try {
    restorePreview.value = await api.previewBackup(file)
    restoreMsg.value = '检查通过。确认前不会替换当前资料。'
  } catch (e) { restoreMsg.value = e.message }
  finally { restoring.value = false }
}

async function confirmRestore() {
  if (!restorePreview.value || !confirm('下次启动将使用备份替换全部知识库、会话与记忆。当前数据会保留在独立目录，恢复后需要重建向量索引。确认准备恢复？')) return
  restoring.value = true
  try {
    const result = await api.restoreBackup({preview_id:restorePreview.value.preview_id, restore_settings:restoreSettings.value, confirm:true})
    restoreMsg.value = result.message
    restoreState.value = await api.restoreStatus()
  } catch (e) { restoreMsg.value = e.message }
  finally { restoring.value = false }
}

async function cancelRestore() {
  try { await api.cancelRestore(); restoreState.value = await api.restoreStatus(); restoreMsg.value = '已取消等待恢复，当前资料未替换。' }
  catch (e) { restoreMsg.value = e.message }
}

function keyPlaceholder() {
  return _lang.value === "zh" ? "已设置则留空" : "Leave blank to keep"
}

async function test(type) {
  if (loading.value || loadError.value || testing.value) return
  testing.value = type
  msg.value = ""
  try {
    const r = await fetch("/api/config/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patch: { ...cfg.value, type } })
    })
    const d = await r.json()
    msg.value = d.msg || (typeof d.detail === 'string' ? d.detail : (d.code === 0 ? '连通 ✓' : '测试失败，请检查配置'))
    msgOk.value = r.ok && d.code === 0
  } catch (e) {
    msg.value = "出错: " + e.message
    msgOk.value = false
  }
  testing.value = ""
}

async function save() {
  if (loading.value || loadError.value || saving.value) return
  saving.value = true
  try {
    const r = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patch: cfg.value })
    })
    const d = await r.json()
    msg.value = r.ok && d.code === 0 ? L('saved') : (typeof d.detail === 'string' ? d.detail : '保存失败，请检查配置')
    msgOk.value = r.ok && d.code === 0
    if (msgOk.value) {
      for (const key of ['DEEPSEEK_KEY','ZHIPU_KEY']) {
        if (cfg.value[key].trim()) keySet.value[key] = true
        cfg.value[key] = ''
      }
    }
  } catch (e) {
    msg.value = "保存出错: " + e.message
    msgOk.value = false
  }
  saving.value = false
}

async function rebuildIndex() {
  if (!confirm("将使用当前向量模型重新处理全部文档。耗时取决于资料数量，确认继续吗？")) return
  rebuilding.value = true
  msg.value = "正在重建向量索引，请勿关闭应用…"
  msgOk.value = true
  try {
    const result = await api.rebuildIndex()
    msg.value = `重建完成：${result.docs} 个文档，${result.chunks} 个片段` +
      (result.skipped?.length ? `；跳过 ${result.skipped.length} 个缺少原文件的文档` : "")
    cap.value = await api.stats()
    restoreState.value = await api.restoreStatus()
  } catch (e) {
    msg.value = "重建失败：" + e.message
    msgOk.value = false
  }
  rebuilding.value = false
}

async function downloadBackup() {
  if (!confirm("备份可能包含 API Key，下载后请妥善保管。继续吗？")) return
  backingUp.value = true
  try {
    const response = await fetch("/api/backup")
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    const disposition = response.headers.get("content-disposition") || ""
    const encoded = disposition.match(/filename\*=utf-8''([^;]+)/i)?.[1]
    const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1]
    const filename = encoded ? decodeURIComponent(encoded) : (plain || "Nebula-Memory-backup.zip")
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
    const missing = Number(response.headers.get('X-Backup-Missing-Originals') || 0)
    msg.value = missing ? `备份已下载，但有 ${missing} 份原文缺失，无法完整恢复。请先找回原文后重新备份。` : "备份已下载"
    msgOk.value = !missing
  } catch (e) {
    msg.value = "备份失败：" + e.message
    msgOk.value = false
  }
  backingUp.value = false
}
</script>

<style scoped>
.okline.bad { color: #ff9b9b; }
.ocr-card code { background: var(--bg); padding: 2px 6px; border-radius: 5px; }
.settings { padding: 24px 34px; max-width: 720px; margin: 0 auto; }
.settings fieldset { border:0; padding:0; margin:0; min-width:0; }
.health-status, .settings small { color:var(--muted); font-size:13px; }
.tip { color: var(--muted); font-size: 13px; }

.group { display: flex; flex-direction: column; gap: 9px; margin-bottom: 18px; }
.group h4 { margin: 0 0 4px; }
.group label { color: var(--muted); font-size: 12.5px; }
.group input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 11px 13px;
  color: var(--text);
  outline: none;
  font-size: 14px;
}
.group input:focus { border-color: var(--accent); }
.test { align-self: flex-start; background: var(--panel); color: var(--text);
        border: 1px solid var(--border); border-radius: 8px; padding: 8px 14px; cursor: pointer; }
.test:hover:not(:disabled) { border-color: var(--accent); }

.save {
  width: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  color: #fff; border: none; border-radius: 12px;
  padding: 14px; font-size: 15px; font-weight: 600; cursor: pointer;
}
.save:disabled { opacity: .6; }
.msg { margin-top: 12px; font-size: 14px; }
.msg.ok { color: var(--ok); }
.msg.bad { color: #ff9b9b; }

.inbox-card p { font-size: 13.5px; color: var(--muted); line-height: 1.7; }
.group label { display: flex; align-items: center; gap: 8px; color: var(--text); font-size: 14px; }
.cap-line { margin: 4px 0; font-size: 14px; }
.cap-line b { color: var(--accent); }
.vector-warning { color: #f2b84b; line-height: 1.6; }
.mono { font-family: monospace; }
</style>
