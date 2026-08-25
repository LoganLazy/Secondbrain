import { createApp } from "vue"
import App from "./App.vue"
import "./style.css"

// 所有 /api 请求自动携带当前知识库ID
const _fetch = window.fetch.bind(window)
window.fetch = (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url
  if (url.startsWith("/api/")) {
    init.headers = {
      ...(init.headers || {}),
      "X-KB-Id": localStorage.getItem("kb") || "default"
    }
  }
  return _fetch(input, init)
}

createApp(App).mount("#app")
