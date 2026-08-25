<template>
  <div class="fc">
    <div class="stats-row">
      <div class="st"><b>{{ st.total }}</b><span>总卡片</span></div>
      <div class="st hot"><b>{{ st.due }}</b><span>今日待复习</span></div>
      <div class="st"><b>{{ st.mastered }}</b><span>已掌握</span></div>
      <div class="st"><b>{{ st.accuracy === null ? "—" : st.accuracy + "%" }}</b><span>正确率</span></div>
    </div>

    <!-- 复习模式 -->
    <template v-if="reviewing">
      <div class="progress">
        第 {{ done + 1 }} / {{ queue.length }} 张
        <button class="quit" @click="stopReview">退出复习</button>
      </div>
      <div class="bigcard" :class="{ flipped: showAns }" @click="showAns = true">
        <div class="q-side">
          <div class="tag">问题</div>
          <div class="text">{{ queue[idx]?.q }}</div>
          <div class="hint">点击卡片查看答案</div>
        </div>
        <div v-if="showAns" class="a-side">
          <div class="tag">答案</div>
          <div class="text">{{ queue[idx]?.a }}</div>
        </div>
      </div>
      <div v-if="showAns" class="grade">
        <button class="g wrong" @click="grade('wrong')">😵 不会</button>
        <button class="g fuzzy" @click="grade('fuzzy')">🤔 模糊</button>
        <button class="g ok" @click="grade('correct')">😀 会了</button>
      </div>
    </template>

    <!-- 管理面板 -->
    <template v-else>
      <div class="gen card">
        <h4>🤖 AI 自动出题</h4>
        <div class="gen-row">
          <select v-model="docId">
            <option v-for="d in docs" :key="d.id" :value="d.id">{{ d.title || d.filename }}</option>
          </select>
          <select v-model.number="num">
            <option :value="6">6张</option>
            <option :value="10">10张</option>
            <option :value="15">15张</option>
          </select>
          <button :disabled="generating || !docId" @click="generate">
            {{ generating ? "出题中…" : "生成闪卡" }}
          </button>
        </div>
        <div v-if="genMsg" class="msg">{{ genMsg }}</div>
      </div>

      <button v-if="queue.length" class="btn-review" @click="startReview">
        🔔 开始今日复习（{{ queue.length }} 张）
      </button>

      <div class="list">
        <div v-for="c in all" :key="c.id" class="card item">
          <div class="item-main">
            <b>{{ c.q }}</b>
            <span class="ans">{{ c.a }}</span>
            <span class="meta">
              复习{{ c.reviews }}次 · 掌握度
              <i v-for="n in 5" :key="n" :class="['dot', { on: n <= c.box }]"></i>
              <em v-if="c.last_result === 'wrong'" class="wrong-tag">上次答错</em>
            </span>
          </div>
          <button class="del" @click="del(c.id)">🗑</button>
        </div>
        <div v-if="!all.length" class="none">还没有卡片，先用上面的按钮从文档生成吧</div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { api } from "../api"

const st = ref({ total: 0, due: 0, mastered: 0, accuracy: null })
const docs = ref([])
const docId = ref(null)
const num = ref(10)
const generating = ref(false)
const genMsg = ref("")
const all = ref([])
const queue = ref([])
const reviewing = ref(false)
const idx = ref(0)
const done = ref(0)
const showAns = ref(false)

onMounted(load)
async function load() {
  try {
    st.value = await api.fcStats()
    all.value = await api.fcList()
    queue.value = await api.fcDue()
    if (!docs.value.length) docs.value = await api.docs()
    if (!docId.value && docs.value.length) docId.value = docs.value[0].id
  } catch (e) {}
}

async function generate() {
  generating.value = true
  genMsg.value = ""
  try {
    const r = await fetch("/api/flashcards/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id: docId.value, num: num.value })
    })
    const d = await r.json()
    genMsg.value = d.count !== undefined ? `✓ 生成了 ${d.count} 张卡片` : (d.detail || "失败")
    load()
  } catch (e) {
    genMsg.value = "出错: " + e.message
  }
  generating.value = false
}

