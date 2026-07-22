# 行旅天下 · AI 旅行助手需求文档

> 文档类型：产品需求文档（PRD）+ 技术方案
>
> 版本：v1.0
>
> 编写日期：2026-07-22
>
> 适用项目：helloagents-trip-planner
>
> 当前实现基线：Vue 3 + TypeScript + Vite 前端；FastAPI + HelloAgents 后端；高德地图服务/MCP；PostgreSQL；已有用户登录、历史对话和旅行表单雏形。

---

## 1. 项目概述

### 1.1 产品定位

“行旅天下”是一款以大语言模型为核心的智能旅行规划助手。用户通过填写结构化旅行信息获得一版可执行的初代行程，再通过上下文对话持续调整目的地、景点顺序、餐饮、酒店、交通和预算，最终形成可保存、可复用、可分享的个性化旅行计划。

产品定位为旅行计划协作工具，具备以下能力：

1. 先填表，快速得到初稿，降低用户面对空白对话框的输入成本。
2. 再对话，持续优化计划，不要求重复描述目的地和日期。
3. 显式表达偏好，通过美食口味、酒店风格、预算等可选项，让结果更稳定。
4. 结合真实地理信息，调用高德地图搜索 POI、路线、天气等信息，减少模型臆测。
5. 输出可执行行程，以每日时间线、地图、交通、餐饮、住宿和预算摘要呈现结果。

### 1.2 建设目标

| 目标 | 衡量方式 |
|---|---|
| 提升首次规划成功率 | 完整表单提交后，95% 的请求返回结构化初代规划或明确失败原因 |
| 降低规划门槛 | 用户无需掌握提示词即可完成一次初始规划 |
| 提高个性化程度 | 结果能体现至少 3 项显式偏好，如口味、酒店风格、预算 |
| 支持迭代协作 | 可通过自然语言增删景点、调整节奏、替换餐厅、控制预算 |
| 提升结果可信度 | 地点尽量绑定高德 POI/路线数据，并展示来源或数据更新时间 |
| 保留用户资产 | 登录用户可保存历史对话、偏好和旅行计划，并继续修改 |

### 1.3 非目标（v1.0 暂不做）

- 不直接替用户完成机票、酒店、门票下单和支付。
- 不承诺实时价格、库存和订单可用性；预算为规划估算值。
- 不实现多人实时协同编辑。
- 不覆盖签证、保险、医疗和法律意见等高风险决策；相关内容仅作提示并要求用户自行核验。

---

## 2. 用户与核心旅程

### 2.1 目标用户

1. 周末短途用户：希望快速生成 1～3 天的城市周边行程。
2. 首次到访用户：不了解景点分布、交通和当地餐饮，希望获得完整建议。
3. 有明确偏好的用户：不吃辣、偏好清真/素食、喜欢设计感酒店或必须控预算。
4. 已有初步想法的用户：已有若干必去地点，希望 AI 负责排序、补全和取舍。
5. 家庭/朋友出行用户：需要考虑同行人数、老人儿童、节奏、预算和无障碍。

### 2.2 核心用户流程

~~~mermaid
flowchart LR
    A[进入首页] --> B[填写旅行表单]
    B --> C[提交并生成初代规划]
    C --> D[查看每日行程/地图/预算]
    D --> E[上下文对话提出修改]
    E --> F[AI调用地图与规划工具]
    F --> G[返回优化版本与变更摘要]
    G --> H{是否满意}
    H -- 否 --> E
    H -- 是 --> I[保存/收藏/分享/导出]
~~~

### 2.3 典型场景

- “我和两位朋友 7 月 27 日到 29 日去陆丰，公共交通，住经济型酒店，想吃当地特色，每餐人均不超过 40 元。”
- “把第二天早上的景点换成室内活动，下午不要安排太满。”
- “我不吃辣，也不吃海鲜；请替换为清淡粤菜，并保持每天餐饮预算不超过 120 元。”
- “酒店换成有设计感、交通方便的民宿，但总住宿预算不能超过 800 元。”
- “下雨时怎么调整？保留今天最重要的两个景点。”

