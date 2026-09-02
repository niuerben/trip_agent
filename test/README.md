# 测试指南

本目录包含可重复执行的单元/集成测试，以及需要本机服务或真实第三方依赖的手动验收测试。

## 测试分层

| 类别 | 目录或脚本 | 是否依赖真实服务 | 适用场景 |
| --- | --- | --- | --- |
| 单元测试 | `test/unit/` | 否 | 默认本地开发与 CI |
| 集成测试 | `test/integration/` | 以具体脚本说明为准 | 服务层、路由与 Agent 组合验证 |
| 本机 API 验收 | `test/integration/test_api.py` | 是 | 手动检查后端、数据库、高德与模型配置 |
| Chroma 诊断 | `test/integration/test_chroma_hit.py` | 是 | 手动观察 Chroma 检索命中 |
| 浏览器 E2E | `test/e2e/` | 是 | 手动或夜间回归 |

> 默认测试不应调用真实 LLM、高德、本机 HTTP 服务或浏览器。真实服务测试必须显式开启对应环境变量，避免意外产生费用或依赖本机状态。

## 默认测试

在仓库根目录执行。此类测试应使用 mock、临时目录或受控的内存依赖，不需要启动前端、后端、PostgreSQL、LLM 或高德服务。

```powershell
python -m unittest discover -s test/unit -p "test_*.py" -v
python -m unittest discover -s test/integration -p "test_*.py" -v
```

也可以单独执行某个文件：

```powershell
python -m unittest test.unit.test_planning_service_react -v
python -m unittest test.unit.test_talk_agent_replan -v
python -m unittest test.unit.test_poi_vector_store -v
```

主要覆盖内容：

- 高德行政区/城市映射、路线几何和天气日期处理
- Chroma POI 缓存、向量检索与过滤
- 证据预取、近邻排程、计划校验与 ReAct 规划流程
- Talk Agent 的偏好提炼、意图识别和 ChangeSet 解析
- 定向修改、路线排序、审查日志及异步路由调用

## 本机 API 验收

`test/integration/test_api.py` 是手动验收脚本，不属于默认 CI。它会访问本机后端，并可能依赖 PostgreSQL、高德和模型服务。

### 前置条件

1. 已在 `backend/.env` 配置可用服务：

```env
DATABASE_URL=postgresql+asyncpg://postgres:password@127.0.0.1:5432/app
AMAP_API_KEY=your_amap_web_service_key
LLM_API_KEY=your_llm_api_key
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL_ID=your_model_id
JWT_SECRET=replace_with_a_long_random_secret
```

2. 启动后端：

```powershell
cd backend
.\venv\Scripts\Activate.ps1
python run.py
```

3. 如需验证浏览器界面，同时启动前端：

```powershell
cd frontend
npm install
npm run dev
```

4. 在另一个终端显式开启真实服务测试并执行：

```powershell
$env:RUN_REAL_SERVICE_TESTS = "1"
python test/integration/test_api.py
```

运行结束后移除开关：

```powershell
Remove-Item Env:RUN_REAL_SERVICE_TESTS
```

## 真实 LLM 与高德验收

真实模型和高德调用可能产生费用、限流或受外部数据变化影响，只能手动或在受保护的夜间任务中运行。

### 前置条件

- 已完成“本机 API 验收”的后端配置和启动步骤。
- `LLM_API_KEY`、`AMAP_API_KEY` 有效；若使用 MCP，还需配置 `AMAP_MAPS_API_KEY` 和安装 `uvx`。
- 测试应通过 `RUN_REAL_SERVICE_TESTS=1` 显式启用。

真实规划 Agent 的结果默认写入仓库根目录下被 Git 忽略的 `test-artifacts/plan_agent_real/`，也可通过 `TEST_ARTIFACT_DIR` 指定目录。

```powershell
$env:RUN_REAL_SERVICE_TESTS = "1"
python -m unittest test.integration.test_plan_agent_real -v
```

真实服务测试应遵循以下约定：

