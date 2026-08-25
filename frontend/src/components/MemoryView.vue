<template>
  <div class="mem">
    <div class="head">
      <h3>{{ L("mem_h") }}</h3>
      <p>{{ L("mem_p") }}</p>
    </div>
    <div class="inputbar">
      <input v-model="draft" :placeholder="L('mem_ph')" @keydown.enter="add" />
      <button @click="add">{{ L("mem_add") }}</button>
    </div>

    <div v-for="m in list" :key="m.id" class="card item">
      <span>{{ m.content }}</span>
      <button class="del" @click="del(m.id)">🗑</button>
    </div>
    <div v-if="!list.length" class="none">{{ L("mem_empty") }}</div>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { t as _t, lang as _lang } from "../i18n"
import { api } from "../api"

const list = ref([])
const draft = ref("")

const L = (k) => _t(k)
const langv = _lang
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