---

## 3. 页面与模块范围

| 模块 | 说明 | 优先级 |
|---|---|---|
| 首页/新行程 | 填写旅行表单，生成初代规划 | P0 |
| 规划结果页 | 每日行程、地图、路线、餐饮、住宿、预算 | P0 |
| 上下文对话区 | 对当前行程进行自然语言修改 | P0 |
| 偏好设置 | 保存和编辑美食、酒店、预算等偏好 | P0 |
| 历史对话 | 查看、继续和删除历史行程 | P0 |
| 用户登录/注册 | 保存个人资产；兼容现有本地账号及 OAuth 方向 | P0 |
| 灵感收藏 | 收藏地点、餐厅、酒店或完整方案 | P1 |
| 分享/导出 | 只读分享链接或 Markdown/PDF | P1 |
| 订单/预订 | 第三方预订与支付 | P2 |

现有项目兼容原则：保留 Vue 3、TypeScript、Vite、Ant Design Vue、Axios；保留 FastAPI、Pydantic、HelloAgents、高德地图 MCP 和 PostgreSQL；在 app_users、conversations 基础上扩展数据表；模型、Base URL、API Key、超时和降级策略全部环境变量化。

---

## 4. 功能需求

> P0 = 首个可用版本必须有；P1 = 首期增强；P2 = 后续版本。

### 4.1 FR-001 填表生成初代规划（P0）

#### 表单字段

| 字段 | 类型 | 必填 | 规则/说明 |
|---|---|---:|---|
| 目的地 | 城市搜索/文本 | 是 | 支持城市、区域；提交前非空校验 |
| 出发地 | 城市搜索/文本 | 否 | 用于估算跨城交通 |
| 出发日期 | 日期 | 是 | 默认不早于当前日期 |
| 返程日期/旅行天数 | 日期/数字 | 是 | 至少 1 天，自动计算天数 |
| 同行人数 | 数字 | 是 | 默认 1，支持成人/儿童/老人拆分 |
| 同行成员 | 多选标签 | 否 | 独自、情侣、朋友、家庭、带老人、带儿童 |
| 交通方式 | 单选/多选 | 是 | 公共交通、自驾、打车、步行优先、混合 |
| 住宿偏好 | 单选 | 否 | 经济型、舒适型、品质型、民宿、青旅等 |
| 旅行风格 | 多选 | 否 | 轻松、特种兵、文化、自然、美食、亲子、拍照、夜游等 |
| 美食口味 | 多选/标签 | 否 | 见 4.3 |
| 酒店风格 | 多选/标签 | 否 | 见 4.3 |
| 总预算 | 区间/数字 | 否 | 支持总预算、日均预算、分项预算 |
| 必去地点 | 文本/标签 | 否 | 景点、商圈、餐厅或活动 |
| 排除项 | 文本/标签 | 否 | 不想去的地点、拥挤、夜间活动等 |
| 额外要求 | 多行文本 | 否 | 无障碍、过敏、作息、拍照等 |

#### 表单交互

1. 支持快速模式：只填写目的地、日期、人数和旅行风格。
2. 支持展开个性化设置，补充口味、酒店、预算和约束。
3. 草稿自动保存，刷新后尽量恢复未提交内容。
4. 日期、人数、预算和互相矛盾的约束在前端即时提示。
5. 提交后展示：解析需求 → 搜索地点 → 规划路线 → 整理行程。
6. 失败时保留表单，提供重试、简化要求后重试、改用对话补充。
7. 成功后创建会话和初始计划版本，跳转结果页。

#### 初代规划输出

必须包含：行程概览；每日时间线；地点地址、坐标、营业时间（如可获得）；交通方式、距离和预计时长；早餐/午餐/晚餐/小吃及口味匹配说明；住宿区域、风格说明和预算；交通/住宿/餐饮/门票/机动费用摘要；天气、营业时间、预约、体力、拥堵和数据不确定性提醒。

