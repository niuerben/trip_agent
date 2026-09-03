# 测试指南

本目录包含正式单元测试、隔离集成测试、真实服务验收脚本和浏览器端到端脚本。默认测试应可重复运行，不需要启动后端、前端、数据库、LLM 或高德服务；真实服务测试只在人工或受保护的夜间任务中运行。

## 测试分层

单元测试验证纯函数、领域规则和服务适配器，外部依赖通过 mock、fake 或临时目录隔离。集成测试验证多个 Agent 或服务之间的组合；本机 API、真实 LLM、高德和 Playwright 脚本属于手动验收，不纳入普通 Pull Request 门禁。

| 类别 | 路径 | 默认执行 | 说明 |
| --- | --- | --- | --- |
| 正式单元测试 | `test/unit/` | 是 | 无网络、无真实服务，适合本地开发和 CI |
| 隔离集成测试 | `test/integration/test_agent_pipeline.py` | 是 | 使用 fake 依赖验证对话到规划的组合 |
| 真实 LLM 验收 | `test/integration/test_plan_agent_real.py` | 否 | 显式设置 `RUN_REAL_SERVICE_TESTS=1` 后运行 |
| 本机 API 诊断 | `test/integration/test_api.py` | 否 | 访问运行中的后端、数据库、高德和模型服务 |
| Chroma 诊断 | `test/integration/test_chroma_hit.py` | 否 | 观察本机服务或本地 Chroma 的检索结果 |
| 浏览器 E2E | `test/e2e/` | 否 | 需要前后端、数据库、账号和真实外部服务 |

## 默认测试

默认测试使用 mock、fake、临时目录或进程内对象验证业务行为，不应访问真实网络或写入仓库中的运行结果。推荐从仓库根目录执行以下两个入口，真实服务测试会在未开启门控时跳过。

```powershell
python -m unittest discover -s test/unit -p "test_*.py" -v
python -m unittest discover -s test/integration -p "test_*.py" -v
```

单独运行重点测试：

```powershell
python -m unittest test.unit.test_planning_service_react -v
python -m unittest test.unit.test_talk_agent_replan -v
python -m unittest test.unit.test_guest_trip_access -v
python -m unittest test.integration.test_agent_pipeline -v
```

## 单元测试覆盖

单元测试覆盖高德城市范围、路线几何、日期天气、JWT 认证边界、异步线程调用、Agent 契约和循环日志。规划侧覆盖 Chroma POI 检索、证据预取、确定性近邻排程、ReAct 校验、定向修改、路线排序和审查日志。

以下 16 个测试文件是当前应保留的正式单元测试：

- `test_amap_service_city_scope.py`：行政区 geocode、adcode 与城市范围
- `test_amap_service_route_geometry.py`：驾车、步行、公交和地铁几何解析
- `test_date_sync_fallback.py`：对话确认改期后的日期 ChangeSet
- `test_guest_trip_access.py`：规划接口无效/有效 JWT 边界
- `test_map_poi_routes_async_threading.py`：地图、POI 和规划路由的异步调用
- `test_observable_function_call_agent_logging.py`：Agent 循环事件和日志
- `test_plan_agent_contract.py`：Plan、Search、Talk Agent 的接口契约
- `test_planning_service_evidence_plan.py`：POI 证据和确定性排程
- `test_planning_service_react.py`：ReAct 规划、校验、降级和日志
- `test_poi_vector_store.py`：Chroma POI 存储、检索和过滤
- `test_talk_agent_replan.py`：对话意图和 ChangeSet 解析
- `test_test_gates.py`：真实服务门控和测试产物路径
- `test_trip_planner_agent_directed_replan.py`：定向重规划操作执行
- `test_trip_planner_agent_route_ordering.py`：景点和餐饮近邻排序
- `test_trip_planner_agent_weather_dates.py`：旅行日期和天气窗口
- `test_trip_routes_review_logging.py`：规划交付审查日志

## 集成测试覆盖

隔离集成测试验证 Talk Agent 产生的 ChangeSet 能被规划 Agent 消费，并验证规划 Agent 的 ReAct 结果经过校验后交付。该层仍使用 fake LLM、fake 高德和 mock 校验器，不要求启动本机服务。

正式隔离集成入口是：

```powershell
python -m unittest test.integration.test_agent_pipeline -v
```

