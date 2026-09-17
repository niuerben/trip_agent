# Service 层重构方案（基于现有代码）

> 本文只描述当前代码的职责边界、问题和渐进式重构方案。
>
> 本文不修改 Domain Schema，不新增不存在的领域对象，不把目标架构中的名称当成当前代码事实。

## 1. 现状范围

当前规划相关代码主要位于以下文件：

| 文件 | 当前职责 |
| --- | --- |
| `backend/app/services/trip_planning_service.py` | 规划入口、行政区准备、Chroma 召回、定向 ChangeSet 执行适配、确定性排程、天气补齐、POI 坐标/图片补齐、计划后处理、部分 POI 解析与选择、fallback 计划 |
| `backend/app/services/planning_service.py` | `PlanningSession`、`PlanningToolset`、`ValidatedPlanningReActAgent`；负责 ReAct 工具编排、POI 证据记录和 Draft 校验循环 |
| `backend/app/services/change_set_executor.py` | 在复制后的 `TripPlan` 上执行现有 `ChangeSet`，负责操作白名单、选择器匹配、POI 转 `Attraction`/`Meal`、日期更新 |
| `backend/app/services/planning_context.py` | `PlanningContext`、`PlanningState`、`POIRecord`、`DateUpdate` 数据结构 |
| `backend/app/services/amap_service.py` | 高德 REST/MCP 封装，包括 POI、天气、地理编码、路线等外部调用 |
| `backend/app/services/amap_photo_service.py` | 高德 POI 搜索及图片相关能力，当前也被定向 POI 替换逻辑直接使用 |
| `backend/app/services/poi_vector_store.py` | Chroma POI 持久化、分类和向量检索 |
| `backend/app/services/trip_plan_validator.py` | `TripPlan` 业务校验、结构化 `ValidationIssue`、城市范围和路线约束校验 |
| `backend/app/api/routes/trip.py` | API 超时、无模型密钥时的 fallback、定向结果持久化和响应包装 |

现阶段不要把下列名称描述为已经存在的代码模块：

- `IntentRecognizer`
- `ChangeSetService`
- `MealResolver`
- `AttractionResolver`
- `POIProvider`
- `ConstraintEngine`
- `PlanMutator`
- `FailurePolicy`
- `ReplanService`
- `MealConstraints`
- `DateRange`

它们最多只能作为未来可能的目标职责名称，不能作为当前系统事实。

## 2. 当前调用链

### 2.1 完整规划

```text
POST /api/trip/plan
  -> api.routes.trip.plan_trip
  -> get_trip_planning_service()
  -> TripPlanningService.plan_trip()
      -> 行政区解析：get_amap_service().get_city_center/get_city_adcode
      -> Chroma 召回：_retrieve_cached_pois()
      -> PlanningSession
      -> PlanningToolset.prepare_required_evidence()
          -> Chroma / 高德搜索
          -> 记录 evidence_records
      -> （可选）_build_evidence_plan()
          -> PlanningToolset.validate_draft()
      -> （否则）ValidatedPlanningReActAgent.run()
          -> PlanningToolset.search_poi()
          -> PlanningToolset.validate_draft()
      -> _fill_plan_timeline()
      -> _order_day_attractions_by_proximity()
      -> 天气获取和 _complete_weather_for_travel_dates()
      -> _enrich_attraction_images() 或 _enrich_meal_pois()
      -> validate_trip_plan()
      -> 返回 TripPlan
```

### 2.2 定向修改

```text
POST /api/trip/plan
  -> request.current_plan + request.change_set
  -> TripPlanningService.plan_trip()
      -> TripPlan.model_validate(current_plan)
      -> _execute_change_set()
          -> 内部 _LegacyAttractionResolver
          -> ChangeSetExecutor.execute()
              -> 复制 plan/request
              -> 校验 operation
              -> 选择器匹配
              -> resolver.resolve_attraction()
              -> 修改复制后的计划
      -> validate_trip_plan()
      -> 成功返回局部修改结果

局部执行失败或验证失败
  -> 保留原计划/草稿
  -> 继续走 PlanningSession + ReAct 定向重规划
```

### 2.3 API 层 fallback

```text
api.routes.trip.plan_trip
  -> 无 LLM key
     -> TripPlanningService._create_fallback_plan()
     -> _enrich_attraction_images()

  -> Agent/外部服务异常或超时
     -> TripPlanningService._create_fallback_plan()
     -> _enrich_attraction_images()
```

因此 fallback 目前不只在 Service 内部，API 路由也参与决定何时使用 fallback。

## 3. 当前职责问题

