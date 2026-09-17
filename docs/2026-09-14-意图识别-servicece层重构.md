> **已过时**：本文档为历史设计讨论。TalkAgent 已并入 plan_agent.py 的 PlanAgent（唯一入口 `talk()`），意图识别改为提示词驱动、后端不再做确定性门控。当前实现以 `backend/app/agents/plan_agent.py` 为准。

可以，而且我建议这次不要再按照“发现一个 Bug → 在现有 service 里打一个补丁”的方式做。你现在已经碰到了一个很典型的边界问题：意图识别、ChangeSet、业务执行、POI 检索、fallback 全部有互相渗透的迹象。日志里甚至出现了 `resolve_attraction(..., operation="replace_meal")` 这种为了补业务语义而给旧接口加参数的做法。

你准备从“意图识别 → service 层”重构，我建议把目标定成：

```text
用户自然语言
      ↓
Intent / ChangeSet 识别
      ↓
结构化 Domain Command
      ↓
Service 编排
      ↓
Domain Resolver
      ↓
POI / Weather / Route 等 Infrastructure
      ↓
Plan Mutation
      ↓
Result / Fallback
```

核心原则只有一个：

> **LLM 负责理解“用户想做什么”，Service 负责决定“怎么做”，Infrastructure 负责“调用外部能力”。**

不要让 LLM、Service、Amap 相互越界。

---

## 一、先不要动代码，先把现状画清楚

第一阶段只做代码考古，不修改行为。

重点把下面这条链完整找出来：

```text
TalkAgent
  ↓
intent recognition
  ↓
ChangeSet schema
  ↓
ChangeSetExecutor
  ↓
TripPlanningService
  ↓
AmapService / other services
  ↓
TripPlan
```

你现在的日志已经证明至少存在这些东西：

* `TalkAgent`
* `ChangeSet`
* `ChangeSetExecutor`
* `TripPlanningService`
* `PlanningContext`
* `POIRecord`
* Amap POI 查询
* fallback
* meal / attraction 匹配

而且 `ChangeSetExecutor` 已经承担了不少职责，包括 operation validation、plan mutation、POI 转模型等。

第一步不要重构。

先建立一张职责表：

| 模块                  | 现在做什么                    | 应该做什么                        |
| ------------------- | ------------------------ | ---------------------------- |
| TalkAgent           | 意图识别、可能生成 ChangeSet      | 只理解用户意图                      |
| Schema              | 表达 ChangeSet             | 定义稳定 Domain Command          |
| ChangeSetExecutor   | 校验 + 查 POI + 修改 Plan     | 编排 command execution         |
| TripPlanningService | 规划、POI resolver、fallback | Trip planning domain service |
| AmapService         | 高德 API                   | 外部 POI provider              |
| PlanningContext     | 执行上下文                    | 保留                           |
| Fallback            | 散落                       | 统一 failure policy            |

这一步完成以后你才知道哪些东西应该搬。

---

# 二、第一刀：先稳定 Domain Schema

这是整个重构最重要的一步。

你现在最大的问题不是 `resolve_meal()` 写得不好，而是：

```text
operation
target.semantic
selector
```

表达能力和业务对象之间还没有完全对齐。

比如这次出现：

```text
operation = add_attraction
semantic = 非面类中式早餐
```

这就是一个明显的 domain model 不一致。

我建议把 operation 明确成业务动作：

```python
class ChangeOperation(str, Enum):
    ADD_ATTRACTION = "add_attraction"
    DELETE_ATTRACTION = "delete_attraction"
    REPLACE_ATTRACTION = "replace_attraction"

    ADD_MEAL = "add_meal"
    DELETE_MEAL = "delete_meal"
    REPLACE_MEAL = "replace_meal"

    UPDATE_DAY = "update_day"
    UPDATE_DATES = "update_dates"

    FULL_REPLAN = "full_replan"
```

然后 target 不要只塞一个自然语言字符串。

可以逐步变成：

```python
class MealConstraint(BaseModel):
    meal_type: Literal["breakfast", "lunch", "dinner"] | None
    cuisine: str | None
    excluded: list[str] = []
    preferred: list[str] = []
    area: str | None
    max_distance_m: int | None
```

例如用户说：

> 钱江新城附近找一家不吃面的中式早餐

LLM 最终输出：

```json
{
  "operation": "add_meal",
  "selector": {
    "day_index": 1,
    "meal_type": "breakfast"
  },
  "constraints": {
    "area": "钱江新城",
    "cuisine": "中式",
    "excluded": ["面食"]
  }
}
```

这时候 Service 根本不需要猜：

```text
“早餐”
是不是 meal？

“非面”
是不是约束？

“钱江新城”
是不是区域？
```

这才是重构真正应该解决的问题。

---

# 三、第二刀：把 Intent Recognition 从 Service 中彻底隔离

建议形成：

```text
TalkAgent
    ↓
IntentRecognizer
    ↓
ChangeSet
```

而不是：

```text
TalkAgent
    ↓
ChangeSet
    ↓
Service 又猜用户意图
```

IntentRecognizer 的职责只有：