### 4.2 FR-002 上下文对话优化规划（P0）

支持增删改景点、餐厅和酒店，交换日期，调整上午/下午/晚上安排，降低预算、缩短步行、减少换乘、避免早起，修改偏好，以及雨天、晚到、闭馆、同行人变更等条件模拟。

交互要求：

1. 固定显示当前行程摘要：目的地、日期、人数、预算和偏好。
2. 每次回答说明“已修改了什么”。
3. 每次修改生成新的计划版本，不覆盖旧版本；支持回退。
4. 缺少关键信息时只追问最必要的 1～3 个问题。
5. 提供“更轻松”“少走路”“压预算”“替换晚餐”等快捷指令。
6. 支持“应用到行程”与“仅查看建议”。
7. 生成期间支持流式输出，显示工具调用状态但不暴露密钥和内部提示词。
8. 上下文由最近消息、当前计划 JSON、用户偏好和最新指令组成，不让模型从长文本猜状态。

版本规则：每个版本记录 version_id、创建时间、来源消息和变更摘要；旧版本修改时进行冲突提示；不得删除用户标记为“必去”的地点，除非用户再次确认；无法同时满足预算、时间和距离时，必须列出冲突及备选方案。

### 4.3 FR-003 个性化偏好（P0）

#### 美食口味

支持口味标签：清淡、偏辣、麻辣、酸甜、咸鲜、甜口、烧烤、海鲜、粤菜、川菜、湘菜、日料、西餐、当地特色、小吃。

支持饮食限制：素食、清真、低糖、低盐、无麸质、过敏原排除、不吃海鲜、不吃香菜等。

支持用餐偏好：苍蝇馆子、连锁、网红店、街边小吃、环境优先、方便快捷、包间；支持单餐人均与每日餐饮预算。

系统需把标签转为结构化约束，并在推荐中输出匹配理由。

#### 酒店风格

支持类型：经济型、舒适型、高端、民宿、青旅、度假村、公寓；支持风格：设计感、简约、传统文化、自然度假、亲子友好、商务、安静、拍照出片；支持位置：市中心、景区、交通枢纽、海边/湖边、安静街区；支持设施：早餐、停车、洗衣、健身房、泳池、无障碍、家庭房、宠物友好。

#### 预算

支持总预算、日均预算、分项预算三种模式。结果必须展示估算值、已知费用、未知费用、机动比例和超预算原因，并标注“估算/以实际为准”。

#### 偏好档案

登录用户可保存默认美食偏好、酒店风格和预算、交通方式、同行人类型、作息、步行强度及禁忌/过敏/无障碍要求；新行程自动带入，本次行程可以临时覆盖默认值。

### 4.4 FR-004 规划结果展示（P0）

结果页采用“行程 + 地图 + 对话”三栏或响应式布局：左侧日期列表，中间时间线卡片，右侧高德地图和地点筛选，移动端改为抽屉。单个行程卡片展示时间、地点、活动、停留时长、交通方式、预计费用、适配标签，并提供替换、删除、移动、收藏操作。

### 4.5 FR-005 历史对话与计划管理（P0）

登录用户可查看会话列表、标题和更新时间；初代规划自动生成标题并可修改；支持继续对话、删除会话和重试失败规划；未登录用户允许临时会话，登录后提示同步。

### 4.6 FR-006 地图与实时信息（P0）

通过高德地图服务/MCP 搜索景点、餐厅、酒店，支持地理编码、逆地理编码和路线规划；按天/时间段显示地图标记；营业时间、天气、路线和价格标注数据时间；工具失败时展示“暂无法核验”。模型优先使用工具返回的 POI 和坐标，禁止只凭记忆生成虚构地点。

### 4.7 FR-007 收藏、分享与导出（P1）

支持收藏地点和行程版本；生成只读分享链接并设置有效期；导出 Markdown/JSON，后续扩展 PDF/长图；分享默认隐藏用户私密信息和对话原文。

---

## 5. 业务规则

### 5.1 约束优先级

