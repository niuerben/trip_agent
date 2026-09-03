# 07：旅行规划路由——从一次请求到可交付行程

本章阅读 `backend/app/api/routes/trip.py`，把一次“帮我规划 3 天游北京”的请求走完。这个路由处在系统的最后一道 API 边界：它读取用户偏好，启动 `TripPlanningService`，等待 ReAct + Validator 产出计划，执行独立业务校验，最后才把结果交给前端。用户修改已有行程时，同一入口还负责受控的定向重规划。

## 1. 路由地图

`main.py` 以 `/api` 挂载路由，模块声明 `APIRouter(prefix="/trip")`：

| 方法 | 完整路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/trip/plan` | 首次生成或定向修改旅行计划 |
| `POST` | `/api/trip/enrich-images` | 为历史计划补齐图片、坐标和缺失天气 |
| `GET` | `/api/trip/health` | 检查规划服务能否初始化 |

核心数据模型是 `TripRequest`、`TripPlan` 和 `TripPlanResponse`。`TripRequest` 中的 `current_plan`、`change_request`、`change_set` 是修改已有计划时使用的字段。

## 2. 场景：首次规划北京三日游

请求示例：

```http
POST /api/trip/plan
Content-Type: application/json
Authorization: Bearer <token>

{
  "city": "北京",
  "start_date": "2026-09-10",
  "end_date": "2026-09-12",
  "travel_days": 3,
  "transportation": "公共交通",
  "accommodation": "经济型酒店",
  "preferences": ["历史文化", "美食"],
  "free_text_input": "每天安排两到三个景点，节奏不要太赶",
  "conversation_id": "conv-bj-001"
}
```

### 2.1 选择偏好来源

路由先确定当前用户，再按优先级取得偏好：

1. 请求中的 `request.preference`；
2. 当前用户、当前 `conversation_id` 在 `conversation_preferences` 中保存的偏好；
3. `free_text_input` 包装成 `Preference(prompt=...)`。

这个顺序让对话提炼结果能服务后续规划，同时允许一次请求临时覆盖会话记忆。选择过程会记录 `preference_source`，并把完整输入写入规划输入日志，方便排查“模型到底看到了什么”。

### 2.2 配置检查与服务初始化

当 `planner_mode` 不是 `fallback` 时，路由要求配置 `LLM_API_KEY` 或 `OPENAI_API_KEY`。缺少 key 直接返回 503，并记录一次 rejected 审查日志：

```json
{"detail": "未配置模型密钥，无法生成经过 Validator 验证的旅行计划"}
```

配置齐全后，初始化服务和执行计划都放入线程，并各自受超时控制：

```python
agent = await asyncio.wait_for(
    asyncio.to_thread(get_trip_planning_service),
    timeout=settings.planner_init_timeout_seconds,
)
planner_task = asyncio.create_task(
    asyncio.to_thread(agent.plan_trip, request, preference)
)
completed, _ = await asyncio.wait(
    {planner_task},
    timeout=settings.planner_execution_timeout_seconds,
)
```

`plan_trip()` 内部连接 PlanAgent、PlanningToolset 和 Validator。高德、Chroma 等同步调用不会直接占用 FastAPI 事件循环。若总预算耗尽，路由返回 504；线程不会强行取消，因为同步 requests/LLM 调用未必能可靠中断，后台任务会被集合保留到自然结束。

## 3. 计划交付前的双重校验

规划服务内部已经执行 ReAct Validator，路由出站前仍调用一次独立业务校验：

```python
validate_trip_plan(
    trip_plan,
    request,
    require_enriched_locations=True,
)
```

校验通过后才写入 approved 审查日志并返回：

```json
{
  "success": true,
  "message": "旅行计划生成成功",
  "data": {
    "city": "北京",
    "start_date": "2026-09-10",
    "end_date": "2026-09-12",
    "days": [],
    "weather_info": [],
    "overall_suggestions": "...",
    "budget": {"total": 0}
  }
}
```

真实响应中的 `days` 包含 `DayPlan`：日期、日索引、交通、住宿、景点、餐饮和酒店；景点、餐馆和酒店应保留真实 POI 坐标或 ID。日志明确标记 reviewer 为 `trip_plan_validator`，避免把 Talk Agent 误写成计划审核者。

## 4. 场景：修改已有行程

用户在聊天中说“把第二天的爬山换成博物馆”。Talk Agent 可能返回 `intent="replan"` 与 ChangeSet，前端将当前计划和变更提交回同一接口：

```json
{
  "city": "广州",
  "start_date": "2026-10-01",
  "end_date": "2026-10-03",
  "travel_days": 3,
  "transportation": "公共交通",
  "accommodation": "经济型酒店",
  "current_plan": {"city": "广州", "days": ["..."]},
  "change_request": "第二天把爬山换成博物馆",
  "change_set": {
    "operations": [
      {
        "operation": "replace_attraction",
        "selector": {"day_index": 1, "semantic": "山景"},
        "target": {"semantic": "博物馆"},
        "fields": {}
      }
    ]
  },
  "conversation_id": "conv-gz-001"
}
```

`ChangeOperation.operation` 只能是 `add_attraction`、`delete_attraction`、`replace_attraction`、`update_day` 或 `full_replan`。路由不执行模型给出的任意代码；ChangeSet 由规划服务按白名单解释，查询真实 POI、调整日期顺序并重新校验。成功后，若请求携带 ChangeSet，路由使用参数化 SQL 将已校验计划写回当前用户的会话。

如果定向重规划超时或失败，响应会说明“原计划保持不变”，客户端应保留旧计划，不能用空结果覆盖页面。完整规划失败则分别返回“旅行计划未通过 ReAct + Validator”或“旅行计划生成超时”。

## 5. 错误状态与审查日志

| 情况 | 状态码 | 路由行为 |
| --- | ---: | --- |
| LLM key 未配置 | 503 | 拒绝交付，写 rejected 日志 |
| 初始化或执行超时 | 504 | 记录预算信息；定向修改保留原计划 |
| Agent/规划服务异常 | 422 | 记录 rejected，不暴露底层循环细节 |
| 出站业务校验失败或未预料异常 | 500 | 记录错误并返回生成失败 |

每次规划都会尽量写入两类 JSONL 日志：输入日志保存日期、偏好、变更和当前计划；交付审查日志保存审核状态、请求上下文、最终计划或错误。日志写入失败只打印提示，不改变主请求结果。生产环境应限制日志访问权限，避免把用户行程和偏好暴露给无关人员。

## 6. 历史计划的图片与天气补齐

旧会话可能没有高德图片、坐标或完整旅行日天气，可调用：

```http
POST /api/trip/enrich-images
Content-Type: application/json
```

请求体是一个 `TripPlan`。路由先解析城市中心、adcode 和高德搜索城市；区县级请求使用区县半径与 adcode 过滤。只有景点缺少 `poi_id`，或餐馆缺少 `poi_id`/坐标时才执行 POI 富化；数据已经完整时直接深拷贝计划，避免重复请求。

天气采用“只补缺失日期”策略。路由根据计划起止日期构造内部 `TripRequest`，调用 `_complete_weather_for_travel_dates()`，已有高德预报不会重复拉取。成功仍返回 `TripPlanResponse`，消息为“景点图片补齐成功”；前端可以把该接口作为历史数据迁移或异步加载流程。

## 7. 健康检查

```http
GET /api/trip/health
```

路由以初始化超时预算调用 `get_trip_planning_service()`。成功返回：

```json
{
  "status": "healthy",
  "service": "trip-planner",
  "agent_name": "...",
  "tools_count": 4
}
```

初始化失败返回 503。这个检查能发现 Agent、工具或配置问题，但不能证明一次完整规划一定能在执行预算内成功。

## 8. 端到端流程

```text
前端表单/对话修改
  -> POST /api/trip/plan
  -> Pydantic 解析 TripRequest
  -> 用户身份与会话偏好
  -> 写入 planner_input 日志
  -> 初始化 TripPlanningService（超时）
  -> 线程执行 PlanAgent / PlanningToolset / Validator
  -> TripPlan 独立业务校验
  -> approved 审查日志
  -> ChangeSet 场景写回会话
  -> TripPlanResponse
