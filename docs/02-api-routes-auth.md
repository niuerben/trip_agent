# 02：认证路由——从账号密码到 JWT 与 OAuth

本章只看后端认证入口：`backend/app/api/routes/auth.py`。它被 `backend/app/api/main.py` 以 `/api` 前缀挂载，因此代码中的 `/login` 实际地址是 `/api/auth/login`。认证模块的职责边界很清楚：校验本地账号、与 GitHub/微信交换授权码、签发本应用 JWT。第三方 client secret 只在服务端使用。

## 1. 先建立路由地图

| 方法 | 实际路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/auth/login` | 本地登录，返回 JWT |
| `POST` | `/api/auth/register` | 向 PostgreSQL 注册本地账号并返回 JWT |
| `GET` | `/api/auth/{provider}/start` | 开始 GitHub 或微信 OAuth |
| `GET` | `/api/auth/{provider}/callback` | 接收授权码，换取资料并跳回前端 |
| `GET` | `/api/auth/me` | 当前实现是占位提示，不解析用户 |

FastAPI 的 `LoginRequest` 对用户名和密码都做了长度约束：用户名 1–100 个字符，密码 1–200 个字符。请求体例如：

```json
{"username":"alice","password":"correct-horse"}
```

## 2. 本地登录的代码流

### 场景：数据库已配置

1. `password_login()` 先检查全局 `engine`。数据库存在时，内部定义异步查询函数。
2. 查询 `app_users`，条件是 `username = :username AND provider = 'local'`，取出 `id`、显示名、头像和 PBKDF2 密码摘要。
3. 查询被 `asyncio.wait_for(..., timeout=3)` 包住。连接池或数据库响应异常时打印原因，然后转入配置账号回退路径。
4. 找到数据库用户后，`verify_password()` 拆分 `salt$digest`，使用同一个 salt 重新计算 PBKDF2-HMAC-SHA256（120,000 次），再用 `secrets.compare_digest()` 比较，避免直接比较密码明文。
5. 校验成功后组装 `{id, name, avatar}`，交给 `create_token()`。JWT payload 包含 `sub`、`name`、`avatar` 和过期时间 `exp`，算法是 HS256，密钥来自 `settings.jwt_secret`。
6. 返回：

```json
{
  "access_token":"<jwt>",
  "token_type":"bearer",
  "user":{"id":"...","name":"Alice","avatar":null}
}
```

### 场景：数据库未配置、暂时不可达或没有该用户

没有数据库引擎，或数据库查询抛出异常，代码会比较 `settings.auth_username` 与 `settings.auth_password`。默认值是 `admin` / `admin123`，生产环境应通过环境变量覆盖，并更换 `jwt_secret`。

配置账号登录成功时，用户 ID 是 `local:<username>`；数据库用户登录成功时，ID 来自 `app_users.id`。密码错误统一返回 HTTP 401 和“用户名或密码错误”，避免暴露账号是否存在。

## 3. 注册路由与密码存储

`POST /api/auth/register` 需要数据库。`engine is None` 时直接返回 503：“数据库未连接，暂时无法注册”。注册流程如下：

- 生成 `user_id = local:<username>`。
- `hash_password()` 生成 16 字节随机十六进制 salt。
- 将 PBKDF2 摘要保存为 `salt$digest`，不会保存原始密码。
- 在事务中插入 `app_users`，provider 固定为 `local`。
- 唯一约束冲突被转换为 409“用户名已存在”；其他异常转换为 500“注册失败，请稍后重试”。
- 插入成功后立即签发 JWT，所以前端不需要再登录一次。

数据库表是在应用启动时由 `backend/app/database.py:init_database()` 创建的，`app_users.username` 有唯一约束。注册请求仍复用 `LoginRequest`，因此也继承用户名和密码的长度校验。

## 4. OAuth：浏览器重定向，服务端换码

前端 `frontend/src/services/api.ts:beginOAuth()` 会生成 `/api/auth/github/start` 或 `/api/auth/wechat/start` 地址，并把当前前端 origin 放在 `redirect_uri` 查询参数中。

### 开始授权

`oauth_start(provider, redirect_uri)` 只接受 `github` 和 `wechat`：

- GitHub 未配置 `github_client_id` 时返回 503；否则重定向到 GitHub 授权页，scope 为 `read:user user:email`。
- 微信未配置 `wechat_app_id` 时返回 503；否则重定向到微信二维码登录页，scope 为 `snsapi_login`。
- 其他 provider 返回 404。

`redirect_uri` 同时作为 OAuth `state` 传递，用于回调后决定回到哪个前端地址；真正向第三方登记的回调地址来自服务端配置 `github_redirect_uri` / `wechat_redirect_uri`。

### 回调与失败点

第三方回调携带 `code` 和 `state` 后，`oauth_callback()` 使用 `httpx.AsyncClient(timeout=15)`：

- GitHub：POST `/login/oauth/access_token` 换 access token，再 GET `/user`，以 GitHub 数字 ID 生成 `github:<id>`。
- 微信：GET access_token 接口，再用 openid 请求 userinfo，以 openid 生成 `wechat:<openid>`。
- 两者都把第三方资料转换成统一的 `id/name/avatar`，随后调用 `frontend_redirect()`。

回跳 URL 形如 `http://localhost:5173/?access_token=<jwt>&user=<name>`。前端应在回调页面提取 token 并调用 `saveSession()`；`api.ts` 的请求拦截器随后会自动附加 `Authorization: Bearer <token>`。