1. 安全、过敏、无障碍和明确不可接受条件。
2. 日期、营业时间、预约和地理可达性。
3. 必去地点和明确指定地点。
4. 总预算/分项预算。
5. 交通方式、步行强度和作息。
6. 偏好标签、推荐丰富度和体验优化。

### 5.2 可执行性

- 每天默认安排 2～5 个核心活动，按城市密度和风格动态调整。
- 相邻地点优先按地理距离聚类，避免跨区往返。
- 每个移动段保留缓冲时间；家庭、老人、儿童提高缓冲比例。
- 夜间活动结合用户偏好、营业时间和安全提醒。
- 区分确定信息、模型建议、待核验信息。
- 时间、预算或营业时间冲突必须显式提示。

### 5.3 AI 边界

不伪造库存、订单、实时票价、营业状态或官方政策；不将估算价格写成确定价格；对医疗、签证、灾害等高风险信息要求用户核验；模型输出经过 XSS/HTML 安全处理。

---

## 6. 技术路线

### 6.1 总体架构

~~~mermaid
flowchart TB
    UI[Vue 3 + TypeScript + Vite]
    API[FastAPI API Gateway]
    AUTH[认证与会话服务]
    PLAN[旅行规划服务]
    CHAT[上下文对话服务]
    PREF[偏好服务]
    MAP[高德地图服务 / MCP]
    AGENT[HelloAgents Planner Agent]
    LLM[DeepSeek API\n默认模型: deepseek-v4-flash]
    DB[(PostgreSQL)]
    CACHE[(Redis 可选)]
    OBS[日志/指标/链路追踪]

    UI -->|REST + SSE| API
    API --> AUTH
    API --> PLAN
    API --> CHAT
    API --> PREF
    PLAN --> AGENT
    CHAT --> AGENT
    AGENT --> LLM
    AGENT --> MAP
    AUTH --> DB
    PLAN --> DB
    CHAT --> DB
    PREF --> DB
    API --> CACHE
    API --> OBS
~~~

### 6.2 前端

- 框架：Vue 3 + Composition API + TypeScript。
- 构建：Vite。
- 组件库：Ant Design Vue。
- 状态管理：建议新增 Pinia，拆分用户、表单草稿、当前计划、对话流状态。
- 网络层：Axios 封装 REST；SSE 用于规划进度和流式对话。
- 地图：高德地图 JavaScript API；前端只放 Web 端 Key，服务端 Key 单独管理。
- 路由：/、/result?conversation=...、/preferences、/share/:token。
- 数据校验：前端即时校验 + 后端 Pydantic 二次校验。

建议目录：

- frontend/src/views/HomeView.vue：新行程表单。
- frontend/src/views/ResultView.vue：结果、地图和对话。
- frontend/src/views/PreferencesView.vue：偏好档案。
- frontend/src/components/trip/TripForm.vue：结构化表单。
- frontend/src/components/trip/ItineraryTimeline.vue：时间线。
- frontend/src/components/trip/MapPanel.vue：地图。
- frontend/src/components/chat/ChatPanel.vue：上下文对话。
- frontend/src/services/api.ts：认证和旅行 API。
- frontend/src/services/stream.ts：SSE 客户端。
- frontend/src/types/trip.ts：类型定义。

### 6.3 后端

- API：Python FastAPI。
- 数据：Pydantic v2；SQLAlchemy Async + asyncpg；PostgreSQL。
- Agent：HelloAgents SimpleAgent/规划 Agent，封装为独立服务，不在路由层拼接复杂提示词。
- 地图：高德 Web 服务 API 与 MCP 工具分层封装，Agent 只能使用白名单工具。
- 流式：FastAPI StreamingResponse + SSE；后续双向协作再评估 WebSocket。
- 异步任务：v1.0 先用 FastAPI 异步请求；高并发时增加 Redis + Celery/Arq。
- 配置：pydantic-settings + .env；密钥不得提交 Git。
- 日志：记录 request_id、conversation_id、plan_version_id、模型耗时、工具耗时和错误码，不记录完整 API Key。