> Natural Language → Structured Command

例如：

```python
class IntentRecognizer(Protocol):
    async def recognize(
        self,
        message: str,
        context: ConversationContext,
    ) -> ChangeSet:
        ...
```

它可以调用 LLM。

但是它**不能**：

* 调高德
* 搜餐厅
* 修改 TripPlan
* 创建 fallback
* 判断 POI 是否存在

这些都属于 Service / Infrastructure。

---

# 四、第三刀：建立真正的 Application Service

这一层是你现在最值得重构的地方。

我建议：

```text
ChangeSetService
```

作为入口。

例如：

```python
class ChangeSetService:

    async def execute(
        self,
        command: ChangeSet,
        context: PlanningContext,
    ) -> ChangeResult:
        ...
```

内部：

```text
ChangeSetService
       │
       ├── validate
       │
       ├── dispatch
       │
       ├── resolver
       │
       ├── mutation
       │
       └── failure policy
```

而不是让 `ChangeSetExecutor` 自己知道：

```text
Amap
Meal
Attraction
Fallback
Weather
```

---

# 五、第四刀：Resolver 按“业务对象”拆，而不是按高德 API 拆

这里正好对应我们刚才讨论的“餐饮和景点是否需要区分”。

我建议：

```text
POIProvider
      ↓
AmapPOIProvider
```

底层统一。

上面：

```text
AttractionResolver
MealResolver
HotelResolver
```

业务上区分。

结构：

```text
                 ┌── AttractionResolver
                 │
ChangeSetService ├── MealResolver
                 │
                 └── HotelResolver
                         │
                         ↓
                    POIProvider
                         │
                         ↓
                      Amap
```

这样非常干净。

例如：

```python
class MealResolver:

    async def resolve(
        self,
        command: AddMealCommand,
        context: PlanningContext,
    ) -> MealCandidate:
        pois = await self.poi_provider.search(...)
        return self.rank_and_filter(pois, command.constraints)
```

而：

```python
class AttractionResolver:

    async def resolve(...):
        pois = await self.poi_provider.search(...)
        return self.rank_and_filter(...)
```

共享：

```python
POIProvider.search()
```

但不共享业务语义。

这比现在这种：

```python
resolve_attraction(..., operation="replace_meal")
```

干净得多。日志中确实已经出现这种 workaround。

---

# 六、第五刀：把“检索”和“选择”分开

这是你这个项目后面非常值得做的一步。

现在类似：

```text
search_pois()
 ↓
过滤
 ↓
score
 ↓
chosen = candidates[0]
```

实际上混在了一起。日志里的 `_resolve_replacement_meal_poi()` 就是这么做的：查询、类型过滤、关键词过滤、评分、最终选择全部集中在一个方法里。

建议拆：

```text
POIProvider
    ↓
Search candidates
    ↓
ConstraintFilter
    ↓
CandidateRanker
    ↓
Resolver
```

例如：

```python
pois = await provider.search(query)

pois = meal_filter.apply(
    pois,
    constraints,
)

candidate = meal_ranker.rank(
    pois,
    constraints,
)
```

这样以后用户说：

```text
便宜一点
评分高
离景点近
不吃辣
素食
适合早餐
```

你不需要继续堆：

```python
if "早餐" ...
if "不吃面" ...
if "不辣" ...
if "便宜" ...
```

---

# 七、第六刀：建立统一 Failure Model

这个项目现在的 fallback 是比较危险的。

日志已经出现：

```text
POI 查询失败
    ↓
fallback
    ↓
_create_fallback_plan 不存在
    ↓
500
```

而且当前代码还在不断把 fallback 往 `TripPlanningService` 里补。

建议统一：

```python
class ServiceError(Exception):
    code: str
    message: str
    retryable: bool
    recoverable: bool
```

例如：

```text
poi_not_found
poi_provider_timeout
invalid_command
constraint_unsatisfied
plan_mutation_failed
weather_unavailable
```

然后：

```text
Service
  ↓
ServiceError
  ↓
FailurePolicy
  ├── retry
  ├── deterministic fallback
  ├── ask user
  └── full replan
```

这样“fallback”就不是某个散落的方法，而是一种**系统策略**。

---

# 八、第七刀：把 ReAct / LLM fallback 放到 Service 外层

你现在已经有：

```text
ChangeSet 无法局部执行
    ↓
ReAct 定向重规划
```

这个机制可以保留。日志明确显示了这条路径。

但建议：

```text
ChangeSetService
      ↓
执行 ChangeSet
      ↓
失败
      ↓
FailurePolicy
      ↓
ReplanService
      ↓
ReAct Agent
```

而不是：

```text
ChangeSetExecutor
    ↓
自己发现失败
    ↓
自己开始 ReAct
```

这样整个系统会变成：

```text
LLM 层
├── IntentRecognizer
└── Replanner

Application 层
├── ChangeSetService
└── ReplanService

Domain 层
├── MealResolver
├── AttractionResolver
├── PlanMutator
└── ConstraintEngine

Infrastructure
├── AmapPOIProvider
├── WeatherProvider
└── RouteProvider
```