### 3.1 `TripPlanningService` 是多个服务的集合

`TripPlanningService` 当前同时承担：

1. 规划用例入口：`plan_trip()`。
2. 行政区和搜索范围准备。
3. Chroma 初始召回：`_retrieve_cached_pois()`。
4. 确定性证据排程：`_build_evidence_plan()`。
5. ReAct 规划流程的创建和结果接收。
6. 定向 ChangeSet 适配：`_execute_change_set()`。
7. 景点、餐饮的定向 POI 解析：`_resolve_replacement_poi()`、`_resolve_replacement_meal_poi()`。
8. POI 字段转换和名称评分。
9. 天气补齐。
10. 景点坐标、越界 POI 和图片补齐。
11. 时间线和景点顺序后处理。
12. fallback 计划构造。

问题不是这些逻辑都必须立即拆成新文件，而是入口类已经同时拥有“用例编排”和“领域/基础设施细节”。后续修改任何一个环节，都容易影响完整规划、定向修改和 fallback。

### 3.2 `ChangeSetExecutor` 不是纯 dispatcher

当前 `ChangeSetExecutor` 已经是一个相对独立的原子执行器，但它仍然负责：

- operation 白名单校验；
- 景点和餐饮 selector 匹配；
- 调用 resolver；
- 把 `POIRecord`/字典转换为 `Attraction`/`Meal`；
- `update_dates` 的日期变更；
- 生成变更说明。

这意味着它不是单纯的 `operation -> handler` 路由器。当前不应直接把它改名或重写为文档中的新服务，而应先保持其行为稳定，逐步减少它对具体 POI 解析语义的了解。

### 3.3 `_LegacyAttractionResolver` 暴露了接口边界问题

`TripPlanningService._execute_change_set()` 内部定义 `_LegacyAttractionResolver`，并根据 operation 分支：

- `replace_meal` 调用 `_resolve_replacement_meal_poi()`；
- 其他操作调用 `_resolve_replacement_poi()`；
- 最后统一转换成 `POIRecord`。

这说明当前 resolver 接口名是景点导向的，但实际已经被餐饮替换复用。这里先记录为边界问题，不在本阶段通过增加 `operation="replace_meal"` 之类参数继续扩展。

### 3.4 `PlanningContext` 和 `PlanningSession` 存在信息重叠

当前已有两套执行上下文：

- `PlanningContext`：位于 `planning_context.py`，包含 `city`、`amap_city`、`city_center`、`radius_km`、`target_adcode`、`request`。
- `PlanningSession`：位于 `planning_service.py`，除请求和范围信息外，还包含 `cached_pois`、`validated_plan`、证据记录、搜索历史、刷新次数和校验计数。

它们用途不同：前者服务于 ChangeSet 执行，后者服务于 ReAct/证据搜索。但字段重复，且 `TripPlanningService` 同时创建和传递两者。重构时应先明确“请求事实”和“ReAct 可变状态”的边界，不要直接合并两个类。

### 3.5 fallback 的决策点分散

当前至少有两处 fallback 相关行为：

- `TripPlanningService._create_fallback_plan()` 负责构造最小计划。
- `api/routes/trip.py` 负责无 LLM key、Agent 超时或 Agent 异常时调用 fallback，并决定 API 最终返回什么。

另外，ReAct 未通过 Validator 时通常不是直接构造 fallback，而是抛出异常或回到另一条规划路径。后续应统一“失败分类”和“由谁决定降级”，但不能先假设已有 `FailurePolicy`。

## 4. 重构目标

本次重构先只处理 Service 层，不改变 Domain Schema 和外部 API 契约。

目标是让以下职责可以独立测试和替换：

```text
请求/规划用例编排
  -> 规划上下文准备
  -> POI 证据准备
  -> 计划生成（确定性或 ReAct）
  -> 计划后处理与校验
  -> 定向 ChangeSet 执行
  -> 失败转入下一策略
```

更具体地说：

1. `TripPlanningService.plan_trip()` 保留为外部入口，但逐步只做流程编排。
2. 行政区解析和搜索范围计算集中到一个已有代码可迁移出的内部组件中；第一阶段可以先使用私有函数，不急于新增目录。
3. 证据准备继续由 `PlanningToolset` 和现有 Chroma/高德逻辑负责，不让 `TripPlanningService` 直接重复实现搜索规则。
4. 确定性排程和 ReAct 规划保留两条路径，但明确共同的“校验、后处理、返回”出口。
5. ChangeSet 的原子执行继续由 `ChangeSetExecutor` 负责，`TripPlanningService` 只负责准备上下文、选择是否局部执行以及失败后的后续策略。
6. POI 搜索、POI 选择、计划节点转换分开整理，暂不引入未经现有代码验证的新抽象名。
7. fallback 行为先建立明确的错误分类和调用关系，再考虑是否提取独立组件。

