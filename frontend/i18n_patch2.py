# -*- coding: utf-8 -*-
"""i18n 第二批: FlashcardsView / MemoryView / SettingsView"""
import sys

def load(p): return open(p, encoding="utf-8").read()
def save(p, s): open(p, "w", encoding="utf-8").write(s)

misses = []

def ensure(s):
    if 'from "../i18n"' in s:
        return s
    s = s.replace('import { ref, onMounted } from "vue"',
                  'import { ref, onMounted } from "vue"\nimport { t as _t, lang as _lang } from "../i18n"', 1)
    if "const L =" not in s:
        s = s.replace("onMounted(", "const L = (k) => _t(k)\nconst langv = _lang\nonMounted(", 1)
    return s

# ================= FlashcardsView =================
p = "FlashcardsView.vue"
s = ensure(load(p))
reps = [
 ('<b>{{ st.total }}</b><span>总卡片</span>', '<b>{{ st.total }}</b><span>{{ L("fc_total") }}</span>'),
 ('<b>{{ st.due }}</b><span>今日待复习</span>', '<b>{{ st.due }}</b><span>{{ L("fc_due") }}</span>'),
 ('<b>{{ st.mastered }}</b><span>已掌握</span>', '<b>{{ st.mastered }}</b><span>{{ L("fc_mastered") }}</span>'),
 ('<b>{{ st.accuracy === null ? "—" : st.accuracy + "%" }}</b><span>{{ L("fc_acc") if false else "正确率" }}</span>',
  '<b>{{ st.accuracy === null ? "—" : st.accuracy + "%" }}</b><span>{{ L("fc_acc") }}</span>'),
 ('<b>{{ st.accuracy === null ? "—" : st.accuracy + "%" }}</b><span>正确率</span>',
  '<b>{{ st.accuracy === null ? "—" : st.accuracy + "%" }}</b><span>{{ L("fc_acc") }}</span>'),
 ('<h4>🤖 AI 自动出题</h4>', '<h4>{{ L("fc_gen_h") }}</h4>'),
 ('{{ generating ? "出题中…" : "生成闪卡" }}', '{{ generating ? L("fc_generating") : L("fc_gen") }}'),
 ('🔔 开始今日复习（{{ queue.length }} 张）', '🔔 {{ L("fc_start") }} ({{ queue.length }})'),
 ('<button class="quit" @click="stopReview">退出复习</button>', '<button class="quit" @click="stopReview">{{ L("fc_quit") }}</button>'),
 ('第 {{ done + 1 }} / {{ queue.length }} 张', '{{ done + 1 }} / {{ queue.length }}'),
 ('<div class="tag">问题</div>', '<div class="tag">{{ L("fc_q_tag") }}</div>'),
 ('<div class="tag">答案</div>', '<div class="tag">{{ L("fc_a_tag") }}</div>'),
 ('<div class="hint">点击卡片查看答案</div>', '<div class="hint">{{ L("fc_flip_hint") }}</div>'),
 ('>😵 不会</button>', '>{{ L("g_wrong") }}</button>'),
 ('>🤔 模糊</button>', '>{{ L("g_fuzzy") }}</button>'),
 ('>😀 会了</button>', '>{{ L("g_ok") }}</button>'),
 ('<div v-if="!all.length" class="none">还没有卡片，先用上面的按钮从文档生成吧</div>',
  '<div v-if="!all.length" class="none">{{ L("fc_none") }}</div>'),
 ('if (!confirm("删除这张卡片？")) return',
  'if (!confirm(langv === "zh" ? "删除这张卡片？" : "Delete this card?")) return'),
 ('alert("本轮复习完成！")', 'alert(L("fc_done_alert"))'),
]
for a, b in reps:
    if a in s: s = s.replace(a, b)
    else: misses.append((p, a[:45]))
save(p, s)

# ================= MemoryView =================
p = "MemoryView.vue"
s = ensure(load(p))
reps = [
 ('<h3>🧷 长期记忆</h3>', '<h3>{{ L("mem_h") }}</h3>'),
 ('<p>告诉 AI 需要长期记住的事（设备、偏好、背景…），问答时会自动参考。</p>',
  '<p>{{ L("mem_p") }}</p>'),
 ('placeholder="比如：我有一台16核16G的服务器，跑Docker和NAS"', ':placeholder="L(\'mem_ph\')"'),
 ('<button @click="add">记住它</button>', '<button @click="add">{{ L("mem_add") }}</button>'),
 ('<div v-if="!list.length" class="none">还没有记忆，添加第一条吧</div>',
  '<div v-if="!list.length" class="none">{{ L("mem_empty") }}</div>'),
]
for a, b in reps:
    if a in s: s = s.replace(a, b)
    else: misses.append((p, a[:45]))