- 缺少密钥或未启用开关时，测试应明确跳过，而不是静默成功。
- 已启用开关后，真实调用失败必须使测试失败。
- 运行结果写入被 Git 忽略的 `artifacts/` 或 `test-artifacts/`，不提交真实 LLM/POI 输出。

## Chroma 检索诊断

`test/integration/test_chroma_hit.py` 用于观察正在运行的服务或本地 Chroma 的实际命中情况，是诊断工具而非默认测试。

```powershell
$env:RUN_REAL_SERVICE_TESTS = "1"
python test/integration/test_chroma_hit.py --city 深圳 --query 景点
```

根据脚本支持的参数，也可以使用直接访问本地 Chroma 的模式：

```powershell
$env:RUN_REAL_SERVICE_TESTS = "1"
python test/integration/test_chroma_hit.py --direct --city 深圳 --query 景点
```

## Playwright 端到端测试

浏览器 E2E 会登录、生成真实行程并操作页面；它依赖前端、后端、数据库、高德和模型服务，适合手动验收或夜间回归。

### 前置条件

1. PostgreSQL、后端和前端均已启动。
2. 已配置可用账号、LLM 与高德 Key。
3. 首次执行前安装浏览器：

```powershell
python -m playwright install
```

4. 显式启用真实服务测试：

```powershell
$env:RUN_REAL_SERVICE_TESTS = "1"
python test/e2e/test_trip_planner.py --city 广州 --preferences 美食 自然风光
```

## 多城市 E2E 回归

`test/e2e/test_major_cities.py` 会对多个城市重复执行真实规划。该测试成本高、耗时长并受外部服务限流影响，只应由人工或 nightly CI 调用。

```powershell
$env:RUN_REAL_SERVICE_TESTS = "1"
$env:RUN_MULTI_CITY_E2E = "1"
python test/e2e/test_major_cities.py
```

运行结束后清理环境变量：

```powershell
Remove-Item Env:RUN_REAL_SERVICE_TESTS
Remove-Item Env:RUN_MULTI_CITY_E2E
```

## 现有测试文件

### 单元测试

- `test_amap_service_city_scope.py`：行政区 geocode、adcode 与父城市 POI 搜索
- `test_amap_service_route_geometry.py`：驾车、步行、公交和地铁路线几何解析
- `test_map_poi_routes_async_threading.py`：地图/POI/规划路由的异步线程调用
- `test_observable_function_call_agent_logging.py`：Agent 循环事件日志
- `test_plan_agent_contract.py`：Plan、Search、Talk Agent 的领域契约
- `test_planning_service_evidence_plan.py`：预取 POI 证据后的确定性近邻排程
- `test_planning_service_react.py`：ReAct 规划、验证、降级和日志
- `test_poi_vector_store.py`：Chroma POI 存储、查询和过滤
- `test_talk_agent_replan.py`：对话重规划意图和 ChangeSet
- `test_trip_planner_agent_directed_replan.py`：定向重规划执行
- `test_trip_planner_agent_route_ordering.py`：景点与餐饮近邻排序
- `test_trip_planner_agent_weather_dates.py`：旅行日期和天气窗口
- `test_trip_routes_review_logging.py`：规划审查日志

### 集成与手动脚本

- `test_agent_layer_openness.py`：Agent 分层架构探针
- `test_agent_pipeline.py`：Talk Agent 到规划 Agent 的组合流程
- `test_plan_agent_real.py`：真实 LLM 规划 Agent 验收
- `test_api.py`：本机 API、数据库、高德和模型服务诊断
- `test_chroma_hit.py`：Chroma 命中诊断
- `test_trip_planner.py`：浏览器旅行规划 E2E
- `test_major_cities.py`：多城市浏览器 E2E 回归

## CI 建议

普通 Pull Request 仅执行默认单元和隔离集成测试。真实 LLM、高德、本机 HTTP 和多城市 Playwright 测试应放入手动触发或夜间工作流，并通过仓库 Secrets 提供密钥。