## 5. 建议的渐进式重构顺序

### CP0：基线和行为清单

只做记录和测试，不改变运行逻辑：

- 运行现有单元测试和可运行的集成测试。
- 记录完整规划、定向景点替换、定向餐饮替换、日期更新、ReAct 校验失败、无 LLM key、超时 fallback 的现状行为。
- 确认 `update_day` 已删除后的代码残留，单独处理残留，不把它混入 Service 层重构。
- 为 `TripPlanningService.plan_trip()` 当前分支补充调用路径测试或最小 fake 依赖测试。

### CP1：固定 `plan_trip()` 的阶段边界

不迁移算法，只把 `plan_trip()` 中的流程按现有职责分段，形成稳定的内部调用边界：

```text
_prepare_planning_scope
_retrieve_initial_pois
_try_targeted_change_set
_prepare_planning_session
_try_deterministic_plan
_run_react_plan
_finalize_plan
```

这些名称是本阶段建议的私有方法边界，不代表新领域模块。每个方法必须保持输入输出清晰，并保留现有日志和异常行为。

优先拆出的只是编排代码，不搬动 `_build_evidence_plan()`、天气、图片和 POI 评分算法。

### CP2：把“规划上下文准备”从入口中隔离

现有代码已经包含：

- `_normalize_city_for_amap()`；
- `_DISTRICT_SCOPES`、`_district_keyword()`；
- `get_city_center()`、`get_city_adcode()`；
- 区县半径和 `target_adcode` 计算。

先将这部分整理成一个稳定的内部返回值，内容对应现有 `PlanningContext` 所需信息：

```text
city
amap_city
city_center
radius_km
target_adcode
```

不要在这一步引入新的行政区领域模型，也不要改变区县映射和 adcode 过滤逻辑。

### CP3：隔离初始 POI 召回

`_retrieve_cached_pois()` 当前是静态方法，负责 Chroma 三类 POI 召回。将它作为“初始候选召回”边界保留：

- 输入：`TripRequest`、`Preference`、`adcode`、`amap_city`。
- 输出：现有 `list[dict]`。
- 超时策略保持在当前调用侧。
- 不把天气和路线放进 POI 召回。

后续如果需要抽象检索接口，应先以现有 `list[dict]` 兼容，不先设计不存在的 `POIProvider` 协议。

### CP4：整理完整规划两条策略

当前完整规划有两条策略：

1. 预加载证据后调用 `_build_evidence_plan()`，再用 `PlanningToolset.validate_draft()` 校验。
2. 由 `ValidatedPlanningReActAgent.run()` 执行搜索和 Draft 校验。

应把它们统一为同一个结果约定：

```text
返回已通过 Validator 的 TripPlan
或返回“本策略无法交付”的明确结果
```

确定性策略未通过 Validator 时继续回到 ReAct，这是当前已有行为，应保留。不要让确定性排程自己处理 ReAct，也不要让 `PlanningToolset` 负责整个 Service 的 fallback。

### CP5：整理定向 ChangeSet 流程

当前建议保留以下边界：

```text
TripPlanningService
  -> 判断是否存在 current_plan + change_set
  -> 判断是否 full_replan
  -> 构造 PlanningContext
  -> 调用 ChangeSetExecutor
  -> 对结果调用 validate_trip_plan
  -> 成功则返回
  -> ChangeExecutionError/ValueError 则回到定向 ReAct
```

`ChangeSetExecutor` 继续负责复制对象、操作校验和原子修改。

本阶段重点是把 `_LegacyAttractionResolver` 从 `TripPlanningService._execute_change_set()` 中移到明确的现有服务边界内，或者至少变成可独立测试的类；暂不改变 `ChangeOperation` 字段，也不新增餐饮 Schema。

后续再分别处理：

- 景点 POI 解析：当前 `_resolve_replacement_poi()`；
- 餐饮 POI 解析：当前 `_resolve_replacement_meal_poi()`；
- POI 字典到 `POIRecord` 的转换。

### CP6：集中计划后处理

当前后处理包括：

- `_fill_plan_timeline()`；
- `_order_day_attractions_by_proximity()`；
- 天气筛选和缺失日期补查；
- `_enrich_meal_pois()`；
- `_enrich_attraction_images()`；
- `validate_trip_plan()`。

建议顺序固定为：