function startReview() {
  reviewing.value = true
  idx.value = 0
  done.value = 0
  showAns.value = false
}
function stopReview() {
  reviewing.value = false
  load()
}

async function grade(result) {
  const card = queue.value[idx.value]
  await fetch(`/api/flashcards/${card.id}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ result })
  })
  showAns.value = false
  idx.value++
  done.value++
  if (idx.value >= queue.value.length) {
    alert("本轮复习完成！")
    stopReview()
  }
}

async function del(id) {
  if (!confirm("删除这张卡片？")) return
  await api.delCard(id)
  load()
}
</script>

<style scoped>
.fc { padding: 22px 30px; max-width: 860px; margin: 0 auto; }

.stats-row { display: flex; gap: 14px; margin-bottom: 22px; }
.st {
  flex: 1;
  background: var(--panel2);
  border-radius: 12px;
  padding: 14px;
  display: flex; flex-direction: column; align-items: center;
}
.st b { font-size: 24px; }
.st span { color: var(--muted); font-size: 12px; }
.st.hot b { color: #ffb454; }

.gen h4 { margin: 0 0 12px; }
.gen-row { display: flex; gap: 12px; }
.gen select, .gen button {
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 14px;
  font-size: 14px;
}
.gen button {
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  border: none; cursor: pointer; color: #fff;
}
.gen button:disabled { opacity: .5; cursor: default; }
.msg { margin-top: 10px; color: var(--ok); font-size: 13.5px; }

.btn-review {
  width: 100%;
  background: linear-gradient(90deg, #ff9a3c, #ff6a3c);
  color: #fff; border: none; border-radius: 14px;
  padding: 17px; font-size: 17px; font-weight: 700;
  cursor: pointer; margin-bottom: 22px;
}

.progress {
  display: flex; justify-content: space-between; align-items: center;
  color: var(--muted); margin-bottom: 16px; font-size: 14px;
}
.quit { background: none; border: none; color: var(--accent); cursor: pointer; }

.bigcard {
  min-height: 300px;
  border-radius: 18px;
  padding: 34px;
  cursor: pointer;
  display: flex; flex-direction: column; gap: 20px;
  background: linear-gradient(160deg, #1d2330, #171c26);
  border: 2px solid #333c4d;
}
.bigcard.flipped { border-color: var(--accent); }
.tag { color: var(--muted); font-size: 12.5px; letter-spacing: 2px; }
.text { font-size: 21px; line-height: 1.7; white-space: pre-wrap; }
.hint { margin-top: auto; color: var(--muted); font-size: 13px; text-align: center; }
.a-side { border-top: 1px dashed var(--border); padding-top: 18px; }
.a-side .text { font-size: 18px; color: #b7e3c1; }

.grade { display: flex; gap: 16px; margin-top: 18px; }
.g {
  flex: 1; padding: 15px; font-size: 16px;
  border-radius: 12px; border: none; cursor: pointer; color: #fff;
}
.g.wrong { background: #e5484d; }
.g.fuzzy { background: #b8860b; }
.g.ok { background: #2e9e5b; }

.item { display: flex; align-items: center; gap: 14px; margin-bottom: 12px; }
.card { background: var(--panel2); border-radius: 12px; padding: 15px 18px; }
.item-main { flex: 1; display: flex; flex-direction: column; gap: 5px; }
.ans { color: var(--muted); font-size: 13.5px; }
.meta { display: flex; align-items: center; gap: 4px; font-size: 12px; color: var(--muted); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #333a46; display: inline-block; }
.dot.on { background: var(--ok); }
.wrong-tag { color: #ff8a8a; font-style: normal; margin-left: 8px; }
.del { background: none; border: none; cursor: pointer; opacity: .5; font-size: 16px; }
.none { text-align: center; color: var(--muted); padding: 40px; }
</style>
