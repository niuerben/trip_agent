# 行旅天下 🌍✈️

基于 [HelloAgents](https://github.com/jjyaoao/HelloAgents) 构建的智能旅行规划应用。系统结合大语言模型、高德地图与 Chroma POI 向量缓存，为用户生成包含景点、餐饮、住宿、天气和交通信息的多日行程，并支持通过对话收集偏好和定向调整计划。

> 产品需求与技术路线详见 [docs/trip-planner-prd.md](docs/trip-planner-prd.md)。

## 功能概览

- **智能行程规划**：根据目的地、日期、交通方式、住宿和旅行偏好生成多日计划
- **对话式偏好收集**：通过多轮对话提炼偏好，并支持对已有行程进行语义化定向修改
- **混合 POI 检索**：优先从 Chroma 召回本地候选，不足时调用高德 Web 服务补充并自动写回缓存
- **可信计划交付**：ReAct Agent 保留完整工具调用轨迹，并通过计划校验后再返回结果
- **地图与实时信息**：支持 POI 搜索、天气查询、路线规划、地图标记及景点图片补齐
- **账号与会话**：支持本地账号、GitHub/微信 OAuth，以及基于 PostgreSQL 的行程和聊天记录持久化
- **行程导出**：前端支持将旅行计划导出为图片或 PDF
- **故障降级**：模型、Chroma 或地图服务不可用时，保留 REST、基础计划等降级路径

## 技术架构

### 后端

- Python 3.10+
- FastAPI + Uvicorn
- HelloAgents + `PlanAgent` / `ValidatedPlanningReActAgent`
- 高德地图 Web API，以及按需懒加载的 MCP 通道
- Chroma PersistentClient（仅缓存 POI，不缓存天气和路线）
- PostgreSQL + SQLAlchemy Async / asyncpg
- JWT（HS256）与第三方 OAuth

规划流程采用“服务层 + ReAct Agent”分层设计：

1. `TripPlanningService` 解析城市和行政区，准备请求上下文。
2. 从 Chroma 按城市、偏好和 POI 类别召回候选；区县请求使用 adcode 硬过滤。
3. 候选不足时，通过高德 REST 服务补充景点、酒店和餐馆并写入 Chroma。
4. 默认在证据完整时使用确定性近邻排程；定向修改或证据不足时进入 ReAct 流程。
5. 对计划进行日期、坐标、距离、餐次等校验及后处理后返回前端。

### 前端

- Vue 3 + TypeScript
- Vite
- Ant Design Vue
- Axios
- 高德地图 JavaScript API
- html2canvas + jsPDF

开发环境下，前端通过 Vite 将 `/api` 请求代理到 `http://localhost:8000`；生产环境可通过 `VITE_API_BASE_URL` 指定后端地址。

## 项目结构

```text
helloagents-trip-planner/
├── backend/
│   ├── app/
│   │   ├── agents/              # 规划、搜索、校验及偏好对话 Agent
│   │   ├── api/
│   │   │   ├── main.py          # FastAPI 应用入口
│   │   │   └── routes/          # trip、poi、map、auth、conversations、talk
│   │   ├── models/              # Pydantic 数据模型
│   │   ├── services/            # 规划、高德、LLM、Chroma 等服务
│   │   ├── config.py            # 环境变量与应用配置
│   │   └── database.py          # PostgreSQL 初始化与健康检查
│   ├── scripts/                 # POI 回填等辅助脚本
│   ├── requirements.txt
│   ├── run.py
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── services/
│   │   ├── types/
│   │   └── views/
│   ├── package.json
│   ├── vite.config.ts
│   └── .env.example
├── test/                         # 端到端、集成与单元测试
├── docs/
└── README.md
```

## 快速开始

### 前置条件

- Python 3.10+
- Node.js 18+（建议使用当前 LTS 版本）
- 一个兼容 OpenAI API 的模型服务密钥
- 高德地图 Web 服务 Key 和 Web 端 JS API Key
- PostgreSQL（如需注册、登录、OAuth、会话和聊天记录持久化）
- `uvx` 与高德 MCP Key（仅在启用 MCP 路线/详情能力时需要）

### 1. 启动后端

```bash
cd backend
python -m venv venv
```

激活虚拟环境：

```bash
# Windows PowerShell
.\venv\Scripts\Activate.ps1

# macOS / Linux
source venv/bin/activate
```

安装依赖并创建配置文件：

```bash
pip install -r requirements.txt
cp .env.example .env
```

Windows PowerShell 也可以使用：

```powershell
Copy-Item .env.example .env
```

至少配置以下变量：

```env
AMAP_API_KEY=your_amap_web_service_key
LLM_API_KEY=your_llm_api_key
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL_ID=your_model_id
JWT_SECRET=replace_with_a_long_random_secret
```

如需数据库持久化，再配置：

```env
DATABASE_URL=postgresql+asyncpg://postgres:password@127.0.0.1:5432/app
```

启动服务（二选一）：

```bash
python run.py
# 或
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

启动后可访问：

- API 文档：<http://localhost:8000/docs>
- ReDoc：<http://localhost:8000/redoc>
- 健康检查：<http://localhost:8000/health>

> 后端启动时会自动创建所需数据库表，无需手动进入 `psql` 建表。未配置 `DATABASE_URL` 时，数据库相关接口会降级或返回 503；本地账号登录可回退到 `AUTH_USERNAME` / `AUTH_PASSWORD`。

### 2. 启动前端

```bash
cd frontend
npm install
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

配置高德前端 Key：

```env
VITE_AMAP_WEB_KEY=your_amap_web_service_key
VITE_AMAP_WEB_JS_KEY=your_amap_javascript_api_key
```

启动开发服务器：

```bash
npm run dev
```

浏览器访问 <http://localhost:5173>。

## 主要配置

完整配置示例见 [`backend/.env.example`](backend/.env.example)。常用选项如下：

| 配置项 | 说明 |
| --- | --- |
| `LLM_API_KEY` / `OPENAI_API_KEY` | 模型服务密钥 |
| `LLM_BASE_URL` / `OPENAI_BASE_URL` | OpenAI 兼容接口地址 |
| `LLM_MODEL_ID` / `OPENAI_MODEL` | 模型 ID |
| `AMAP_API_KEY` | 高德 Web 服务 Key，用于 POI、天气等 REST 请求 |
| `AMAP_MAPS_API_KEY` | 高德 MCP 服务 Key（可选） |
| `DATABASE_URL` | PostgreSQL asyncpg 连接串 |
| `JWT_SECRET` | JWT 签名密钥，生产环境必须更换 |
| `PLANNER_MODE` | `auto` 使用正常规划链路，`fallback` 强制返回基础计划 |
| `PLANNER_PRELOAD_POI_EVIDENCE` | 是否在完整规划前预取 POI 证据 |
| `PLANNER_PRELOADED_DETERMINISTIC_PLAN` | 证据完整时是否使用确定性近邻排程 |
| `PLANNER_INIT_TIMEOUT_SECONDS` | 规划服务初始化超时 |
| `PLANNER_EXECUTION_TIMEOUT_SECONDS` | 单次规划执行超时 |
| `CHROMA_PERSIST_DIRECTORY` | Chroma 数据目录，默认 `data/chroma` |
| `CHROMA_COLLECTION_NAME` | Chroma collection 名称 |
| `POI_VECTOR_TOP_K` | 向量召回数量 |
| `POI_VECTOR_DISTANCE_THRESHOLD` | 余弦距离阈值，越小越相似 |
| `DISTRICT_GEO_RADIUS_KM` | 区县级请求的地理范围限制 |

项目会将 `LLM_*` 配置桥接到 HelloAgents 使用的 `OPENAI_*` 环境变量。`backend/app/config.py` 还会尝试加载相邻 `HelloAgents/.env`，且不会覆盖已存在的环境变量。

### Chroma POI 缓存

首次通过高德查询 POI 后，系统会持久化名称、地址、POI ID、GCJ-02 坐标和类型标签。后续规划优先按城市、偏好与类别召回本地候选；天气和路线始终按需实时查询。

默认缓存目录是 `backend/data/chroma/`，属于可重建的本地数据，不应提交到 Git。

可在后端目录预热常用城市：

```bash
cd backend
python scripts/backfill_pois.py --city 深圳 --keywords 景点 公园 美食 酒店
```

## 使用流程

1. 注册或登录账号。
2. 在首页填写目的地、日期、交通方式、住宿和旅行风格。
3. 可先通过对话补充个性化偏好。
4. 提交规划请求，等待系统检索 POI 并生成经校验的行程。
5. 在结果页查看每日安排、地图、天气、交通和餐饮信息。
6. 通过自然语言对已有行程进行定向调整，或导出图片/PDF。

> `POST /api/trip/plan` 要求携带有效的 Bearer JWT。前端会自动从 localStorage 读取登录令牌并附加到请求。

## API 概览

完整接口及请求模型以 <http://localhost:8000/docs> 为准。主要路由包括：

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/auth/login` | 本地账号登录 |
| `POST /api/auth/register` | 注册账号（需要 PostgreSQL） |
| `GET /api/auth/me` | 获取当前用户 |
| `POST /api/trip/plan` | 生成旅行计划（需要登录） |
| `POST /api/trip/enrich-images` | 为计划异步补齐景点图片 |
| `GET /api/poi/search` | 高德 POI 搜索 |
| `GET /api/poi/vector-search` | Chroma POI 向量查询 |
| `GET /api/poi/photo` | 获取景点图片 |
| `GET /api/map/weather` | 查询天气 |
| `POST /api/map/route` | 规划路线 |
| `GET/POST/DELETE /api/conversations` | 会话记录管理 |
| `POST /api/talk` | 偏好对话和语义修改 |

## 测试与构建

### 前端构建

```bash
cd frontend
npm run build
```

### Playwright 端到端测试

前后端均启动后执行：

```bash
python -m playwright install
python test/test_trip_planner.py --city 广州 --preferences 美食 自然风光
```

仓库的 `test/unit/` 与 `test/integration/` 还包含后端规划、对话及真实服务链路的专项测试；运行要求以具体测试文件和本地环境配置为准。

## 故障排查

- **启动提示未配置高德或模型 Key**：检查 `backend/.env`，并确保从 `backend/` 目录启动服务。
- **注册或历史会话接口返回 503**：配置 `DATABASE_URL` 并确认 PostgreSQL 可访问。
- **规划接口返回 401**：先登录，确认请求包含 `Authorization: Bearer <token>`。
- **Chroma 不可用或首次启动较慢**：系统会自动退回高德 REST；也可先运行 POI 回填脚本。
- **地图能打开但无标记或图片**：检查前端两个 `VITE_AMAP_*` Key 的类型和授权域名。
- **MCP 不可用**：确认已安装 `uvx` 且设置 `AMAP_MAPS_API_KEY`；简单 POI 查询仍可走 REST。

## 贡献

欢迎通过 Issue 或 Pull Request 提交问题与改进。

## 开源协议

CC BY-NC-SA 4.0

## 致谢

- [HelloAgents](https://github.com/datawhalechina/Hello-Agents) — 智能体教程
- [HelloAgents 框架](https://github.com/jjyaoao/HelloAgents) — Agent 框架
- [高德地图开放平台](https://lbs.amap.com/) — 地图与位置服务
- [amap-mcp-server](https://github.com/sugarforever/amap-mcp-server) — 高德地图 MCP 服务

---

**行旅天下** — 让旅行计划变得简单而智能。