### 6.4 DeepSeek 调用建议

通过 OpenAI 兼容接口调用 DeepSeek，默认配置为：

~~~env
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL_ID=deepseek-v4-flash
LLM_API_KEY=<your-deepseek-api-key>
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=8000
~~~

模型名、Base URL、超时、最大输出 Token、温度和重试次数必须支持环境变量覆盖。生产请求显式传入模型名，并在上线前做真实调用验证，确认账号权限、上下文长度、结构化输出和工具调用能力。

### 6.5 Agent 工作流

1. 需求解析：表单和自由文本 → TripRequirement JSON。
2. 地点检索：城市、日期、风格和预算 → 高德 POI/路线工具。
3. 初代规划：结构化需求 + 工具结果 → ItineraryPlan JSON。
4. 服务端校验：日期、预算、地点坐标、必填字段；失败则修复或降级。
5. 对话优化：当前计划 JSON + 偏好 + 最近消息 + 最新指令 → PlanChangeSet。
6. 应用变更：后端应用操作集、校验并保存新版本。
7. 用户解释：生成自然语言变更摘要，但不把解释文本当作唯一事实来源。

建议核心 Schema：TripRequirement、PreferenceProfile、ItineraryPlan、ItineraryDay、ItineraryItem、BudgetSummary、PlanChangeSet。

对话优先生成操作集，例如：

~~~json
{
  "op": "replace_item",
  "day": 2,
  "item_id": "d2-3",
  "reason": "用户不吃辣",
  "constraints": {"cuisine": "清淡粤菜"}
}
~~~

### 6.6 降级与容错

- DeepSeek 超时：重试 1～2 次，仍失败则返回可恢复错误并保留表单。
- JSON 不合法：尝试修复；失败时降级为文本建议并提示结构化行程暂不可用。
- 高德不可用：生成非实时建议，但标注地点信息未核验。
- 单个 POI 查询失败：跳过该地点，继续完成规划。
- 预算无法满足：返回省钱/平衡/舒适多方案。
- 频率超限：返回明确限流提示，不暴露供应商内部错误。

---

## 7. API 设计

统一前缀建议为 /api，所有接口返回 request_id；错误统一为 {code, message, details, request_id}。

### 7.1 旅行规划

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/trips/plan | 提交表单，创建会话并生成初代规划 |
| GET | /api/trips/{conversation_id} | 获取会话与最新计划 |
| GET | /api/trips/{conversation_id}/versions | 获取计划版本 |
| POST | /api/trips/{conversation_id}/retry | 重试生成或工具调用 |
| POST | /api/trips/{conversation_id}/apply-change | 应用确认后的计划变更 |
| POST | /api/trips/{conversation_id}/rollback | 回退到指定版本 |
| GET | /api/trips/{conversation_id}/stream | SSE 推送规划进度/结果 |

### 7.2 上下文对话

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/conversations/{id}/messages | 发送优化指令 |
| GET | /api/conversations/{id}/messages | 分页读取消息 |
| GET | /api/conversations/{id}/stream | SSE 流式返回回答、工具状态和变更摘要 |
| PATCH | /api/conversations/{id} | 修改标题/归档状态 |
| DELETE | /api/conversations/{id} | 删除会话及计划版本 |

### 7.3 偏好

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/preferences/me | 获取默认偏好 |
| PUT | /api/preferences/me | 保存默认偏好 |
| POST | /api/preferences/validate | 校验偏好冲突 |
| GET | /api/preferences/options | 获取标签选项 |

### 7.4 表单请求示例

~~~json
{
  "destination": "陆丰",
  "origin": "广州",
  "start_date": "2026-07-27",
  "end_date": "2026-07-29",
  "travelers": {"adults": 3, "children": 0, "seniors": 0},
  "transportation": ["public_transit"],
  "travel_style": ["food", "relaxed"],
  "preferences": {
    "food": {"flavors": ["light", "local_specialty"], "avoid": ["spicy"], "meal_budget_per_person": 40},
    "hotel": {"types": ["economy_hotel"], "styles": ["quiet", "convenient"], "nightly_budget": 300},
    "budget": {"total": 3000, "currency": "CNY"}
  },
  "must_visit": [],
  "excluded": [],
  "free_text": "每餐人均不超过 40 元，尽量少换乘"
}
~~~

