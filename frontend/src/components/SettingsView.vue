<template>
  <div class="settings">
    <h3>{{ L("set_h") }}</h3>
    <p class="tip">{{ L("set_tip") }}</p>

    <div class="group card">
      <h4>{{ L("g_chat") }}</h4>
      <label>接口地址</label>
      <input v-model="cfg.CHAT_BASE_URL" placeholder="https://api.deepseek.com" />
      <label>模型名</label>
      <input v-model="cfg.CHAT_MODEL" placeholder="deepseek-chat" />
      <label>API Key</label>
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
      <input v-model="cfg.ZHIPU_KEY" type="password" :placeholder="keyPlaceholder()" />
      <div class="hint">免费方案: 硅基流动 https://api.siliconflow.cn/v1 + BAAI/bge-m3；本地: http://127.0.0.1:11434/v1 + ollama的bge-m3</div>
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
    </div>

    <button class="save" :disabled="saving" @click="save">{{ saving ? L("saving") : L("save") }}</button>
    <div :class="['msg', msgOk ? 'ok' : 'bad']" v-if="msg">{{ msg }}</div>

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
const saving = ref(false)
const msg = ref("")
const msgOk = ref(false)

const L = (k) => _t(k)
const langv = _lang
const ocrOk = ref(false)
const cap = ref({ docs: 0, chunks: 0, db_size_mb: 0, perf_estimate: "" })

onMounted(async () => {
  const r = await fetch("/api/config")
  const c = await r.json()
  ocrOk.value = !!c.ocr_available
  cfg.value.NET_MODE = c.NET_MODE || "auto"
  cfg.value.FC_INTERVALS = c.FC_INTERVALS || "0,1,2,4,7,15,30"
  cfg.value.FC_MASTER_BOX = c.FC_MASTER_BOX ?? 4
  try { cap.value = await api.stats() } catch (e) {}
  for (const k of Object.keys(cfg.value)) {
    if (k.endsWith("KEY")) continue
    cfg.value[k] = c[k] ?? ""
  }
})

function keyPlaceholder() {
  return _lang.value === "zh" ? "已设置则留空" : "Leave blank to keep"
}

async function test(type) {
  testing.value = type
  msg.value = ""
  try {
    const r = await fetch("/api/config/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patch: { ...cfg.value, type } })
    })
    const d = await r.json()
    msg.value = d.msg || (d.code === 0 ? "连通 ✓" : "失败")
    msgOk.value = d.code === 0
  } catch (e) {
    msg.value = "出错: " + e.message
    msgOk.value = false
  }
  testing.value = ""
}

async function save() {
  saving.value = true
  try {
    const r = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patch: cfg.value })
    })
    const d = await r.json()
    msg.value = d.code === 0 ? L("saved") : (langv === "zh" ? "保存失败" : "Save failed")
    msgOk.value = d.code === 0
  } catch (e) {
    msg.value = "保存出错: " + e.message
    msgOk.value = false
  }
  saving.value = false
}
</script>

<style scoped>
.okline.bad { color: #ff9b9b; }
.ocr-card code { background: var(--bg); padding: 2px 6px; border-radius: 5px; }
.settings { padding: 24px 34px; max-width: 720px; margin: 0 auto; }
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
.mono { font-family: monospace; }
</style>
