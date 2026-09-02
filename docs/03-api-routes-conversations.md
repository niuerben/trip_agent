# 03：会话路由——让旅行计划跨页面保存

本章阅读 `backend/app/api/routes/conversations.py`，并结合前端 `frontend/src/services/conversations.ts`。会话接口保存的是一条旅行计划快照：标题、来源 provider、计划 JSON 和创建/更新时间。路由通过 `main.py` 挂载后，实际前缀为 `/api/conversations`。

## 1. 路由地图

| 方法 | 实际路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/conversations` | 读取当前用户的会话，按更新时间倒序 |
| `POST` | `/api/conversations` | 新建或覆盖一条会话 |
| `DELETE` | `/api/conversations/{conversation_id}` | 删除当前用户拥有的会话 |

请求和响应里的字段使用前端约定的 camelCase：`createdAt`、`updatedAt`。数据库字段使用 snake_case：`created_at`、`updated_at`。路由负责两种命名之间的转换。

## 2. 身份解析：Bearer JWT 或 guest

每个处理函数都先调用 `user_id_from_request(request)`：

1. 读取 `Authorization` 请求头。
2. 只有以 `Bearer ` 开头时才尝试 JWT 解码。
3. 使用配置中的 `settings.jwt_secret`、HS256 算法校验签名和 `exp` 过期时间。
4. 取 payload 的 `sub` 作为数据库 `user_id`。
5. JWT 缺少 `sub` 返回 401“JWT 缺少用户身份”；签名错误、格式错误或已过期返回 401“JWT 无效或已过期”。
6. 没有 Authorization 头时使用 `local:guest`。

“guest”是无 token 的本地降级身份，不代表绕过数据库：后续 `ensure_user()` 仍会尝试确保 `local:guest` 存在。

前端 `api.ts` 的请求拦截器会自动把 localStorage 中的 `trip_planner_access_token` 加成 Bearer 头。响应收到 401 时，拦截器调用 `clearSession()`，清除 token 和本地用户信息。

## 3. 数据库表与 ensure_user

`backend/app/database.py:init_database()` 创建两张本章直接使用的表：

- `app_users`：`id` 主键、`username` 唯一、显示名、provider、头像。
- `conversations`：`id` 主键，`user_id` 外键引用 `app_users(id)`，计划放在 `payload JSONB`，并有创建/更新时间。

`ensure_user(user_id)` 是会话接口的前置步骤：

```sql
INSERT INTO app_users (id, username, display_name)
VALUES (:id, :username, :display_name)
ON CONFLICT (id) DO NOTHING
```

这样 OAuth 用户第一次保存会话时，即使尚未在 `app_users` 中有本地资料，也能满足外键约束。`engine is None` 时直接返回 503“DATABASE_URL未配置”。

## 4. 查询会话：GET

调用 `GET /api/conversations` 时，代码流为：

1. 从 JWT 得到 user ID，或使用 `local:guest`。
2. `ensure_user()` 确保用户行存在。
3. 只查询 `WHERE user_id = :user_id` 的记录，并按 `updated_at DESC` 排序。
4. 将每行映射成前端对象：`row.payload` 变成 `plan`，数据库时间经过 `as_beijing()` 变成带 `+08:00` 的 ISO 字符串。

`as_beijing()` 对无时区 datetime 按 UTC 解释；有时区值则转换到 `Asia/Shanghai`。因此页面可以稳定显示北京时间，不依赖数据库连接的本地时区。

### 场景：Alice 看不到 Bob 的计划

即使 Alice 猜中了 Bob 的会话 ID，列表查询也不会返回 Bob 的数据，因为筛选条件包含当前请求解析出的 `user_id`。用户隔离在 SQL 层完成，不依赖前端隐藏列表。

## 5. 保存会话：POST

`ConversationPayload` 要求：

```json
{
  "id":"conversation_1720000000000_ab12cd",
  "title":"广州 · 3天旅行计划",
  "provider":"local",
  "plan":{"city":"广州","days":[]},
  "createdAt":"2026-08-31T09:00:00+08:00",
  "updatedAt":"2026-08-31T09:10:00+08:00"
}
```

`id` 最长 100，`title` 最长 255，`provider` 最长 30，`plan` 必须是 JSON object。代码先解析两个客户端时间：

- `Z` 会替换成 `+00:00` 后交给 `datetime.fromisoformat()`。
- 没有时区的时间按北京时间补齐。

接着在事务中执行 PostgreSQL upsert：

- 新 ID：插入用户、标题、provider、JSONB 计划和时间。
- 已有 ID：更新标题、provider、payload 和 `updated_at`。
- `user_id` 来自请求身份，不从客户端 payload 接收，所以客户端不能通过请求体声明另一个拥有者。

成功响应是 `{"success":true,"id":"..."}`。前端创建或更新本地记录后，会异步调用 `persistConversation()` POST；POST 失败时保留 localStorage，页面继续可用。

## 6. 删除会话：DELETE

`DELETE /api/conversations/{conversation_id}` 的流程：

1. 没有数据库连接时返回 503。
2. 重新解析请求身份。
3. 执行：

```sql
DELETE FROM conversations
WHERE id = :id AND user_id = :user_id
```

因此删除动作同时绑定会话 ID 和当前用户 ID。即使 ID 存在但属于别人，SQL 也不会删除它；当前实现仍返回 `success: true`，没有区分“未找到”和“已删除”。前端在后端 DELETE 成功后才调用 `removeConversation()` 清除本地记录。

## 7. 本地优先与远端同步

`frontend/src/services/conversations.ts` 采用本地优先策略：

- `createConversation()` / `updateConversation()` 先写按用户命名空间隔离的 localStorage，再异步 POST。
- `deleteConversation()` 先请求后端，成功后删除本地记录。
- `syncConversations()` GET 远端列表成功后，用远端数据覆盖当前用户的本地列表；失败则静默保留本地数据。
- 用户命名空间来自本地用户的 `id`，没有用户时使用 `guest`，并对 key 做 URL 编码。
- 页面刷新或多标签页变化通过自定义事件和 `storage` 事件通知订阅者。

这个设计适合后端暂时离线的开发场景，但异步 POST 失败不会自动重试，也没有冲突合并策略。需要强一致时应增加同步状态、重试队列或服务端版本号。

## 8. 常见故障定位

| 现象 | 先看哪里 | 原因/处理 |
| --- | --- | --- |
| GET/POST 返回 503 | `database.py`、环境变量 | `DATABASE_URL` 未配置，或启动时未建立 engine |
| 返回 401 | 请求头、JWT secret、过期时间 | token 缺失/无效；前端会清理本地登录状态 |
| POST 返回 422 | `ConversationPayload` | 缺少字段、字符串超长、`plan` 不是对象或时间格式非法 |
| POST 返回 500 | 数据库日志、payload 内容 | JSONB 转换、外键或数据库连接失败 |
| 页面有记录，刷新后远端为空 | `persistConversation()` 和网络请求 | 本地写入成功但异步保存失败；当前策略不会阻塞页面 |
| 删除后又出现 | `syncConversations()` 或其他标签页 | 本地/远端同步时序造成旧数据覆盖，需要检查请求顺序 |

## 9. 练习

1. 不带 token 请求 GET，追踪 `local:guest` 如何进入 `app_users` 并查询会话。
2. 用 Alice 的 token POST 一条记录，再用 Bob 的 token GET，验证列表隔离。
3. 用同一个 `id` 修改 title 和 plan，观察 upsert 后 `updated_at` 的变化。
4. 提交 `createdAt: "2026-08-31T09:00:00"` 与带 `+08:00` 的版本，确认无时区输入会按北京时间解析。
5. 用属于 Bob 的 ID 执行 Alice 的 DELETE，解释为什么数据库不会删除，但响应仍为 success。

## 10. 检查清单

- [ ] 客户端请求使用 Bearer JWT，且 JWT 的 `sub` 是稳定用户 ID。
- [ ] 查询、更新、删除都包含当前用户身份约束。
- [ ] `DATABASE_URL` 未配置时，调用方能处理 503。
- [ ] 计划 JSON 可被 JSONB 接收，时间字符串包含明确时区更稳妥。
- [ ] 前端已接受后端离线时 localStorage 的降级行为。
- [ ] 需要强一致的产品已设计失败重试与同步冲突处理。
- [ ] 日志中不记录 token、密码或 OAuth secret。

## 11. 继续阅读

- `backend/app/api/main.py`：查看路由前缀和 CORS 配置。
- `backend/app/database.py`：查看外键、JSONB 与级联删除表结构。
- `backend/app/api/routes/auth.py`：查看 JWT 的签发方式和 payload。
- `frontend/src/services/conversations.ts`：查看本地优先、同步和事件通知。
- `frontend/src/services/api.ts`：查看 Authorization 拦截器与 401 清理。
- `backend/app/api/routes/talk.py`：查看聊天历史如何与会话身份关联。
