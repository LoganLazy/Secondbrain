<template>
  <div class="mem">
    <div class="head">
      <h3>🧷 长期记忆</h3>
      <p>告诉 AI 需要长期记住的事（设备、偏好、背景…），问答时会自动参考。</p>
    </div>
    <div class="inputbar">
      <input v-model="draft" placeholder="比如：我有一台16核16G的服务器，跑Docker和NAS" @keydown.enter="add" />
      <button @click="add">记住它</button>
    </div>

    <div v-for="m in list" :key="m.id" class="card item">
      <span>{{ m.content }}</span>
      <button class="del" @click="del(m.id)">🗑</button>
    </div>
    <div v-if="!list.length" class="none">还没有记忆，添加第一条吧</div>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { api } from "../api"

const list = ref([])
const draft = ref("")

onMounted(load)
async function load() { list.value = await api.memoryList() }
async function add() {
  const c = draft.value.trim()
  if (!c) return
  await api.addMemory(c)
  draft.value = ""
  load()
}
async function del(id) {
  await api.delMemory(id)
  load()
}
</script>

<style scoped>
.mem { padding: 22px 30px; max-width: 760px; margin: 0 auto; }
.head p { color: var(--muted); font-size: 13.5px; }

.inputbar { display: flex; gap: 12px; margin-bottom: 20px; }
.inputbar input {
  flex: 1;
  background: var(--panel2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 13px 16px;
  color: var(--text);
  outline: none;
}
.inputbar input:focus { border-color: var(--accent); }
.inputbar button {
  background: var(--accent);
  border: none;
  color: #fff;
  border-radius: 12px;
  padding: 0 22px;
  cursor: pointer;
}

.item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
}
.card {
  background: var(--panel2);
  border-radius: 12px;
  padding: 14px 18px;
  margin-bottom: 12px;
  line-height: 1.6;
}
.del { background: none; border: none; cursor: pointer; opacity: 0.5; font-size: 16px; }
.del:hover { opacity: 1; }
.none { text-align: center; color: var(--muted); padding: 40px; }
</style>