`test/integration/test_agent_layer_openness.py` 是基于源码检查的架构探针，当前不属于核心行为测试。它可以暂时保留用于迁移期间的架构回归，但后续应改成稳定的接口契约测试，或移到独立的 architecture/checks 入口。

## 真实 LLM 与高德验收

真实验收用于确认模型提示词、工具调用和高德数据在真实环境中的表现，不能替代确定性的单元测试。它可能产生费用、受到限流和外部数据变化影响，因此必须人工确认配置后显式运行。

当前真实规划验收由 `RUN_REAL_SERVICE_TESTS` 控制，结果默认写入被 Git 忽略的 `test-artifacts/plan_agent_real/`，也可以通过 `TEST_ARTIFACT_DIR` 指定根目录：

```powershell
$env:RUN_REAL_SERVICE_TESTS = "1"
python -m unittest test.integration.test_plan_agent_real -v
```

执行结束后清理环境变量：

```powershell
Remove-Item Env:RUN_REAL_SERVICE_TESTS
```

缺少密钥或真实调用失败不能当作测试通过。不要把真实模型响应、用户行程、POI 联系方式或完整提示词提交到 `test/integration/results/`；这些内容应作为本地 artifact 或去敏后的固定夹具保存。

## 本机 API 诊断

`test/integration/test_api.py` 是手动诊断脚本，不是默认集成测试，它会访问运行中的后端并检查登录、会话、数据库、高德 REST 和模型接口。当前脚本没有读取 `RUN_REAL_SERVICE_TESTS`，设置该变量不会自动阻止或允许它运行，执行前必须由操作者自行确认风险。

### 前置条件

