<template>
  <aside class="sidebar">
    <div class="kb-switch">
      <select :value="kb" @change="onKbChange($event.target.value)" title="Switch KB">
        <option v-for="k in kbs" :key="k.id" :value="k.id">📚 {{ k.name }}</option>
      </select>
      <button class="kb-add" title="New KB" @click="createKb">＋</button>
      <button v-if="kb !== 'default'" class="kb-del" title="Delete current KB" @click="delCurrent">🗑</button>
    </div>

    <div class="logo">
      <span class="logo-icon">🧠</span>
      <div>
        <div class="logo-name">{{ t("sb_title") }}</div>
        <div class="logo-sub">{{ t("sb_sub") }}</div>
      </div>
    </div>

    <nav class="nav">
      <button :class="{ active: tab === 'chat' }" @click="$emit('change', 'chat')">{{ t("nav_chat") }}</button>
      <button :class="{ active: tab === 'library' }" @click="$emit('change', 'library')">{{ t("nav_library") }}</button>
      <button :class="{ active: tab === 'memory' }" @click="$emit('change', 'memory')">{{ t("nav_memory") }}</button>
      <button :class="{ active: tab === 'cards' }" @click="$emit('change', 'cards')">{{ t("nav_cards") }}</button>
      <button :class="{ active: tab === 'settings' }" @click="$emit('change', 'settings')">{{ t("nav_settings") }}</button>
    </nav>

    <div class="stats">
      <div class="stat"><b>{{ stats.docs }}</b><span>{{ t("stat_docs") }}</span></div>
      <div class="stat"><b>{{ stats.chunks }}</b><span>{{ t("stat_chunks") }}</span></div>
    </div>

    <button class="lang-btn" @click="toggleLang">
      {{ lang === "zh" ? "🌐 中文 / EN" : "🌐 EN / 中文" }}
    </button>

    <div class="foot">{{ t("foot_local") }}</div>
  </aside>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { api } from "../api"
import { t, lang, setLang } from "../i18n"

defineProps({ tab: String })
defineEmits(["change"])
const stats = ref({ docs: 0, chunks: 0 })
const kbs = ref([])
const kb = localStorage.getItem("kb") || "default"

onMounted(() => {
  load()
  loadKbs()
  window.addEventListener("kb-updated", load)
})

async function load() {
  try { stats.value = await api.stats() } catch (e) {}
}
async function loadKbs() {
  try {
    kbs.value = await api.kbs()
    if (!kbs.value.some((k) => k.id === kb)) localStorage.setItem("kb", "default")
  } catch (e) {}
}
function onKbChange(v) {
  localStorage.setItem("kb", v)
  location.reload()
}
async function createKb() {
  const name = prompt(lang.value === "zh" ? "新知识库名称：" : "New KB name:")
  if (!name?.trim()) return
  const r = await api.createKb(name.trim())
  localStorage.setItem("kb", r.id)
  location.reload()
}
async function delCurrent() {
  if (!confirm(lang.value === "zh" ? `删除「${kbs.value.find((k) => k.id === kb)?.name}」及其全部数据？不可恢复！` : `Delete "${kbs.value.find((k) => k.id === kb)?.name}" and ALL its data? This cannot be undone!`)) return
  await api.delKb(kb)
  localStorage.setItem("kb", "default")
  location.reload()
}
function toggleLang() {
  setLang(lang.value === "zh" ? "en" : "zh")
}
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
.kb-switch { display: flex; gap: 6px; margin-bottom: 12px; align-items: center; }
.kb-switch select {
  flex: 1; min-width: 0;
  background: var(--panel2); color: var(--text);
  border: 1px solid var(--border); border-radius: 9px;
  padding: 8px 10px; font-size: 13.5px; outline: none;
}
.kb-add, .kb-del {
  background: var(--panel2); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px;
  width: 32px; height: 34px; cursor: pointer; flex-shrink: 0;
}
.kb-add:hover { border-color: var(--accent); }
.kb-del:hover { border-color: #e5484d; }

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

.lang-btn {
  margin-top: auto;
  background: var(--panel2); color: var(--muted);
  border: 1px solid var(--border); border-radius: 9px;
  padding: 8px; cursor: pointer; font-size: 12.5px;
}
.lang-btn:hover { color: var(--text); border-color: var(--accent); }

.stats { margin-top: 10px; display: flex; gap: 10px; }
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