# 06：对话路由——让偏好沉淀为可执行的行程语义

本章阅读 `backend/app/api/routes/talk.py`。场景是这样的：用户已经生成了一份广州行程，在聊天框说“我喜欢慢节奏，也想多看博物馆，第二天不要爬山”。对话接口要完成三件事：理解这一轮话、保留会话上下文、把可执行的修改意图交给 `/api/trip/plan`。

## 1. 路由地图

`main.py` 将路由挂载到 `/api`，模块声明 `prefix="/talk"`，因此有三条完整路径：

| 方法 | 完整路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/talk` | 处理一轮偏好对话 |
| `GET` | `/api/talk/{conversation_id}` | 读取当前用户的聊天历史 |
| `POST` | `/api/talk/suggestions` | 恢复会话 Top3 建议，不写聊天记录 |

请求和响应模型集中在 `schemas.py` 的 `TalkRequest`、`TalkResponse`、`ChatMessage` 及建议模型中。

## 2. 一轮对话的请求

```http
POST /api/talk
Content-Type: application/json
Authorization: Bearer <token>

{
  "conversation_id": "conv-gz-001",
  "city": "广州",
  "plan_context": "第1天陈家祠和上下九；第2天白云山",
  "message": "第二天不要爬山，换成博物馆，整体节奏慢一点"
}
```

`messages` 可以携带前端历史；有 `conversation_id` 且数据库可用时，服务端优先读取数据库历史。`city` 用于消解“那个大学”“附近的公园”等地点表达，`plan_context` 则帮助 Agent 理解当前行程。

## 3. 请求处理流水线

### 3.1 确定用户与上下文

路由先通过 `user_id_from_request()` 从 Bearer token 得到用户身份，没有 token 时使用访客身份。若会话 ID 和数据库都存在，会调用 `ensure_user()`，再读取 `chat_messages` 与 `conversation_preferences`。SQL 使用参数绑定，并按 `created_at ASC, id ASC` 排序。

数据库不可用或读取失败时不会让聊天接口直接崩溃：路由记录日志，退回 `request.messages`。这让本地无数据库开发仍可测试对话，但此时历史不会跨请求自动保存。

### 3.2 调用 Talk Agent

路由重新组装一个 `TalkRequest`，把服务端读到的长期偏好放进去，然后在线程中初始化并调用 Agent：

```python
agent = await asyncio.wait_for(
    asyncio.to_thread(get_talk_agent),
    timeout=settings.planner_init_timeout_seconds,
)
result = await asyncio.wait_for(
    asyncio.to_thread(agent.chat, agent_request),
    timeout=settings.planner_execution_timeout_seconds,
)
```

Agent 的结果包含 `reply`、`intent`、`change_request`、`change_set`、`top_suggestions`、`preference` 和 `done`。`intent` 通常是 `chat` 或 `replan`。例如上面的输入可能产生 `intent="replan"`，并返回一个由白名单操作组成的 ChangeSet，而不是让模型直接写 SQL 或任意修改数据库。

### 3.3 持久化本轮消息与偏好

Agent 完成后，路由将用户消息和助手回复一起写入 `chat_messages`，随后重新读取完整历史作为响应。若 Agent 提炼出了非空 `Preference.prompt`，则写入 `conversation_preferences`；同一会话使用 `ON CONFLICT` 更新已有偏好。

持久化失败只打印日志，不影响当前响应。这是有意的可用性选择：聊天回复先到达用户，数据库问题可以在监控中处理。

## 4. 响应结构

成功响应示例：

```json
{
  "success": true,
  "reply": "好的，我会把第二天调整为轻松的博物馆路线。",
  "intent": "replan",
  "change_request": "第二天改为博物馆，整体节奏放慢",
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
  "top_suggestions": ["增加本地美食", "减少景点数量", "查看交通建议"],
  "preference": {"prompt": "偏好慢节奏、博物馆和历史文化"},
  "done": true,
  "messages": []
}
```

`change_set` 是后续规划的结构化桥梁；`change_request` 保留自然语言，便于日志和展示。`messages` 只有在数据库持久化成功时才会带回聊天记录。

## 5. Agent 不可用时的安全兜底

初始化、调用超时或其他异常都会进入统一兜底分支：

```python
reply = "好的，我已经记下你的偏好啦，可以直接开始规划行程～"
preference = Preference(prompt=(request.message or "").strip())
intent = "chat"
change_request = None
change_set = None
```

接口仍返回 `TalkResponse(success=True)`，但不会假装已经完成重规划。客户端应依据 `intent` 和 `change_set` 决定是否调用 `/api/trip/plan`；没有 ChangeSet 时不要自动覆盖当前计划。

## 6. 历史与 Top3 建议

获取历史：

```http
GET /api/talk/conv-gz-001
```

返回 `ChatHistoryResponse`，消息中的时间通过 `as_beijing()` 转为北京时间。未配置数据库时返回空列表，读取异常也返回空列表，避免刷新页面被历史接口拖垮。

恢复建议：

```http
POST /api/talk/suggestions
Content-Type: application/json

