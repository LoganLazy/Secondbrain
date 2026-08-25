<template>
  <div class="settings">
    <h3>⚙️ 设置</h3>
    <p class="tip">修改后点「保存」，密钥留空表示不修改。</p>

    <div class="group card">
      <h4>💬 对话模型</h4>
      <label>接口地址</label>
      <input v-model="cfg.CHAT_BASE_URL" placeholder="https://api.deepseek.com" />
      <label>模型名</label>
      <input v-model="cfg.CHAT_MODEL" placeholder="deepseek-chat" />
      <label>API Key</label>
      <input v-model="cfg.DEEPSEEK_KEY" type="password" :placeholder="keyPlaceholder('DEEPSEEK_KEY')" />
      <button class="test" :disabled="testing==='chat'" @click="test('chat')">
        {{ testing === "chat" ? "测试中…" : "🔌 测试连通" }}
      </button>
    </div>

    <div class="group card">
      <h4>🧲 向量模型（语义搜索质量）</h4>
      <label>接口地址</label>
      <input v-model="cfg.EMBED_BASE_URL" />
      <label>模型名</label>
      <input v-model="cfg.EMBED_MODEL" />
      <label>API Key</label>
      <input v-model="cfg.ZHIPU_KEY" type="password" :placeholder="keyPlaceholder('ZHIPU_KEY')" />
      <div class="hint">免费方案: 硅基流动 https://api.siliconflow.cn/v1 + BAAI/bge-m3；本地: http://127.0.0.1:11434/v1 + ollama的bge-m3</div>
      <button class="test" :disabled="testing==='embed'" @click="test('embed')">
        {{ testing === "embed" ? "测试中…" : "🔌 测试连通" }}
      </button>
    </div>

    <button class="save" :disabled="saving" @click="save">{{ saving ? "保存中…" : "💾 保存设置" }}</button>
    <div :class="['msg', msgOk ? 'ok' : 'bad']" v-if="msg">{{ msg }}</div>

    <div class="card ocr-card">
      <h4>🔍 OCR 扫描件识别（可选）</h4>
      <template v-if="ocrOk">
        <p class="okline">✓ 已安装。上传扫描版PDF或图片会自动走OCR识别。</p>
      </template>
      <template v-else>
        <p class="okline bad">未安装 —— 上传扫描件/图片时会提示无法识别。</p>
        <p>启用命令（后端环境执行）：<code>.venv/bin/pip install -r requirements-ocr.txt</code></p>
      </template>
    </div>

    <div class="card inbox-card">
      <h4>📁 知识库文件夹</h4>
      <p>把 PDF/Word/TXT/MD 丢进项目目录下的 <code>知识库文件夹</code>，会自动导入（每分钟扫描一次）。</p>
      <p class="mono">已导入/ 存放成功文件，失败/ 存放失败文件。</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"

const cfg = ref({
  CHAT_BASE_URL: "", CHAT_MODEL: "", DEEPSEEK_KEY: "",
  EMBED_BASE_URL: "", EMBED_MODEL: "", ZHIPU_KEY: ""
})
const testing = ref("")
const saving = ref(false)
const msg = ref("")
const msgOk = ref(false)

const ocrOk = ref(false)

onMounted(async () => {
  const r = await fetch("/api/config")
  const c = await r.json()
  ocrOk.value = !!c.ocr_available
  for (const k of Object.keys(cfg.value)) {
    if (k.endsWith("KEY")) continue
    cfg.value[k] = c[k] ?? ""
  }
})

function keyPlaceholder(k) {
  // 需要重新拉取preview, 简化处理
  return k === "DEEPSEEK_KEY" ? "已设置则留空" : "已设置则留空"
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
    msg.value = d.code === 0 ? "✓ 已保存并生效" : "保存失败"
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
.mono { font-family: monospace; }
</style>
