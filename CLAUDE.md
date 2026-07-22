# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

HelloAgents 智能旅行助手（产品名：**行旅天下**）：基于 HelloAgents 框架的多智能体旅行规划应用，集成高德地图 MCP 服务生成多日行程。后端 FastAPI + 多 Agent，前端 Vue3 + Vite。产品需求详见 `docs/trip-planner-prd.md`。

## 常用命令

### 后端 (`backend/`)
```bash
# 安装依赖（需 Python 3.10+）
pip install -r requirements.txt

# 启动开发服务（二选一，reload 模式）
python run.py
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```
API 文档：`http://localhost:8000/docs`（或 `/redoc`）。

### 前端 (`frontend/`)
```bash
npm install
npm run dev        # 开发服务器，端口 5173，/api 代理到 localhost:8000
npm run build      # vue-tsc 类型检查 + vite 构建
npm run preview
```

### 测试 (`test/`)
无单元测试框架。`test/test_trip_planner.py` 是基于 Playwright 的端到端脚本，需前后端均在运行：
```bash
python -m playwright install         # 首次运行前
python test/test_trip_planner.py --city 广州 --preferences 美食 自然风光
```

## 架构要点

### 多智能体规划流水线
核心在 `backend/app/agents/trip_planner_agent.py` 的 `MultiAgentTripPlanner`。它编排 4 个 `SimpleAgent`（HelloAgents），**串行**执行：
1. 景点搜索 Agent → 2. 天气查询 Agent → 3. 酒店推荐 Agent（前三者共享同一个 `amap` MCPTool）→ 4. 行程规划 Agent（无工具，负责整合并输出 JSON）。

关键约定：
- 前三个 Agent 通过 **文本协议** 触发工具调用，格式 `[TOOL_CALL:amap_maps_text_search:keywords=...,city=...]`，提示词在文件顶部的 `*_AGENT_PROMPT` 常量中。修改工具调用行为时改这些常量。
- 规划 Agent 的输出必须是严格的 JSON（`PLANNER_AGENT_PROMPT` 定义了完整 schema），`_parse_response` 从代码块 / 花括号中提取并用 `TripPlan(**data)` 校验。
- **降级机制无处不在**：任何一步失败都会调用 `_create_fallback_plan`，它绕过 LLM/MCP，直接用高德 REST API（`amap_service`、`amap_photo_service`）拿 POI 和天气生成基础行程。修改规划逻辑时务必保持 fallback 可用。
- `_enrich_attraction_images` 只接受高德域名（`autonavi.com`）图片，用于替换模型编造的示例图片 URL。

### 高德地图双通道
高德服务有两条独立通路，不要混淆：
- **MCP 通道**（`get_amap_mcp_tool`，`uvx amap-mcp-server`）：供 Agent 调用，也用于路线规划 / 地理编码 / POI 详情。按需懒加载，避免简单查询依赖 uvx 进程。
- **REST 通道**（`AmapService` 直接 `requests` 调用 `restapi.amap.com`）：用于 POI 文本搜索和天气，是 fallback 路径的基础，不依赖 MCP。

### LLM 配置桥接
`llm_service.get_llm()` 用 `HelloAgentsLLM()`，它读 `OPENAI_*` 环境变量。项目对外用 `LLM_*` 命名，`llm_service` 和 `config.py` 会把 `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_ID` 映射到 `OPENAI_*`。`config.py` 还会尝试加载同级目录 `../HelloAgents/.env`（不覆盖已有变量）。

### API 路由
`app/api/main.py` 注册全部路由，前缀 `/api`：`trip`（规划）、`poi`、`map`、`auth`、`conversations`。所有 Agent 调用在 `trip.py` 中通过 `asyncio.to_thread` + `asyncio.wait_for` 包裹，受 `PLANNER_INIT_TIMEOUT_SECONDS` / `PLANNER_EXECUTION_TIMEOUT_SECONDS` 控制超时。`PLANNER_MODE=fallback` 可强制跳过 LLM。

### 认证与持久化
- `auth.py`：本地账号密码登录/注册（PBKDF2 哈希）+ GitHub/微信 OAuth，签发 HS256 JWT。第三方密钥只在服务端使用。
- `conversations.py`：聊天记录 CRUD，从 `Authorization: Bearer` 解析 `user_id`（无 token 则用 `local:guest`），时间统一输出北京时间。
- 数据库为 PostgreSQL（asyncpg），`database.py` 在启动时 `CREATE TABLE IF NOT EXISTS` 建 `app_users` / `conversations` 两表（schema 见 `spec.md`）。**未配置 `DATABASE_URL` 时全部降级**：`engine` 为 `None`，登录回退到 `.env` 中的 `AUTH_USERNAME/AUTH_PASSWORD`，会话接口返回 503。

### 前端
- `src/services/api.ts`：axios 客户端，开发环境固定指向 `http://localhost:8000`，请求拦截器自动附加 localStorage 中的 JWT，401 时清除会话。
- `src/services/conversations.ts`：会话记录接口。
- 视图 `views/Home.vue`（表单）、`views/Result.vue`（行程展示，含高德 JS 地图、html2canvas/jsPDF 导出）。
- 高德 Web/JS Key 通过 `VITE_AMAP_WEB_KEY` / `VITE_AMAP_WEB_JS_KEY` 注入。

## 注意事项
- 后端默认端口 `8000`，与前端 Vite 代理、OAuth 回调一致（`backend/.env.example` 的 `PORT` 及回调 URL 均为 8000）。
- 数据模型集中在 `backend/app/models/schemas.py`（`TripRequest`/`TripPlan`/`DayPlan`/`Attraction` 等），前端类型在 `frontend/src/types/index.ts`，两侧改字段需同步。
