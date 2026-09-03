# 04：POI 路由——把高德搜索与 Chroma 检索接成可用 API

本章阅读 `backend/app/api/routes/poi.py`，并顺着调用链看到 `AmapService`、`AmapPhotoService` 和 `PoiVectorStore`。POI（Point of Interest）接口服务于两个场景：用户直接搜索“深圳博物馆”，以及规划流程按语义从本地 Chroma 候选库中召回景点、酒店和餐饮。

路由被 `backend/app/api/main.py` 以 `/api` 挂载，模块自身声明 `APIRouter(prefix="/poi")`，因此完整前缀是 `/api/poi`。

## 1. 路由地图

| 方法 | 实际路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/poi/detail/{poi_id}` | 按高德 POI ID 获取详情 |
| `GET` | `/api/poi/search` | 通过高德 REST 文本搜索 POI |
| `GET` | `/api/poi/vector-search` | 从后端已初始化的 Chroma 查询候选 |
| `GET` | `/api/poi/photo` | 按景点名称获取高德官方图片 |

详情接口使用 `POIDetailResponse`，其他接口返回字典结构，便于保留高德或向量检索的字段。

## 2. 场景：用户搜索“博物馆”

请求：

```http
GET /api/poi/search?keywords=博物馆&city=深圳
```

`search_poi()` 的执行步骤很短：

```python
amap_service = get_amap_service()
result = await asyncio.to_thread(
    amap_service.search_poi,
    keywords,
    city,
)
return {"success": True, "message": "搜索成功", "data": result}
```

这里有一个关键的并发边界。`AmapService.search_poi()` 使用同步 `requests.get()` 调用高德 REST API，路由函数本身是异步函数，所以通过 `asyncio.to_thread()` 把同步网络调用放到线程池，事件循环可以继续处理其他请求。

进入 `AmapService.search_poi()` 后，服务会：

1. 检查 `AMAP_API_KEY`。
2. 请求 `https://restapi.amap.com/v3/place/text`。
3. 传入关键词、城市、`citylimit=true`、`extensions=all` 等参数。
4. 检查高德 JSON 中的 `status`。
5. 解析 `location` 的“经度,纬度”文本，并构造 `POIInfo`。
6. 跳过坐标格式不正确的条目。

响应示例的形状如下：

```json
{
  "success": true,
  "message": "搜索成功",
  "data": [
    {
      "id": "B0FF...",
      "name": "深圳博物馆",
      "type": "科教文化服务;博物馆",
      "address": "深圳市福田区",
      "location": {"longitude": 114.05, "latitude": 22.54},
      "tel": "0755-..."
    }
  ]
}
```

`city` 默认值是“北京”，因此省略城市参数时仍能形成合法请求；产品调用应显式传入目的城市，命中率和城市范围更可靠。

## 3. 场景：规划器查询本地候选

请求：

```http
GET /api/poi/vector-search?query=适合亲子游的博物馆&city=深圳&poi_group=attraction&top_k=5
```

处理流程：

```python
store = get_poi_vector_store()
if store is None:
    raise HTTPException(status_code=503, detail="Chroma 不可用")

results = await asyncio.to_thread(
    store.search,
    query=query,
    city=city,
    limit=top_k,
    adcode=adcode,
    poi_group=poi_group,
    distance_threshold=threshold_from_settings,
)
```

### 参数约束

- `query` 必填，是向量查询词。
- `city` 默认“深圳”。服务层会统一“广州市”和“广州”这类城市键。
- `poi_group` 可选值为 `attraction`、`hotel`、`meal`。
- `adcode` 可选，适合“深圳坪山”这类区县级范围过滤。
- `top_k` 使用 `Query(..., ge=1, le=50)` 限制在 1 到 50。
- `threshold` 可覆盖配置中的余弦距离阈值；省略时读取 `settings.poi_vector_distance_threshold`，默认 0.55。

`PoiVectorStore.search()` 先按城市构造 Chroma `where` 条件；提供 `adcode` 时使用城市和行政区的 AND 过滤。Chroma 以 cosine 距离衡量相似度，距离越小越接近查询。超过阈值的结果会丢弃。指定 `poi_group` 时，旧数据即使没有该元数据，也会尝试根据名称、类型和 typecode 推断大类。

响应带有简单性能元数据：

```json
{
  "success": true,
  "message": "Chroma 查询成功",
  "data": [],
  "meta": {
    "query_duration_ms": 12.345,
    "distance_threshold": 0.55
  }
}
```

路由在请求外层先调用 `get_poi_vector_store()`。这个函数有进程内缓存：已有 store 时直接返回；首次调用才创建 PersistentClient。应用启动事件已经尝试预热它，路由仍保留懒加载逻辑，以应对启动阶段失败或测试环境未预热的情况。

## 4. 失败如何转换成 HTTP 响应

### 高德搜索和详情：500

详情：

```http
GET /api/poi/detail/B0FF123
```

路由调用 `amap_service.get_poi_detail(poi_id)`，成功后返回：

```json
{
  "success": true,
  "message": "获取POI详情成功",
  "data": {"...": "高德返回的详情"}
}
```

高德 key 缺失、网络失败、服务返回错误等异常会被捕获，打印日志并转换为 HTTP 500。搜索接口采用同样策略，消息分别是“获取POI详情失败”和“搜索POI失败”。

