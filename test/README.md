# 单元测试

## test_observable_function_call_agent_logging.py，Agent 循环与日志

```powershell
python unit/test_observable_function_call_agent_logging.py
```

## test_trip_planning_service_directed_replan.py，定向重规划

```powershell
python unit/test_trip_planning_service_directed_replan.py
```

## test_planning_service_evidence_plan.py，POI 近邻排程

```powershell
python unit/test_planning_service_evidence_plan.py
```

## test_trip_routes_review_logging.py，规划审查日志

```powershell
python unit/test_trip_routes_review_logging.py
```

## test_planning_service_react.py，ReAct 规划与校验

```powershell
python unit/test_planning_service_react.py
```

## test_poi_vector_store.py，POI 向量库

```powershell
python unit/test_poi_vector_store.py
```

## test_amap_service_route_geometry.py，道路与公共交通路线几何

```powershell
python unit/test_amap_service_route_geometry.py
```

## test_trip_planning_service_route_ordering.py，景点近邻排序

```powershell
python unit/test_trip_planning_service_route_ordering.py
```

## test_talk_agent_replan.py，对话重规划意图

```powershell
python unit/test_talk_agent_replan.py
```

## test_trip_planning_service_weather_dates.py，旅行日期天气筛选

```powershell
python unit/test_trip_planning_service_weather_dates.py
```

# 集成测试

## test_api.py，后端 API

```powershell
python integration/test_api.py
```

## test_chroma_hit.py，Chroma 检索结果

```powershell
python integration/test_chroma_hit.py
```

## test_talk_agent_chat_real.py，真实 TalkAgent 对话意图评测

```bash
python integration/test_talk_agent_chat_real.py
```

运行真实模型的十组 `chat/replan` 用例，逐组记录 `passed`、`error`、耗时、响应和对话提示；结果写入 `integration/results/`。

## test_talk_agent_talk_context.py，TalkAgent 连续上下文与规划输入

```powershell
python integration/test_talk_agent_talk_context.py
```

# 端到端测试

## test_trip_planner.py，网页旅行规划流程

```powershell
python e2e/test_trip_planner.py
```
