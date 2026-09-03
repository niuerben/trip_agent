# 01：API 入口初始化——FastAPI 怎样把应用启动起来

本章从 `backend/app/api/main.py` 开始。假设你在开发环境执行 `python run.py`，浏览器访问 `http://localhost:8000/docs`：这两个动作背后都要经过同一个 FastAPI 应用对象。阅读完本章，你应能回答三个问题：应用对象在哪里创建，路由为什么实际带有 `/api`，启动时哪些外部依赖会被检查或预热。

## 1. 入口文件做了什么

`main.py` 可以按四个阶段阅读：

1. 配置标准输出编码，减少 Windows 控制台打印中文时的乱码。
2. 读取配置并创建 `FastAPI` 实例。
3. 加入 CORS 中间件并挂载各业务路由。
4. 定义启动、关闭、根路径和健康检查处理函数。

核心代码可以压缩成下面的结构：

```python
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="行旅天下 - 基于HelloAgents框架的智能旅行规划助手API",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trip.router, prefix="/api")
app.include_router(poi.router, prefix="/api")
# 其他业务路由同样挂载
```

这里有两层路径前缀。`poi.py` 中的 router 声明 `APIRouter(prefix="/poi")`，main 再加上 `/api`，因此 `@router.get("/search")` 的完整地址是 `/api/poi/search`。Swagger 文档显示的也是完整地址。

## 2. 场景：前端 5173 端口访问后端 8000

开发时，Vue 通常运行在 `http://localhost:5173`，FastAPI 运行在 `http://localhost:8000`。端口不同就属于跨源请求。`settings.get_cors_origins_list()` 会把配置中的逗号分隔字符串变成列表，默认包含：

- `http://localhost:5173`
- `http://localhost:3000`
- `http://127.0.0.1:5173`
- `http://127.0.0.1:3000`

`allow_credentials=True` 允许浏览器携带凭据；`allow_methods` 和 `allow_headers` 当前全部放开，便于开发阶段调用登录、规划和 POI 接口。生产部署应把 origin、方法和请求头收窄到实际需要的集合。

一次浏览器调用大致经过：

```text
Vue 页面
  -> axios http://localhost:8000/api/poi/search
  -> CORS 中间件处理跨源请求
  -> /api 前缀匹配 poi.router
  -> /poi/search 匹配 search_poi()
  -> JSON 响应返回浏览器
```

若是带有自定义请求头的跨源请求，浏览器可能先发送 `OPTIONS` 预检。CORS 中间件负责这个预检，业务函数通常不会看到它。

## 3. 启动事件：先验证，再初始化，再预热 Chroma

应用启动时执行 `startup_event()`：

```python
@app.on_event("startup")
async def startup_event():
    print_config()
    validate_config()
    await init_database()

    chroma_store = await asyncio.to_thread(get_poi_vector_store)
    if chroma_store is not None:
        print("Chroma 启动预热完成")
    else:
        print("Chroma 启动预热失败；后续使用 REST/MCP 降级链路")
```

可以把它理解成开门前的检查清单：

- `print_config()` 打印应用、端口、LLM 和密钥“是否已配置”等信息，不打印密钥原文。
- `validate_config()` 对高德和 LLM 配置缺失打印警告。目前这些缺失项是警告；函数中的 `errors` 为空时不会阻止启动。
- `init_database()` 在有 `DATABASE_URL` 时创建 PostgreSQL 基础表；没有配置时打印提示并跳过。
- `get_poi_vector_store()` 可能初始化 Chroma PersistentClient。它放进 `asyncio.to_thread()`，避免同步初始化工作直接占住事件循环。Chroma 不可用时返回 `None`，后续请求仍可以走高德 REST/MCP 路径。

启动函数中的异常会让应用启动失败。例如 `validate_config()` 将来发现致命配置并抛出 `ValueError`，Uvicorn 不会把一个未完成初始化的服务当作可用服务。

## 4. 三个基础地址

### 根路径 `/`

```json
{
  "name": "行旅天下",
  "version": "1.0.0",
  "status": "running",
  "docs": "/docs",
  "redoc": "/redoc"
}
```