### Chroma 不可用：503

`get_poi_vector_store()` 捕获初始化异常并返回 `None`。路由返回 503“Chroma 不可用”，调用方可以把它视为向量缓存暂时不可用，再转到高德搜索或规划服务的降级路径。`PoiVectorStore.search()` 对非法 `poi_group` 抛出 `ValueError`，路由将其转换为 400，避免把客户端参数错误伪装成服务器故障。

## 5. 图片接口：城市优先，空结果可接受

请求：

```http
GET /api/poi/photo?name=世界之窗&city=深圳
```

`get_attraction_photo()` 先使用带城市的搜索：

```python
photo_url = await asyncio.to_thread(
    photo_service.get_photo_url,
    name,
    city=city,
)
if not photo_url and city:
    photo_url = await asyncio.to_thread(
        photo_service.get_photo_url,
        name,
        city="",
    )
```

第一次搜索提高同名景点的匹配精度；没有结果时再无城市兜底。即使最终没有图片，也返回 HTTP 200：

```json
{
  "success": true,
  "message": "未找到匹配图片",
  "data": {
    "name": "世界之窗",
    "city": "深圳",
    "photo_url": null
  }
}
```

网络或服务异常才会进入 HTTP 500。项目约定图片补齐只接受高德域名，规划服务中的图片富化和前端异步加载还会进一步处理 URL；POI 路由本身负责查询结果包装。

## 6. 三条调用链的对照

```text
/api/poi/search
  -> get_amap_service()
  -> AmapService.search_poi()
  -> 高德 REST /v3/place/text
  -> POIInfo 列表

/api/poi/vector-search
  -> get_poi_vector_store()
  -> PoiVectorStore.search()
  -> Chroma city/adcode/group/距离过滤
  -> 候选字典列表

/api/poi/photo
  -> get_amap_photo_service()
  -> 高德关键词图片查询（城市优先）
  -> photo_url 或 null
```

REST 搜索适合获取即时结果，向量搜索适合从已缓存证据中低延迟召回；两者都通过线程卸载保护异步 API。规划服务还会把高德返回的 POI 写入 Chroma，缓存逐步丰富。

## 7. 常见故障定位

| 现象 | 检查位置 | 原因/处理 |
| --- | --- | --- |
| `/search` 返回 500 且提示 key 未配置 | `.env`、`config.py` | 配置 `AMAP_API_KEY` 后重启服务 |
| 高德返回空列表 | `keywords`、`city`、高德日志 | 关键词过宽、城市写法不一致或高德无匹配 |
| 向量接口返回 503 | 启动日志、Chroma 依赖和目录 | Chroma 未安装、目录不可写或初始化失败 |
| 向量接口返回 400 | `poi_group` 参数 | 只能使用 `attraction`、`hotel`、`meal` |
| 区县请求混入其他区 | `adcode` 是否传入 | 仅传城市只能做城市过滤，区县场景应携带 adcode |
| 图片返回 200 但 URL 为 null | 图片匹配结果 | 这是可接受的空结果，前端应显示占位或稍后重试 |
| 请求期间吞吐下降 | `asyncio.to_thread` 和下游超时 | 检查同步 HTTP 是否有合理 connect/read timeout |

## 8. 练习

1. 调用 `/api/poi/search?keywords=公园&city=广州`，找出响应中坐标如何从高德字符串变成 `Location`。
2. 分别用 `poi_group=meal`、`poi_group=hotel` 查询同一城市，比较过滤结果。
3. 传入 `poi_group=shopping`，确认响应是 400，并解释错误发生在路由还是向量存储层。
4. 不启动 Chroma 或让其目录不可写，调用 vector-search，设计一个客户端降级到 `/api/poi/search` 的流程。
5. 为同名景点请求 `/api/poi/photo`，分别传入城市和空城市，观察城市优先策略。

## 9. 检查清单

- [ ] 调用方使用完整 `/api/poi/...` 路径。
- [ ] 高德同步调用通过 `asyncio.to_thread()` 执行。
- [ ] 搜索请求显式传入正确城市，区县场景传入 adcode。
- [ ] `top_k` 位于 1–50，`poi_group` 使用白名单值。
- [ ] 调用方区分 400、500 和 503，并为 Chroma 503 准备降级方案。
- [ ] 图片接口允许 `photo_url` 为空，并提供前端占位体验。
- [ ] 不把 API key 放进 URL 分享、前端代码或日志。
- [ ] 关注高德超时配置，避免同步下游拖住整个请求。

## 10. 继续阅读

- `backend/app/api/main.py`：查看 `/api` 前缀、CORS 和 Chroma 启动预热。
- `backend/app/services/amap_service.py`：查看高德 REST 参数、坐标解析和错误检查。
- `backend/app/services/poi_vector_store.py`：查看城市键、POI 大类、adcode 和距离过滤。
- `backend/app/services/amap_photo_service.py`：查看图片匹配和域名处理。
- `backend/app/agents/tool_lib.py`：查看规划 Agent 如何把 POI 搜索包装成领域工具。
- `backend/app/services/trip_planning_service.py`：查看 POI 证据如何进入完整计划和定向修改流程。
