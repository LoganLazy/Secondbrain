<template>
  <Sidebar :tab="tab" ref="sidebar" @change="tab = $event" />
  <main class="main">
    <template v-if="tab === 'reader' && reading">
      <ReaderView :doc="reading" @close="tab = 'library'; reading = null" />
    </template>
    <ChatView v-else-if="tab === 'chat'" @openDoc="openReader" />
    <LibraryView v-else-if="tab === 'library'" @openDoc="openReader" @uploaded="sidebar && sidebar.load()" />
    <FlashcardsView v-else-if="tab === 'cards'" />
    <SettingsView v-else-if="tab === 'settings'" />
    <MemoryView v-else />
  </main>
</template>

<script setup>
import { ref, onMounted } from "vue"
import Sidebar from "./components/Sidebar.vue"
import ChatView from "./components/ChatView.vue"
import LibraryView from "./components/LibraryView.vue"
import MemoryView from "./components/MemoryView.vue"
import ReaderView from "./components/ReaderView.vue"
import FlashcardsView from "./components/FlashcardsView.vue"
import SettingsView from "./components/SettingsView.vue"

const tab = ref("chat")
const sidebar = ref(null)
const reading = ref(null)

onMounted(() => {
  window.addEventListener("switch-tab", (e) => { tab.value = e.detail })
})

function openReader(s) {
  // s: {doc_id, title, filename}
  reading.value = {
    id: s.doc_id ?? s.id,
    title: s.title,
    filename: s.filename
  }
  tab.value = "reader"
}
</script>

<style scoped>
.main { flex: 1; overflow: hidden; }
</style>
