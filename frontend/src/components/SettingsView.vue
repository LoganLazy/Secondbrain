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

    <div class="group card">
      <h4>🌐 网络模式</h4>
      <label><input type="radio" value="auto" v-model="cfg.NET_MODE" /> 自动（默认，远程失败自动降级）</label>
      <label><input type="radio" value="online" v-model="cfg.NET_MODE" /> 强制在线</label>
      <label><input type="radio" value="offline" v-model="cfg.NET_MODE" />
        强制离线（AI问答/摘要/网页抓取不可用；上传仍可入库但无AI标题，搜索退化为字面匹配）</label>
    </div>

    <div class="group card">
      <h4>🧠 复习参数</h4>
      <label>间隔档位（天，逗号分隔，答对升一档/答错回零）</label>
      <input v-model="cfg.FC_INTERVALS" placeholder="0,1,2,4,7,15,30" />
      <label>掌握阈值（连续答对达到该档位记为已掌握）</label>
      <input v-model="cfg.FC_MASTER_BOX" type="number" min="1" max="9" />
    </div>

    <div class="group card">
      <h4>📊 知识库规模</h4>
      <p class="cap-line">📄 文档 <b>{{ cap.docs }}</b> 篇 · 🧩 知识块 <b>{{ cap.chunks }}</b> 条 · 💾 占用 <b>{{ cap.db_size_mb }}MB</b></p>
      <p class="cap-line">⚡ 检索性能预估：{{ cap.perf_estimate || '尚无检索记录' }}</p>
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
      <p>项目目录下的 <code>知识库文件夹/</code> 里，<b>每个知识库都有一个同名子文件夹</b>——把文件丢进哪个文件夹，就自动导入哪个库。</p>
      <p class="mono">例：知识库文件夹/工作资料/xxx.pdf → 导入「工作资料」库<br>子文件夹内：已导入/ 归档成功文件，失败/ 归档失败文件</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"

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
.group label { display: flex; align-items: center; gap: 8px; color: var(--text); font-size: 14px; }
.cap-line { margin: 4px 0; font-size: 14px; }
.cap-line b { color: var(--accent); }
.mono { font-family: monospace; }
</style>
