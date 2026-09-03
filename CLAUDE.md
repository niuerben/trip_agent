# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

HelloAgents 智能旅行助手（产品名：**行旅天下**）：基于 HelloAgents 框架的 ReAct 旅行规划应用，集成高德地图服务和 Chroma 向量缓存生成多日行程。后端采用服务层 + ReAct Agent 架构，前端 Vue3 + Vite。产品需求详见 `docs/trip-planner-prd.md`。

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

### 服务层 + ReAct Agent 架构
系统采用职责分离的两层架构：

**服务层** (`TripPlanningService`)：
- 请求上下文准备与行政区解析（城市中心、adcode、搜索半径）
- Chroma POI 向量召回（景点/酒店/餐馆三大类）
- 证据预取与确定性计划生成（`_build_evidence_plan`）
- 定向修改执行（`_execute_change_set`）
- 计划后处理（日期归属、近邻排序、图片补齐、坐标校验）

**ReAct Agent 层** (`PlanAgent` + `ValidatedPlanningReActAgent`)：
- `PlanAgent` 作为薄封装，注册领域工具（`tool_lib.py` 中的 SearchAttraction/Weather/Hotel/Restaurant）
- `ValidatedPlanningReActAgent` 执行 ReAct 循环，调用 `PlanningToolset` 搜索 POI
- `validate_draft` 工具负责计划校验，只允许通过校验的计划交付

关键约定：
- ReAct 历史必须保留每轮 `Thought`、`Action` 与 `Observation`，不得通过伪造 Observation 绕过校验
- `PlanningToolset` 负责 POI 搜索工具路由与证据记录；高德与 Chroma 调用保留在服务层
- 图片补齐（`_enrich_attraction_images`）只接受高德域名（`autonavi.com`），用于替换模型示例 URL
- 定向修改与预加载证据模式下跳过图片补齐，避免超时（转为前端异步加载）

### 高德地图与向量缓存
系统采用"向量召回 + 高德补充"的混合检索策略：

**Chroma 向量缓存**：
- 持久化存储高德 POI 的名称、地址、POI ID、坐标和类型标签
- 规划前按城市和偏好分类召回（景点/酒店/餐馆三大类）
- 只缓存 POI 数据，不缓存天气和路线（实时查询）
- 区县级请求使用 adcode 硬过滤，避免跨区结果

**高德地图服务**：
- **REST 通道**（`AmapService`）：POI 文本搜索、天气查询、地理编码
- **MCP 通道**（可选，`get_amap_mcp_tool`）：路线规划、POI 详情、地理编码
- 按需懒加载 MCP 进程，避免简单查询依赖 uvx

**检索路径**：
1. Chroma 召回候选（超时 3 秒则跳过）
2. 按需调用高德 REST API 补充新 POI
3. 所有高德返回的 POI 自动写入 Chroma，形成持久缓存

### LLM 配置桥接
`llm_service.get_llm()` 用 `HelloAgentsLLM()`，它读 `OPENAI_*` 环境变量。项目对外用 `LLM_*` 命名，`llm_service` 和 `config.py` 会把 `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_ID` 映射到 `OPENAI_*`。`config.py` 还会尝试加载同级目录 `../HelloAgents/.env`（不覆盖已有变量）。

### API 路由
`app/api/main.py` 注册全部路由，前缀 `/api`：`trip`（规划）、`poi`、`map`、`auth`、`conversations`。所有 Agent 调用在 `trip.py` 中通过 `asyncio.to_thread` + `asyncio.wait_for` 包裹，受 `PLANNER_INIT_TIMEOUT_SECONDS` / `PLANNER_EXECUTION_TIMEOUT_SECONDS` 控制超时。

规划服务提供两种模式：
- **ReAct 模式**（默认）：通过 `PlanAgent` + `ValidatedPlanningReActAgent` 执行 POI 搜索与计划生成
- **确定性模式**（可选，`PLANNER_PRELOADED_DETERMINISTIC_PLAN=true`）：预取完整 POI 证据后，通过 `_build_evidence_plan` 近邻排程生成计划，跳过长 JSON 模型调用
- **降级模式**（`PLANNER_MODE=fallback`）：强制跳过 LLM，返回模拟数据

### 认证与持久化
- `auth.py`：本地账号密码登录/注册（PBKDF2 哈希）+ GitHub/微信 OAuth，签发 HS256 JWT。第三方密钥只在服务端使用。
- `conversations.py`：聊天记录 CRUD，从 `Authorization: Bearer` 解析 `user_id`（无 token 则用 `local:guest`），时间统一输出北京时间。
- 数据库为 PostgreSQL（asyncpg），`database.py` 在启动时 `CREATE TABLE IF NOT EXISTS` 建 `app_users` / `conversations` / `conversation_preferences` 三表。**未配置 `DATABASE_URL` 时全部降级**：`engine` 为 `None`，登录回退到 `.env` 中的 `AUTH_USERNAME/AUTH_PASSWORD`，会话接口返回 503。

### 前端
- `src/services/api.ts`：axios 客户端，开发环境固定指向 `http://localhost:8000`，请求拦截器自动附加 localStorage 中的 JWT，401 时清除会话
- `src/services/conversations.ts`：会话记录接口
- 视图 `views/Home.vue`（表单）、`views/Result.vue`（行程展示，含高德 JS 地图、html2canvas/jsPDF 导出）
- 高德 Web/JS Key 通过 `VITE_AMAP_WEB_KEY` / `VITE_AMAP_WEB_JS_KEY` 注入
- 前端负责异步加载行程图片（定向修改和预加载证据模式下，后端跳过图片补齐避免超时）

## 注意事项
- 后端默认端口 `8000`，与前端 Vite 代理、OAuth 回调一致（`backend/.env.example` 的 `PORT` 及回调 URL 均为 8000）
- 数据模型集中在 `backend/app/models/schemas.py`（`TripRequest`/`TripPlan`/`DayPlan`/`Attraction` 等），前端类型在 `frontend/src/types/index.ts`，两侧改字段需同步
- Chroma 数据目录默认为 `backend/data/chroma/`，属于本地可重建缓存，不应提交到 Git
- 定向修改（`change_set`）与预加载证据模式下，后端跳过图片补齐以避免超时，前端需异步加载图片
- 区县级请求（如"深圳坪山"）自动映射到地级市进行高德搜索，再通过 adcode 硬过滤保证结果在目标区县内
