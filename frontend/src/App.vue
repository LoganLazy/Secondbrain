<template>
  <Sidebar :tab="tab" ref="sidebar" @change="tab = $event" />
  <main class="main">
    <ChatView v-if="tab === 'chat'" />
    <LibraryView v-else-if="tab === 'library'" @uploaded="sidebar && sidebar.load()" />
    <MemoryView v-else />
  </main>
</template>

<script setup>
import { ref } from "vue"
import Sidebar from "./components/Sidebar.vue"
import ChatView from "./components/ChatView.vue"
import LibraryView from "./components/LibraryView.vue"
import MemoryView from "./components/MemoryView.vue"

const tab = ref("chat")
const sidebar = ref(null)
</script>

<style scoped>
.main { flex: 1; overflow: hidden; }
</style>