```text
计划生成
  -> 时间线补齐
  -> 景点顺序整理
  -> 天气补齐
  -> 按模式决定图片/餐饮补齐
  -> 最终 Validator
```

其中“定向修改和预加载证据跳过图片补齐、转前端异步加载”的现有行为必须保留。不要把图片服务和计划核心生成混在一起。

### CP7：统一失败决策，但暂不命名为新 FailurePolicy

先列出实际失败来源和当前处理方式：

| 失败来源 | 当前处理 |
| --- | --- |
| Chroma 召回超时 | 跳过缓存，继续高德/规划流程 |
| POI 预加载不完整 | 回到按需 ReAct |
| 确定性排程 Validator 失败 | 刷新部分证据后重排，仍失败则 ReAct |
| ChangeSet 局部执行失败 | 回到定向 ReAct |
| Agent 超时/异常 | API 路由构造 fallback 计划 |
| 无 LLM key | API 路由直接构造 fallback 计划 |
| 最终 Validator 失败 | 抛出异常，由 API 层处理 |

在这些行为有测试覆盖后，再决定是否需要单独的失败决策类。不要先把所有异常都包装成一个笼统的 ServiceError，否则会丢失当前调用方依赖的 `ChangeExecutionError`、`TripPlanValidationError` 和超时语义。

## 6. 推荐的目标结构（只使用现有职责名称）

第一阶段不建议新建大量目录。可以先在现有 `services` 目录内逐步形成以下边界：

```text
services/
├── trip_planning_service.py
│   └── 对外规划用例入口和流程编排
├── planning_service.py
│   └── ReAct、PlanningSession、PlanningToolset、证据记录
├── change_set_executor.py
│   └── ChangeSet 原子执行
├── planning_context.py
│   └── ChangeSet/规划执行上下文和 POIRecord
├── trip_plan_validator.py
│   └── TripPlan 业务校验
├── amap_service.py
│   └── 高德 REST/MCP 外部调用
├── amap_photo_service.py
│   └── 高德 POI/图片补齐相关调用
└── poi_vector_store.py
    └── Chroma POI 缓存和检索
```

只有当某一职责已经在当前代码中有清晰输入输出、并且测试能够独立覆盖时，才考虑新增文件。新增文件的依据应是现有职责搬迁，而不是先建立文档中的理想目录。

## 7. 明确不在本轮做的事情

本轮只写方案，不修改代码。后续即使开始实施，也不应与 Service 层第一阶段混做：

- 不修改 `backend/app/models/schemas.py`。
- 不新增 `MealConstraints`、`DateRange` 等当前不存在的 Schema。
- 不改变 `ChangeSet` 的 JSON 结构。
- 不把 `TalkAgent` 改造成新的 IntentRecognizer。
- 不重写 `ChangeSetExecutor`。
- 不把 Amap REST、Amap MCP、Amap 图片服务一次性合并。
- 不把 Chroma 天气或路线数据加入缓存。
- 不删除现有 ReAct、确定性排程或 Validator 路径。
- 不把 API 路由 fallback 直接搬到一个未经测试的新类。
- 不以目录结构变化代替职责边界验证。

## 8. 验收标准

Service 层重构达到阶段目标时，应能从代码和测试中回答：

1. 完整规划从哪里进入，行政区上下文在哪里准备？
2. 初始 Chroma 召回和 ReAct 工具搜索分别由谁负责？
3. 确定性排程失败后为什么回到 ReAct？
4. 定向 ChangeSet 失败后为什么回到定向 ReAct？
5. `ChangeSetExecutor` 是否仍然保证输入 `TripPlan` 不被原地修改？
6. 最终 `TripPlan` 由哪个 Validator 作为交付闸门？
7. 图片补齐为什么在定向修改和预加载证据模式下跳过？
8. 哪些异常由 Service 继续抛出，哪些异常由 API 层转成 fallback？

如果这些问题仍然需要阅读整个 `TripPlanningService` 才能回答，说明边界还没有拆清楚；如果能通过少量入口方法和测试回答，才进入下一阶段的实际搬迁。

## 9. 本文结论

当前最值得先做的不是创建一组新的领域类，而是：

```text
保留现有 Schema
保留现有 ChangeSetExecutor 行为
保留现有 PlanningToolset/ReAct 行为
先把 TripPlanningService 的流程编排和细节实现分开
再按测试覆盖逐个迁移职责
```

重构的第一实际代码步骤应是 CP0/CP1：建立基线，并固定 `plan_trip()` 的阶段边界。完成并验证后，再决定哪些私有方法值得搬到独立服务文件。