### 7.5 规划响应核心结构

~~~json
{
  "conversation_id": "conv_xxx",
  "plan_version_id": "plan_v1",
  "status": "completed",
  "summary": {},
  "days": [],
  "budget": {},
  "warnings": [],
  "data_quality": {"verified_poi_count": 8, "unverified_count": 1, "generated_at": "2026-07-22T00:00:00Z"},
  "change_summary": []
}
~~~

---

## 8. 数据库设计

现有 app_users、conversations 表继续保留，建议增加或扩展：

### 8.1 trip_requirements

保存原始表单和解析后的结构化约束，字段包括 id、conversation_id、raw_payload、normalized_payload、schema_version、created_at。

### 8.2 preference_profiles

字段包括 id、user_id、name、food_preferences、hotel_preferences、budget_preferences、transport_preferences、constraints、is_default、updated_at。

### 8.3 plan_versions

字段包括 id、conversation_id、parent_version_id、plan_payload、source_message_id、change_summary、status、created_at。

### 8.4 conversation_messages

字段包括 id、conversation_id、role、content、structured_action、tool_trace、token_usage、created_at。

### 8.5 conversations 扩展

建议增加 trip_requirement_id、latest_plan_version_id；继续保留 payload 以兼容现有历史数据。

### 8.6 favorites / share_links（P1）

用于收藏地点/计划和只读分享链接；分享 Token 必须随机且不可枚举，并支持过期。

---

## 9. 安全、隐私与非功能需求

### 9.1 安全与隐私

1. API Key、JWT 密钥、OAuth Secret、数据库密码只通过环境变量或密钥管理服务注入。
2. 密码使用强哈希，禁止明文；生产环境关闭默认账号或强制修改默认密码。
3. 认证接口增加失败次数限制和基础限流。
4. 用户只能读写自己的会话、偏好和计划。
5. 分享链接只读，默认不包含身份信息、原始对话或隐私约束。
6. 对发送给模型的内容做最小化；日志脱敏，不记录完整 Token、Cookie 或 API Key。
7. 模型输出做 XSS/HTML 清洗，Markdown 渲染使用安全白名单。
8. 工具参数白名单校验，禁止模型构造任意 URL、SQL 或系统命令。
9. 向用户说明价格、营业时间、天气、交通和政策需以实际或官方渠道为准。

### 9.2 性能与可用性

- 首页主要内容 3 秒内展示。
- 规划常规请求目标 60 秒内返回，超过 15 秒展示进度。
- 普通消息首 token 目标不超过 5 秒。
- 历史消息分页加载。
- 所有加载、空状态、错误、权限不足和未核验状态均有反馈。
- 支持移动端填写、查看和对话。

### 9.3 可观测性

记录初代规划成功率/耗时、模型耗时/Token/错误/重试、高德工具耗时/成功率、用户修改次数/回退次数/保存率、预算超限率和地点未核验率。

---

## 10. 测试与验收标准

### 10.1 功能验收

- [ ] 目的地、日期、人数、交通、住宿、风格和额外要求可填写并提交。
- [ ] 美食口味、饮食禁忌、酒店风格和预算可选择，并体现在结果中。
- [ ] 初代规划包含每日行程、交通、餐饮、住宿、预算和提醒。
- [ ] “删除景点”“替换餐厅”“减少步行”等指令可生成新版本并展示变更摘要。
- [ ] 可查看旧版本并回退。
- [ ] 会话可保存、继续、删除，且与用户绑定。
- [ ] 地图标记关联行程地点；地图失败时降级。
- [ ] 模型或工具超时时可以重试且不丢表单。

### 10.2 固定测试案例