- 已配置 `backend/.env`，至少包含可用的 `AMAP_API_KEY`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL_ID` 和 `JWT_SECRET`。
- 如需检查注册、会话和聊天记录，还要配置可访问的 `DATABASE_URL`。
- 后端已启动：

```powershell
cd backend
.\venv\Scripts\Activate.ps1
python run.py
```

从仓库根目录运行脚本：

```powershell
python test/integration/test_api.py
```

`--skip-trip` 只跳过旅行规划请求，不会跳过登录、数据库、高德或模型检查。后续应为该脚本增加真实服务门控，或将它迁移到 `scripts/diagnostics/`。

## Chroma 诊断

`test/integration/test_chroma_hit.py` 用于观察 Chroma 检索命中和候选质量，不是带稳定断言的正式测试。它当前没有自动门控，默认不会被 unittest 收集，运行前应确保后端或本地 Chroma 已准备好。

访问运行中的后端：

```powershell
python test/integration/test_chroma_hit.py --city 深圳 --query 景点
```

直接访问本地 Chroma：

```powershell
python test/integration/test_chroma_hit.py --direct --city 深圳 --query 景点
```

该脚本后续可迁移到 `scripts/diagnostics/`，并明确未命中时的退出码和诊断含义。

## Playwright 端到端测试

单城市 E2E 验证用户从登录、填写表单到查看和调整行程的完整浏览器流程，覆盖页面跳转、路线节点、删除操作和结果展示。它依赖 Microsoft Edge、前端 `5173` 端口、后端 `8000` 端口、数据库、测试账号、LLM 和高德服务，当前脚本没有实际读取 `RUN_REAL_SERVICE_TESTS`。

### 前置条件

1. 安装 Playwright 浏览器：

```powershell
python -m playwright install
```

2. 启动后端：

```powershell
cd backend
.\venv\Scripts\Activate.ps1
python run.py
```

3. 另开终端启动前端：

```powershell
cd frontend
npm install
npm run dev
```

4. 从仓库根目录运行：

```powershell
python test/e2e/test_trip_planner.py --city 广州 --preferences 美食 自然风光 --headless
```

脚本会写入截图和测试日志，并可能读取后端日志。后续应增加真实服务门控、可配置服务地址和临时测试账号，避免固定账号、端口和共享日志造成误报。

## 多城市 E2E 回归

多城市脚本复用单城市 E2E 流程，当前默认覆盖北京、上海、广州、深圳和杭州，适合发布前验收或 nightly 回归。它会重复调用真实 LLM 和高德服务，耗时、费用和限流风险都高于单城市测试。

当前脚本支持命令行筛选城市，但不读取 `RUN_REAL_SERVICE_TESTS` 或 `RUN_MULTI_CITY_E2E`；后者目前只是文档约定：

```powershell
python test/e2e/test_major_cities.py --headless
python test/e2e/test_major_cities.py --headless --cities 广州 深圳
```

后续实现门控后，推荐要求同时设置：

```powershell
$env:RUN_REAL_SERVICE_TESTS = "1"
$env:RUN_MULTI_CITY_E2E = "1"
python test/e2e/test_major_cities.py --headless
```

## 测试文件状态

测试源码、测试基础设施、诊断脚本和运行产物需要分开管理，不能因为文件名包含 `test` 就全部放进默认测试入口。以下状态用于后续清理，当前只做记录，不在本轮删除文件。

### 保留为正式测试或基础设施

- `test/unit/` 下列出的 16 个正式单元测试
- `test/integration/test_agent_pipeline.py`
- `test/integration/test_plan_agent_real.py`，作为显式真实 LLM 验收
- `test/e2e/test_trip_planner.py` 和 `test/e2e/test_major_cities.py`，作为手动/夜间 E2E 入口
- `test/_gates.py`、`test/_output.py`
- `test/__init__.py`、`test/unit/__init__.py`、`test/integration/__init__.py`、`test/e2e/__init__.py`

### 暂不删除，后续迁移或重构评估

- `test/integration/test_api.py`：迁移到 `scripts/diagnostics/` 或补充真实服务门控
- `test/integration/test_chroma_hit.py`：迁移到 `scripts/diagnostics/` 或补充真实服务门控
- `test/integration/test_agent_layer_openness.py`：改成稳定架构契约或移出默认集成层
- `test/requirements.txt`：补齐测试依赖，或拆分为 unit/integration/e2e/live 依赖文件

### 运行产物，不作为测试源码

- `test/integration/results/`
- `test/unit/results/`
- `test-artifacts/`
- `test/**/__pycache__/` 和 `*.pyc`
- `test/**/*.png`、`test/logs/`、`backend/logs/`

结果目录中的文件可能包含旧基线或真实响应，清理前必须搜索引用并确认不再用于回归对照。当前已有的未提交结果文件不能在清理过程中被覆盖或删除。

## 验证命令

文档变更和测试清理前，先验证路径、默认入口和门控行为；这些命令不需要真实 LLM 或高德密钥。真实服务和 Playwright 命令只在相应前置条件满足时执行，不作为普通 PR 的必需验证。

```powershell
python -m unittest discover -s test/unit -p "test_*.py" -v
python -m unittest discover -s test/integration -p "test_*.py" -v
python -m unittest test.unit.test_test_gates test.unit.test_guest_trip_access -v
git diff --check
```

还应使用实际目录清单核对 README 中的文件名，并确认未设置 `RUN_REAL_SERVICE_TESTS` 时真实 LLM 测试显示 skipped、`test/integration/results/` 没有新增或修改。

## 后续清理顺序

清理应分阶段进行，每一阶段都先搜索引用、运行相关测试并查看 Git 状态。任何结果文件、诊断脚本或架构探针都不能只凭文件名直接删除。

1. 清理 `__pycache__`、`.pyc`、截图和明确无引用的日志。
2. 确认 `results/` 是否仍是历史基线；若不是，迁移到 `test-artifacts/` 后再删除旧产物。
3. 为 API/Chroma 诊断脚本补门控或迁移到 `scripts/diagnostics/`。
4. 将架构源码探针改成行为或接口契约测试。
5. 最后再评估重复或过时测试，并运行完整默认测试入口。

## 风险与注意事项

真实 LLM、高德、数据库和浏览器测试都可能受凭据、网络、限流、外部数据和本机端口影响，失败不一定代表业务代码回归。测试日志和结果可能包含用户输入、模型响应、POI 地址或联系方式，默认应写入被 Git 忽略的目录并在共享前去敏。

固定账号、固定端口、Microsoft Edge channel 和后台同步线程会降低 E2E 的可重复性；真实测试应使用临时账号、可配置 URL、独立 artifact 目录和明确超时。普通 Pull Request 只应阻断正式 unit 和隔离 integration，真实服务与多城市 E2E 应通过手动触发或 nightly 工作流运行。
