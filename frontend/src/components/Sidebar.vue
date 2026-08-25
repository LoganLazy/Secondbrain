<template>
  <aside class="sidebar">
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

onMounted(load)
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
