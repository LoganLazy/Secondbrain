# Memory AI — 私人第二大脑

基于 RAG 的个人知识管理助手：导入你的文档，AI 自动整理入库，之后**只基于你自己的资料**回答问题，并标注来源出处。

## 功能（v1）

- 📤 文档导入：PDF / Word / TXT / Markdown，自动解析、切块、向量化
- 🏷 AI 自动整理：生成标题 / 分类 / 标签 / 摘要
- 💬 知识问答：RAG 检索 + DeepSeek 回答，答案附带「来源: 文件 第N页」
- 🔍 语义搜索：大白话描述就能找到相关内容，显示匹配度
- 🧷 长期记忆：告诉 AI 你的设备/偏好/背景，问答时自动参考

## 技术架构

```
Electron 壳(可选) / 浏览器访问
        │
Vue3 + Vite 前端 (frontend/)
        │
FastAPI 后端 (backend/)
├── 解析: PyMuPDF(PDF带页码) / python-docx / 纯文本
├── 向量库: Chroma(本地持久化) + SQLite(元数据)
├── 向量化: 智谱 embedding-3(云端) | mock离线向量(测试)
└── 对话: DeepSeek(OpenAI兼容, 可换任意中转站)
```

所有原始文件、数据库、向量索引都在本机 `backend/data/` 目录。

## 快速开始

```bash
# 0. 准备: Python3.11 + Node20 (runtime/ 内已有便携版则跳过)

# 1. 后端依赖
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 配置密钥
cp .env.example .env   # 编辑: DEEPSEEK_KEY 必填; ZHIPU_KEY 填了才有语义检索质量

# 3. 启动后端(同时服务前端页面)
.venv/bin/python start_daemon.py     # 后台运行, 日志 last-run.log
# 或前台: .venv/bin/python -m uvicorn app.main:app --port 8787

# 4. 构建前端(首次)
cd ../frontend && npm install && npm run build

# 5a. 浏览器使用
打开 http://127.0.0.1:8787

# 5b. 桌面App方式(Electron, 需要桌面环境)
cd ../electron && npm install
../start-desktop.sh
```

## 密钥说明 (.env)

| 变量 | 用途 | 不配会怎样 |
|------|------|-----------|
| `DEEPSEEK_KEY` | 对话+自动摘要 | 功能不可用 |
| `ZHIPU_KEY` | 向量化(open.bigmodel.cn 申请) | 退化为 mock 哈希向量, 仅能联调不能语义搜索 |
| `CHAT_BASE_URL` | OpenAI兼容地址, 可指中转站/ollama | 默认官方 |

## API 一览

```
POST /api/upload    上传文档(multipart)
GET  /api/docs      文档列表      DELETE /api/docs/{id}
POST /api/search    语义搜索 {query}
POST /api/chat      RAG问答 {question}
GET  /api/history   对话历史
POST /api/memory    添加长期记忆 {content}   GET/DELETE 同路径
GET  /api/stats     统计
```

## 路线图

- v2: 图片OCR(PaddleOCR)、网页链接导入、阅读助手(原文侧栏AI)、复习闪卡
- v3: 知识图谱可视化、多设备同步、纯本地Ollama模式

## License

MIT