1. 三人、陆丰、3 天、公共交通、经济型酒店、餐饮人均 40 元。
2. 亲子出行、少步行、家庭房和室内备选。
3. 素食 + 不吃辣 + 严格预算，检查餐厅和预算约束。
4. 自驾出行，检查停车和路线字段。
5. “把第二天改成雨天方案”，检查上下文和版本变更。
6. 高德工具超时、模型非法 JSON、未登录临时会话登录后同步。

---

## 11. 研发分期

### Phase 0：需求与基础治理（1～2 天）

固化数据模型、API 契约和 JSON Schema；确认 DeepSeek 账号、模型权限、Base URL 和限额；统一环境变量和错误码。

### Phase 1：表单初代规划 MVP（3～5 天）

完成 TripForm、偏好选择、POST /api/trips/plan、规划状态和 SSE；打通 HelloAgents + DeepSeek + 高德工具；建立需求和计划版本表；完成时间线、预算摘要和地图标点。

### Phase 2：上下文对话与版本管理（3～5 天）

增加消息表和上下文装配器；实现操作集、变更摘要、新版本和回退；支持替换地点、调序、控预算、雨天方案。

### Phase 3：偏好档案与历史资产（2～4 天）

实现默认偏好、临时覆盖、冲突校验、草稿恢复、登录同步；视排期增加收藏和分享。

### Phase 4：质量与上线（3～5 天）

增加自动化测试、固定评测集、限流、重试、监控、成本统计、密钥管理、迁移、备份和发布流程。

---

## 12. 推荐环境变量

后端建议：

~~~env
APP_NAME=行旅天下
DEBUG=false
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<database>
CORS_ORIGINS=http://localhost:5173
LLM_PROVIDER=deepseek
LLM_API_KEY=<your-deepseek-api-key>
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL_ID=deepseek-v4-flash
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=8000
PLANNER_INIT_TIMEOUT_SECONDS=180
PLANNER_EXECUTION_TIMEOUT_SECONDS=110
AMAP_API_KEY=<your-amap-server-key>
JWT_SECRET=<random-production-secret>
~~~

前端只配置公开的 API 地址和高德 Web 端 Key：

~~~env
VITE_API_BASE_URL=http://localhost:8000/api
VITE_AMAP_JS_KEY=<your-amap-web-js-key>
~~~

---

## 13. 待确认决策

1. DeepSeek API 的实际模型标识、账号可用区域、上下文长度、结构化输出和工具调用能力，需要在项目环境真实验证；配置层保持可切换。
2. 高德地图 MCP 由后端进程托管还是独立服务托管，需要结合部署环境确定。
3. 是否允许规划历史日期；默认建议只允许今天及未来日期。
4. 是否接入实时酒店/门票接口；v1.0 建议先做估算并明确核验提示。
5. 是否引入 Redis；低并发 Phase 1 可不引入，需要任务队列、限流或缓存时再接入。
6. 分享和导出建议作为 P1，避免影响初代规划和对话优化主链路。

---

## 14. 结论

本项目建议采用“结构化表单 + 结构化计划 JSON + 操作集对话修改 + 地图工具核验”的路线。这样既保留自然语言交互的灵活性，又让行程版本、预算和地点数据可校验、可比较、可回退。

首个可交付闭环聚焦四件事：

1. 填表生成一份可查看的初代规划。
2. 选择美食口味、酒店风格和预算，并体现在结果中。
3. 对当前计划进行上下文对话优化，生成可回退的新版本。
4. 使用 DeepSeek + HelloAgents + 高德地图工具完成真实数据增强，并在失败时可恢复。

完成上述闭环后，再扩展收藏、分享、导出和预订能力。

### 参考资料

- [DeepSeek API 文档](https://api-docs.deepseek.com/)
- [DeepSeek 模型与定价说明](https://api-docs.deepseek.com/quick_start/pricing)
- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [Vue 官方文档](https://vuejs.org/)
- [高德地图 Web 服务 API](https://lbs.amap.com/api/webservice/summary)