{
  "conversation_id": "conv-gz-001",
  "city": "广州",
  "plan_context": "当前行程摘要"
}
```

该接口读取历史和偏好，调用 `agent.generate_suggestions()`，返回 `top_suggestions`，不插入聊天记录。失败时返回 `success=false` 和空数组，前端可隐藏建议卡片。

## 7. 端到端流程与设计取舍

```text
前端输入
  -> POST /api/talk
  -> token 解析用户
  -> 读取 chat_messages / conversation_preferences
  -> 组装 TalkRequest
  -> 线程执行 Talk Agent（超时保护）
  -> reply + intent + ChangeSet + Preference
  -> 写入消息和偏好（失败可忽略）
  -> TalkResponse
  -> 若 intent=replan 且有 change_set，再请求 /api/trip/plan
```

路由保持异步边界，Agent 和数据库分别处理各自职责；模型只产出语义与白名单变更，计划的真实 POI 查询、执行和最终校验留在旅行规划服务。这样对话理解失败不会直接破坏现有计划，数据库暂时不可用也不妨碍用户继续交流。

## 8. 常见故障定位

| 现象 | 检查位置 | 处理建议 |
| --- | --- | --- |
| 返回兜底回复 | LLM 配置、Agent 初始化、超时日志 | 检查 key、模型地址与执行预算 |
| 历史为空 | `DATABASE_URL`、会话 ID、用户 token | 确认会话属于当前用户；无数据库时这是预期行为 |
| 有回复但未触发行程修改 | `intent`、`change_set` | 前端仅在结构化变更存在时提交重规划 |
| 建议恢复失败 | Agent 初始化和会话表 | 隐藏建议区域并允许用户继续输入 |
| 消息写入失败但响应成功 | 数据库连接/表结构 | 查看日志；不要重复插入同一轮消息 |

## 9. 练习

1. 只发送 `message`，比较无数据库时 `messages` 和 `preference` 的结果。
2. 构造一个 `intent=replan` 的回复，追踪 ChangeSet 如何传到 `TripRequest`。
3. 说明为什么 `/suggestions` 不应写入 `chat_messages`。
4. 为历史接口增加分页参数，保持时间升序和用户隔离。
5. 设计 Agent 超时后的前端提示，确保当前行程仍可继续使用。

## 10. 检查清单

- [ ] 请求携带正确的 `conversation_id` 和当前城市/计划摘要。
- [ ] 客户端区分自然聊天与 `replan` 意图。
- [ ] 只有存在合法 ChangeSet 时才触发行程修改。
- [ ] 不把模型输出当作 SQL 或直接数据库指令执行。
- [ ] 处理数据库未配置、Agent 超时和建议为空的情况。
- [ ] token 用户只能读取和写入自己的会话消息。

## 11. 继续阅读

- `backend/app/agents/talk_agent.py`：查看对话语义提炼与建议生成。
- `backend/app/models/schemas.py`：查看 Talk 与 ChangeSet 的字段约束。
- `backend/app/api/routes/conversations.py`：查看会话归属和用户身份工具。
- `backend/app/api/routes/trip.py`：查看偏好读取及 ChangeSet 进入规划的入口。
- `backend/app/services/trip_planning_service.py`：查看白名单变更的执行与验证。
