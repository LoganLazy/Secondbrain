# -*- coding: utf-8 -*-
"""i18n 批量接线: LibraryView / ReaderView / FlashcardsView / MemoryView / SettingsView"""
import io, sys

def load(p): return open(p, encoding="utf-8").read()
def save(p, s): open(p, "w", encoding="utf-8").write(s)

def ensure_i18n(s, vue_import_old, vue_import_new):
    if 'from "../i18n"' in s:
        return s
    s = s.replace(vue_import_old, vue_import_new)
    s = s.replace('from "../api"', 'from "../api"\nimport { t as _t, lang as _lang } from "../i18n"', 1)
    s = s.replace("defineEmits(", "const L = (k) => _t(k)\nconst langv = _lang\ndefineEmits(", 1)
    return s

misses = []

# ================= LibraryView =================
p = "LibraryView.vue"
s = load(p)
if 'from "../i18n"' not in s:
    s = ensure_i18n(s, 'import { ref, onMounted } from "vue"',
                       'import { ref, onMounted } from "vue"')
reps = [
 ('{{ busy ? "处理中…" : "＋ 上传文档/图片 (可多选)" }}', '{{ busy ? L("uploading") : L("upload_btn") }}'),
 ('placeholder="🔍 语义搜索：用大白话描述你要找的东西，Enter 搜索"', ':placeholder="L(\'search_ph\')"'),
 ('>🔗 导入网页</button>', '>{{ L("web_import") }}</button>'),
 ('<h4 style="margin:0 0 10px">🔗 导入网页</h4>', '<h4 style="margin:0 0 10px">{{ L("link_modal_h") }}</h4>'),
 ('{{ importing ? "抓取中…" : "开始导入" }}', '{{ importing ? L("importing") : L("start_import") }}'),
 ('<button class="mbtn cancel" @click="linkModal = false">取消</button>',
  '<button class="mbtn cancel" @click="linkModal = false">{{ L("cancel") }}</button>'),
 ("err.value = \"导入失败: \" + e.message", "err.value = L(\"import_fail\") + e.message"),
 ('<div v-if="!hits.length" class="none">没找到相关内容</div>',
  '<div v-if="!hits.length" class="none">{{ L("none_found") }}</div>'),
 ('<button class="linkbtn" @click="clearSearch">返回列表</button>',
  '<button class="linkbtn" @click="clearSearch">{{ L("back_list") }}</button>'),
 ("第{{ h.page }}页", "{{ L(\"page_n\") }}{{ h.page }}"),
 ("% 匹配", "% {{ L(\"matches\") }}"),
 ('语义分 {{ h.semantic?.toFixed?.(3) ?? h.semantic }} ·',
  '{{ L("dbg_sem") }} {{ h.semantic?.toFixed?.(3) ?? "-" }} ·'),
 ('关键词分 {{ h.keyword?.toFixed?.(3) ?? h.keyword }} ·',
  '{{ L("dbg_kw") }} {{ h.keyword?.toFixed?.(3) ?? "-" }} ·'),
 ('融合 = 语义×0.65 + 关键词×0.35', '{{ L("dbg_fuse") }}'),
 ('知识库还是空的，上传第一份文档吧', '{{ L("kb_empty") }}'),
]
for a, b in reps:
    if a in s: s = s.replace(a, b)
    else: misses.append((p, a[:40]))
save(p, s)

# ================= ReaderView =================
p = "ReaderView.vue"
s = load(p)
if 'from "../i18n"' not in s:
    s = s.replace('import { ref, computed, nextTick, onMounted } from "vue"',
                  'import { ref, computed, nextTick, onMounted } from "vue"\nimport { t as _t, lang as _lang } from "../i18n"', 1)
    if "_t" not in s.split("<script")[1][:400]:
        s = s.replace('defineEmits(["close"])',
                      'const L = (k) => _t(k)\nconst langv = _lang\ndefineEmits(["close"])', 1)
    else:
        s = s.replace("defineEmits([\"close\"])",
                      "const L = (k) => _t(k)\nconst langv = _lang\ndefineEmits([\"close\"])", 1)