它适合人工快速确认服务是否已经响应。

### 健康检查 `/health`

返回应用信息和数据库状态：

```json
{
  "status": "healthy",
  "service": "行旅天下",
  "version": "1.0.0",
  "database": "connected"
}
```

`database_health()` 会执行 `SELECT 1`。数据库未配置、连接失败时，字段值是 `not_configured_or_unavailable`。注意：这个接口的整体 `status` 仍是 `healthy`，调用方需要同时读取 `database` 字段。

### OpenAPI 文档 `/docs` 与 `/redoc`

FastAPI 根据路由装饰器、Pydantic 模型、`summary` 和 `description` 自动生成文档。新增一个路由后，只要它被 `include_router()` 挂载，就会出现在 OpenAPI 页面中。

## 5. 关闭事件与运行方式

`shutdown_event()` 当前只打印关闭日志，没有主动关闭数据库引擎或其他资源。需要引入连接池关闭逻辑时，应在这里或新的生命周期管理方案中统一处理，避免把清理代码散落在各路由里。

文件底部的 `__main__` 分支允许直接执行模块：

```python
uvicorn.run(
    "app.api.main:app",
    host=settings.host,
    port=settings.port,
    reload=True,
)
```

项目通常从 `run.py` 启动；Uvicorn 的导入字符串仍然指向 `app.api.main:app`。`reload=True` 适合开发，生产环境应使用明确的进程管理和关闭策略。

## 6. 常见故障定位

| 现象 | 检查位置 | 常见原因 |
| --- | --- | --- |
| 访问 `/api/poi/search` 返回 404 | `main.py`、`poi.py` | 忘记考虑两个前缀，或 router 没有 include |
| 浏览器报 CORS 错误 | `CORS_ORIGINS`、浏览器 Network | 前端 origin 不在允许列表，或预检请求配置不匹配 |
| 服务启动即退出 | 启动日志、`validate_config()` | 致命配置异常、数据库初始化异常或导入依赖失败 |
| 首次请求很慢 | Chroma 启动日志 | 预热失败后发生懒加载，或本地向量库初始化耗时 |
| `/health` 显示数据库不可用 | `DATABASE_URL`、数据库连接 | 未配置连接串、连接池无法执行 `SELECT 1` |
| 控制台中文乱码 | `sys.stdout.reconfigure`、终端编码 | 启动方式没有保留 UTF-8 输出设置 |

## 7. 练习

1. 打开 `/docs`，找到 POI、地图和旅行规划路由，写出它们由哪两个前缀拼成完整路径。
2. 将 `CORS_ORIGINS` 临时改为只允许 `http://localhost:5173`，从另一个端口发请求，观察浏览器预检结果。
3. 在没有 `DATABASE_URL` 的环境访问 `/health`，解释为什么 HTTP 仍可能是 200，但 `database` 不是 `connected`。
4. 暂时让 Chroma 初始化失败，观察启动日志，并说明为什么服务仍能保留高德 REST/MCP 降级链路。

## 8. 检查清单

- [ ] 清楚区分 router 自身前缀与 `include_router()` 的全局前缀。
- [ ] 开发前端 origin 已加入 CORS 配置。
- [ ] 启动日志中能看到配置警告、数据库状态和 Chroma 预热结果。
- [ ] 生产环境没有直接使用 `reload=True`。
- [ ] 监控同时检查 `/health` 的总体状态和 `database` 字段。
- [ ] 新路由已通过 `app.include_router()` 注册并能在 `/docs` 中看到。

## 9. 继续阅读

- `backend/app/api/routes/poi.py`：学习 POI 查询、线程卸载和错误映射。
- `backend/app/api/routes/trip.py`：查看规划请求的超时边界。
- `backend/app/config.py`：查看环境变量、CORS 和 Chroma 配置默认值。
- `backend/app/database.py`：查看启动时创建的表与健康检查。
- `backend/app/services/poi_vector_store.py`：查看 Chroma 初始化、过滤和距离阈值。