这是我比较推荐的最终形态。

---

# 九、具体实施顺序

不要一次性重写。

我建议你按下面 8 个 checkpoint 做，每一个都可以单独 commit。

### CP0：建立基线

只做：

```text
pytest
compileall
现有 integration/e2e
```

把当前通过率记录下来。

尤其保存：

```text
intent tests
changeset tests
executor tests
Amap tests
trip planning tests
```

**没有基线，不开始重构。**

---

### CP1：整理 Schema

目标：

```text
ChangeSet
ChangeOperation
Selector
Target
Constraints
```

先不改执行逻辑。

新增：

```text
add_meal
replace_meal
delete_meal
```

并保留兼容层。

例如旧的：

```text
add_attraction + semantic=早餐
```

暂时可以转换成：

```text
add_meal
```

但这个兼容转换应该明确标记为 legacy。

---

### CP2：抽 IntentRecognizer

目标：

```text
TalkAgent
 ↓
IntentRecognizer
 ↓
ChangeSet
```

测试重点：

```text
“把第二天午餐换成川菜”
→ replace_meal

“第二天增加西湖”
→ add_attraction

“第三天不要这个景点”
→ delete_attraction

“把第二天重新规划”
→ full_replan
```

先保证识别，不执行。

---

### CP3：重构 ChangeSetExecutor

把它变成纯 dispatcher：

```python
operation → handler
```

例如：

```python
handlers = {
    "add_meal": self.meal_service.add,
    "replace_meal": self.meal_service.replace,
    "add_attraction": self.attraction_service.add,
    ...
}
```

不要再出现：

```python
if operation == "replace_meal":
    resolver.resolve_attraction(...)
```

---

### CP4：抽 MealResolver / AttractionResolver

这是你这次餐厅问题真正应该落地的地方。

```text
MealResolver
AttractionResolver
```

共享：

```text
POIProvider
```

不共享业务约束。

---

### CP5：抽 ConstraintEngine

把：

```text
区域
距离
类型
偏好
排除项
预算
时间
```

统一变成约束。

这一步完成以后，类似：

```text
非面早餐
川菜午餐
便宜一点的晚餐
西湖附近餐厅
```

都只是不同的 `MealConstraints`。

而不是不断新增 resolver 特判。

---

### CP6：统一 FailurePolicy

处理：

```text
POI 0 results
Amap timeout
invalid target
constraint unsatisfied
weather None
route unavailable
```

明确：

```text
retry
fallback
replan
ask user
hard failure
```

---

### CP7：最后才动 ReAct / Full Replan

等 deterministic service 稳定以后再接：

```text
ChangeSet
 ↓
deterministic execution
 ↓
failure
 ↓
ReAct fallback
```

否则你会出现现在这种情况：

```text
底层 service 不稳定
+
LLM fallback
+
fallback service 不稳定
```

最后根本不知道谁出了问题。

---

# 十、你这次重构最重要的验收标准

我不建议以“代码结构看起来漂亮”为验收标准。

应该用**能力边界**验收。

最终至少应该能回答：

```text
用户说什么？
      ↓
IntentRecognizer

用户想修改什么？
      ↓
ChangeSet

这个操作属于哪个业务对象？
      ↓
Meal / Attraction / Hotel

需要调用什么外部能力？
      ↓
POIProvider / WeatherProvider / RouteProvider

怎么判断候选是否符合？
      ↓
ConstraintEngine

怎么修改 TripPlan？
      ↓
PlanMutator

失败怎么办？
      ↓
FailurePolicy

确定性执行失败怎么办？
      ↓
ReplanService
```

如果每一个问题都能落到一个明确模块，重构就成功了。

---

## 最后给你一个实际的目录目标

我不会一开始就创建这么多文件，但最终可以向这个方向靠：

```text
backend/app/
│
├── agents/
│   ├── talk_agent.py
│   ├── intent_recognizer.py
│   └── replanner.py
│
├── domain/
│   ├── commands.py
│   ├── constraints.py
│   ├── entities.py
│   └── errors.py
│
├── services/
│   ├── change_set_service.py
│   ├── meal_service.py
│   ├── attraction_service.py
│   ├── plan_mutator.py
│   ├── constraint_engine.py
│   └── failure_policy.py
│
├── resolvers/
│   ├── meal_resolver.py
│   ├── attraction_resolver.py
│   └── hotel_resolver.py
│
├── providers/
│   ├── amap_poi_provider.py
│   ├── weather_provider.py
│   └── route_provider.py
│
└── models/
    └── schemas.py
```

不过**不要直接让 Claude Code 把现有项目改成这个目录**。你这次已经出现过 `Write` 后把 `change_set_executor.py` 的方法边界打乱、重复类定义等问题。

正确策略是：

**先定义边界 → 搬一个职责 → 测试 → commit → 再搬下一个。**

尤其第一阶段，我建议你只做一件事：

> **把当前“意图识别 → ChangeSet”的完整代码链找出来，然后设计新的 Command Schema。暂时不要改 `TripPlanningService` 和 `ChangeSetExecutor`。**

这是这次重构的地基。