reps = [
 ('← 返回</button>', '← {{ langv === "zh" ? "返回" : "Back" }}</button>'),
 ('◀ 上一页</button>', '>{{ L("prev") }}</button>'),
 ('下一页 ▶</button>', '>{{ L("next") }}</button>'),
 ('第 <input class="jump"', '<span class="page-ind-txt">{{ L("page_n") }}</span> <input class="jump"'),
 ('/ {{ pages.length }} 页', '/ {{ pages.length }}'),
 ('>文字</button>', '>{{ L("view_text") }}</button>'),
 ('>原版</button>', '>{{ L("view_original") }}</button>'),
 ('<div class="rendering">渲染中…</div>', '<div class="rendering">{{ L("rendering") }}</div>'),
 ('选中左侧文字提问，或点上面的快捷操作\n        </div>', '{{ L("ai_empty") }}\n        </div>'),
 ('@click="copy(m)">复制</button>', '@click="copy(m)">{{ L("copy") }}</button>'),
 ('placeholder="针对当前页提问…"', ':placeholder="L(\'ask_page_ph\')"'),
 ('askDraft">问</button>', 'askDraft">{{ L("ask") }}</button>'),
 ('loadErr.value = "原文加载失败: " + e.message + "（可能已被删除或丢失，请重新上传）"',
  'loadErr.value = L("load_fail") + e.message + (langv === "zh" ? "（可能已被删除或丢失，请重新上传）" : "(it may have been deleted, please re-upload)")'),
 ('<div v-else class="load-err">加载中…</div>', '<div v-else class="load-err">{{ L("loading") }}</div>'),
 # 快捷操作标签
 ('label: "📝 总结全文"', 'label: L("qa_sum_all")'),
 ('label: "💡 解释本页"', 'label: L("qa_explain_page")'),
 ('label: "📌 提取重点"', 'label: L("qa_key_points")'),
 ('label: "📓 生成笔记"', 'label: L("qa_notes")'),
 ('label: "❓ 出3道题"', 'label: L("qa_quiz")'),
 ('question: "请总结这份文档的核心内容"', 'question: langv === "zh" ? "请总结这份文档的核心内容" : "Summarize the core content of this document"'),
 ('question: "用大白话解释这一页的内容"', 'question: langv === "zh" ? "用大白话解释这一页的内容" : "Explain this page in plain language"'),
 ('question: "提取这一页的关键要点，分条列出"', 'question: langv === "zh" ? "提取这一页的关键要点，分条列出" : "Extract the key points of this page as a list"'),
 ('question: "把这一页整理成结构化学习笔记(markdown要点式)"', 'question: langv === "zh" ? "把这一页整理成结构化学习笔记(markdown要点式)" : "Turn this page into structured study notes (markdown bullets)"'),
 ('question: "基于这一页内容出3道自测题并附答案"', 'question: langv === "zh" ? "基于这一页内容出3道自测题并附答案" : "Create 3 self-test questions with answers from this page"'),
 ('<button @click="askSelected(\'解释这段话\')">💬 解释这段</button>',
  '<button @click="askSelected(langv === \'zh\' ? \'解释这段话\' : \'Explain this passage\')">💬 {{ langv === "zh" ? "解释这段" : "Explain" }}</button>'),
 ('<button @click="askSelected(\'这段话的重点是什么？\')">📌 划重点</button>',
  '<button @click="askSelected(langv === \'zh\' ? \'这段话的重点是什么？\' : \'What are the key points here?\')">📌 {{ langv === "zh" ? "划重点" : "Points" }}</button>'),
 ('<button @click="askSelected(\'翻译成中文(如果是外文)或用大白话再讲一遍\')">🔁 换个说法</button>',
  '<button @click="askSelected(langv === \'zh\' ? \'翻译成中文(如果是外文)或用大白话再讲一遍\' : \'Translate to English if foreign, or rephrase simply\')">🔁 {{ langv === "zh" ? "换个说法" : "Rephrase" }}</button>'),
]
for a, b in reps:
    if a in s: s = s.replace(a, b)
    else: misses.append((p, a[:40]))
save(p, s)

print("MISSES:")
for m in misses:
    print(" ", m[0], "|", m[1])