当前代码对 OAuth HTTP 状态和返回字段没有单独的业务错误映射；第三方网络超时、错误 JSON 或缺少字段可能直接产生异常。部署时应确保 client ID、secret、回调地址完全匹配，并为生产环境补充更严格的响应检查和安全 state 校验。

## 5. JWT 在系统中的位置

认证路由负责签发 JWT，但 `/api/auth/me` 当前只返回提示：

```json
{"message":"请在客户端携带Authorization Bearer JWT后接入用户解析"}
```

真正读取 JWT 的示例在 `backend/app/api/routes/conversations.py:user_id_from_request()`：它校验 HS256 签名和过期时间，并读取 `sub`。因此，拿到 token 不等于所有路由都自动受保护；每个需要身份的路由必须显式解析它。

## 6. 练习

1. 不配置数据库，用默认配置账号调用 `/api/auth/login`，观察成功响应中的 `id`。
2. 配置 PostgreSQL 后注册同一用户名两次，比较首次的 200 与第二次的 409。
3. 修改 `jwt_expire_minutes` 为很小的值，等待过期后访问需要身份的会话接口，确认 401 行为。
4. 故意使用未知 provider 访问 `/api/auth/gitlab/start`，解释为什么是 404 而不是 503。

## 7. 检查清单

- [ ] 前端只保存 access token，不接触 GitHub/微信 secret。
- [ ] 生产环境已更换 `JWT_SECRET`、配置账号和密码。
- [ ] 登录失败统一为 401，注册冲突为 409，数据库不可用为 503。
- [ ] OAuth 回调地址与第三方控制台配置一致。
- [ ] 需要用户隔离的业务路由确实校验 JWT 的 `sub`。
- [ ] 生产环境对 OAuth `state` 做不可猜测且可验证的绑定。

## 8. 继续阅读

- `backend/app/api/main.py`：查看认证路由如何挂载到 `/api`。
- `backend/app/database.py`：查看 `app_users` 表结构和启动初始化。
- `backend/app/api/routes/conversations.py`：查看 JWT 如何转换为业务用户 ID。
- `frontend/src/services/api.ts`：查看登录、OAuth 回跳和请求拦截器。
- `backend/app/config.py`：查看 JWT、OAuth 和数据库环境变量默认值。
