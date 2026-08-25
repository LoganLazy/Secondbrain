<template>
  <aside class="sidebar">
    <div class="kb-switch">
      <select :value="kb" @change="onKbChange($event.target.value)" title="切换知识库">
        <option v-for="k in kbs" :key="k.id" :value="k.id">📚 {{ k.name }}</option>
      </select>
      <button class="kb-add" title="新建知识库" @click="createKb">＋</button>
      <button v-if="kb !== 'default'" class="kb-del" title="删除当前知识库" @click="delCurrent">🗑</button>
    </div>

    <div class="logo">
      <span class="logo-icon">🧠</span>
      <div>
        <div class="logo-name">Memory AI</div>
        <div class="logo-sub">你的私人第二大脑</div>
      </div>
    </div>

    <nav class="nav">
      <button :class="{ active: tab === 'chat' }" @click="$emit('change', 'chat')">💬 AI 问答</button>
      <button :class="{ active: tab === 'library' }" @click="$emit('change', 'library')">📚 知识库</button>
      <button :class="{ active: tab === 'memory' }" @click="$emit('change', 'memory')">🧷 长期记忆</button>
      <button :class="{ active: tab === 'cards' }" @click="$emit('change', 'cards')">🃏 复习闪卡</button>
    </nav>

    <button :class="{ active: tab === 'settings' }" class="settings-btn" @click="$emit('change', 'settings')">⚙️ 设置</button>

    <div class="stats">
      <div class="stat"><b>{{ stats.docs }}</b><span>文档</span></div>
      <div class="stat"><b>{{ stats.chunks }}</b><span>知识条目</span></div>
    </div>
    <div class="foot">数据全部保存在本机</div>
  </aside>
</template>

<script setup>
import { onMounted, ref } from "vue"
import { api } from "../api"

defineProps({ tab: String })
defineEmits(["change"])
const stats = ref({ docs: 0, chunks: 0 })
const kbs = ref([])
const kb = localStorage.getItem("kb") || "default"

async function loadKbs() {
  try {
    kbs.value = await api.kbs()
    if (!kbs.value.some((k) => k.id === kb)) {
      localStorage.setItem("kb", "default")
    }
  } catch (e) {}
}
function onKbChange(v) {
  localStorage.setItem("kb", v)
  location.reload()
}
async function createKb() {
  const name = prompt("新知识库名称：")
  if (!name?.trim()) return
  const r = await api.createKb(name.trim())
  localStorage.setItem("kb", r.id)
  location.reload()
}
async function delCurrent() {
  if (!confirm(`删除「${kbs.value.find((k) => k.id === kb)?.name}」及其全部文档/卡片/记录？不可恢复！`)) return
  await api.delKb(kb)
  localStorage.setItem("kb", "default")
  location.reload()
}

onMounted(() => {
  load()
  loadKbs()
  window.addEventListener("kb-updated", load)
})
async function load() {
  try { stats.value = await api.stats() } catch (e) {}
}
defineExpose({ load })
</script>

<style scoped>
.sidebar {
  width: 230px;
  background: var(--panel);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 18px 14px;
}
.logo { display: flex; gap: 10px; align-items: center; padding: 4px 6px 18px; }
.logo-icon { font-size: 30px; }
.logo-name { font-weight: 700; font-size: 17px; }
.logo-sub { color: var(--muted); font-size: 12px; }

.nav { display: flex; flex-direction: column; gap: 6px; }
.nav button {
  text-align: left;
  padding: 11px 14px;
  border-radius: 10px;
  border: none;
  background: transparent;
  color: var(--text);
  font-size: 15px;
  cursor: pointer;
}
.nav button:hover { background: var(--panel2); }
.nav button.active { background: linear-gradient(90deg, #2a3550, #242c46); color: #fff; }

.stats {
  margin-top: auto;
  display: flex;
  gap: 10px;
}
.stat {
  flex: 1;
  background: var(--panel2);
  border-radius: 12px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.stat b { font-size: 20px; }
.stat span { color: var(--muted); font-size: 12px; }

.foot { color: var(--muted); font-size: 12px; margin-top: 12px; text-align: center; }
</style>