save(p, s)

# ================= SettingsView =================
p = "SettingsView.vue"
s = load(p)
if 'from "../i18n"' not in s:
    s = s.replace('import { ref, onMounted } from "vue"',
                  'import { ref, onMounted } from "vue"\nimport { t as _t } from "../i18n"', 1)
    if "const L =" not in s:
        s = s.replace("const ocrOk", "const L = (k) => _t(k)\nconst ocrOk", 1)
s = s.replace('langv === _lang', '')
reps = [
 ('<h3>⚙️ 设置</h3>', '<h3>{{ L("set_h") }}</h3>'),
 ('<p class="tip">修改后点「保存」，密钥留空表示不修改。</p>', '<p class="tip">{{ L("set_tip") }}</p>'),
 ('<h4>💬 对话模型</h4>', '<h4>{{ L("g_chat") }}</h4>'),
 ('<h4>🧲 向量模型（语义搜索质量）</h4>', '<h4>{{ L("g_embed") }}</h4>'),
 ('<h4>🌐 网络模式</h4>', '<h4>{{ L("g_net") }}</h4>'),
 ('自动（默认，远程失败自动降级）', '{{ L("net_auto") }}'),
 ('强制在线', '{{ L("net_online") }}'),
 ('强制离线（AI问答/摘要/网页抓取不可用；上传仍可入库但无AI标题，搜索退化为字面匹配）',
  '{{ L("net_offline") }}'),
 ('<h4>🧠 复习参数</h4>', '<h4>{{ L("g_review") }}</h4>'),
 ('间隔档位（天，逗号分隔，答对升一档/答错回零）', '{{ L("rv_intervals_l") }}'),
 ('掌握阈值（连续答对达到该档位记为已掌握）', '{{ L("rv_master_l") }}'),
 ('<h4>📊 知识库规模</h4>', '<h4>{{ L("g_cap") }}</h4>'),
 ('⚡ 检索性能预估：', '{{ L("cap_perf") }}'),
 ('📄 文档 <b>{{ cap.docs }}</b> 篇 · 🧩 知识块 <b>{{ cap.chunks }}</b> 条 · 💾 占用 <b>{{ cap.db_size_mb }}MB</b>',
  '📄 <b>{{ cap.docs }}</b> · 🧩 <b>{{ cap.chunks }}</b> · 💾 <b>{{ cap.db_size_mb }}MB</b>'),
 ('{{ saving ? "保存中…" : "💾 保存设置" }}', '{{ saving ? L("saving") : L("save") }}'),
 ('msg.value = "✓ 已保存并生效"', 'msg.value = L("saved")'),
 ('{{ testing === "chat" ? "测试中…" : "🔌 测试连通" }}', '{{ testing === "chat" ? L("testing") : L("test_conn") }}'),
 ('{{ testing === "embed" ? "测试中…" : "🔌 测试连通" }}', '{{ testing === "embed" ? L("testing") : L("test_conn") }}'),
 ('<h4>🔍 OCR 扫描件识别（可选）</h4>', '<h4>{{ L("ocr_h") }}</h4>'),
 ('✓ 已安装。上传扫描版PDF或图片会自动走OCR识别。', '{{ L("ocr_on") }}'),
 ('未安装 —— 上传扫描件/图片时会提示无法识别。', '{{ L("ocr_off") }}'),
 ('启用命令（后端环境执行）：', '{{ L("ocr_cmd_hint") }}'),
 ('<h4>📁 知识库文件夹</h4>', '<h4>{{ L("inbox_h") }}</h4>'),
 ("每个知识库都有一个同名子文件夹——把文件丢进哪个文件夹，就自动导入哪个库。",
  "{{ L(\"inbox_p1\") }}"),
 ("子文件夹内：已导入/ 归档成功文件，失败/ 归档失败文件。",
  "{{ L(\"inbox_p2\") }}"),
]
for a, b in reps:
    if a in s: s = s.replace(a, b)
    else: misses.append((p, a[:45]))
save(p, s)

print("MISSES:")
for m in misses:
    print(" ", m[0], "|", m[1][:60])