```

这个设计把路由职责放在边界编排：请求上下文、超时、错误状态、日志和出站门禁；POI 召回与计划算法留在服务层，语义理解留在 Agent 层。前端得到的是经过验证、字段稳定的 `TripPlan`，而非模型生成的原始文本。

## 9. 常见故障定位

| 现象 | 检查位置 | 原因/处理 |
| --- | --- | --- |
| 503 未配置模型密钥 | `.env`、`config.py` | 配置 LLM 变量后重启后端 |
| 504 规划超时 | planner init/execution 配置、下游请求 | 减少检索范围或调整合理预算；保留旧计划 |
| 422 未通过 Validator | planner review 日志、服务层错误 | 检查日期、天数、坐标、POI 证据 |
| 区县计划混入外区 | `amap_service` adcode 解析 | 确认区县请求触发 adcode 硬过滤 |
| 历史补齐很慢 | `enrich-images` 的 POI 查询 | 完整 POI 数据时跳过富化，前端可异步重试 |
| 修改后会话未更新 | `conversation_id`、token、数据库 | 确认 ChangeSet 存在且用户归属匹配 |

## 10. 练习

1. 用一个完整 `TripRequest` 调用 `/api/trip/plan`，从输入日志定位实际采用的偏好来源。
2. 去掉 LLM key，观察 503 与审查日志中的 rejected 状态。
3. 构造 `current_plan + change_set`，解释超时后为什么必须显示原计划。
4. 对比已有 `poi_id` 与缺少 `poi_id` 的 `TripPlan` 调用 `/enrich-images`，观察查询路径。
5. 检查 Validator 与路由独立校验各自负责哪些约束，并为新字段补一条测试。

## 11. 检查清单

- [ ] 日期、天数、交通和住宿字段完整，`travel_days` 位于 1–30。
- [ ] 偏好来源可追踪，且不跨用户读取会话数据。
- [ ] Agent 初始化和执行均有超时预算。
- [ ] 不把未校验的模型草稿直接返回前端。
- [ ] 定向修改只使用 ChangeSet 白名单操作。
- [ ] 规划失败或超时时保留当前计划。
- [ ] 出站计划具备真实位置数据，图片缺失可走异步补齐。
- [ ] 区分 422、500、503、504，并查看对应日志。

## 12. 继续阅读

- `backend/app/models/schemas.py`：查看 TripRequest、TripPlan 和 ChangeSet 的字段约束。
- `backend/app/services/trip_planning_service.py`：查看证据预取、排程、定向修改和后处理。
- `backend/app/agents/plan_agent.py`：查看规划 Agent 的工具注册。
- `backend/app/agents/tool_lib.py`：查看 SearchAttraction、Weather、Hotel、Restaurant 工具。
- `backend/app/services/planning_service.py`：查看 ReAct 循环与 `PlanningLoopError`。
- `backend/app/services/trip_plan_validator.py`：查看独立出站校验。
- `backend/app/api/routes/talk.py`：查看偏好如何沉淀并进入本路由。
