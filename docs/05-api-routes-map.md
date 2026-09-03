# 05：地图路由——把同步地图服务接入异步 API

本章阅读 `backend/app/api/routes/map.py`，并顺着调用链理解地图接口如何调用 `AmapService`。设想一个具体场景：用户在行程页输入“故宫”，想查看附近 POI；随后查看北京天气，再请求从酒店到景点的路线。三个动作都要访问外部地图服务，但不能因为高德接口的同步网络调用而阻塞 FastAPI 的事件循环。

## 1. 路由地图

`backend/app/api/main.py` 将本路由以 `/api` 挂载，模块中的 `APIRouter(prefix="/map")` 再追加 `/map`，所以完整路径如下：

| 方法 | 完整路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/map/poi` | 按关键词、城市搜索 POI |
| `GET` | `/api/map/weather` | 查询城市天气 |
| `POST` | `/api/map/route` | 规划两个地址之间的路线 |
| `GET` | `/api/map/route-geometry` | 返回道路或公共交通折线几何 |
| `GET` | `/api/map/health` | 查看 REST key 与 MCP 工具状态 |

这里的 `poi` 搜索请求使用查询参数；`route` 使用 Pydantic 请求体；`route-geometry` 也使用查询参数，但会先严格解析经纬度。

## 2. 场景一：搜索“故宫”

请求：

```http
GET /api/map/poi?keywords=故宫&city=北京&citylimit=true
```

路由的核心代码可以概括为：

```python
service = get_amap_service()
pois = await asyncio.to_thread(
    service.search_poi, keywords, city, citylimit
)
return POISearchResponse(
    success=True, message="POI搜索成功", data=pois
)
```

`keywords` 和 `city` 是必填参数，`citylimit` 默认 `true`。服务实例通过 `get_amap_service()` 获取，真正的高德请求由 `AmapService.search_poi()` 完成。该服务使用同步 `requests`，因此路由把它放进 `asyncio.to_thread()`；在等待高德返回时，事件循环仍能处理其他客户端请求。

成功响应符合 `POISearchResponse`：

```json
{
  "success": true,
  "message": "POI搜索成功",
  "data": [
    {
      "id": "B0FF...",
      "name": "故宫",
      "type": "风景名胜;公园广场",
      "address": "北京市东城区景山前街4号",
      "location": {"longitude": 116.397, "latitude": 39.918},
      "tel": "010-..."
    }
  ]
}
```

服务层负责检查 key、请求高德文本搜索接口、检查高德返回的 `status`，并把坐标字符串转换为 `Location`。没有合法坐标的条目会被跳过。调用方应显式传入城市，避免同名 POI 命中错误地区。

## 3. 场景二：查询天气

请求：

```http
GET /api/map/weather?city=北京
```

`get_weather()` 与 POI 搜索采用相同的线程卸载模式：

```python
weather_info = await asyncio.to_thread(
    service.get_weather, city
)
return WeatherResponse(
    success=True, message="天气查询成功", data=weather_info
)
```

`WeatherResponse.data` 是 `WeatherInfo` 列表，每项包含日期、白天/夜间天气、温度、风向和风力。模型中的温度校验器会移除 `°C`、`℃` 等符号，并尽量转换为整数；无法转换的值回退为 `0`。地图路由提供的是城市天气查询，旅行日期的精确天气补齐由旅行规划服务进一步处理。

## 4. 场景三：地址路线与地图折线

### 4.1 地址到地址的路线

请求体：

```http
POST /api/map/route
Content-Type: application/json

{
  "origin_address": "北京市朝阳区阜通东大街6号",
  "destination_address": "北京市海淀区上地十街10号",
  "origin_city": "北京",
  "destination_city": "北京",
  "route_type": "transit"
}
```

`RouteRequest` 的 `route_type` 默认是 `walking`，约定支持 `walking`、`driving`、`transit`。路由将字段逐一传给 `service.plan_route()`，再包装为 `RouteResponse`。`RouteInfo` 的重点字段是距离（米）、耗时（秒）、路线类型和可读描述。

路线服务可能启动同步 MCP/HTTP 客户端，同样必须通过 `asyncio.to_thread()` 执行：

```python
route_info = await asyncio.to_thread(
    service.plan_route,
    origin_address=request.origin_address,
    destination_address=request.destination_address,
    origin_city=request.origin_city,
    destination_city=request.destination_city,
    route_type=request.route_type,
)
```

### 4.2 前端地图需要真实折线

请求：

```http
GET /api/map/route-geometry?origin=116.397,39.918&destination=116.407,39.928&city=北京&route_type=driving
```

该接口的 `route_type` 通过正则限制为 `driving` 或 `transit`。`_parse_coordinate()` 按第一个逗号切分经度和纬度，检查经度位于 `[-180, 180]`、纬度位于 `[-90, 90]`，成功后构造 `Location`。格式错误或越界会立即返回 422，例如：

```json
{"detail": "origin 必须为 longitude,latitude"}
```

坐标合法后，服务调用 `get_route_geometry()`，成功结果统一包装为：

```json
{"success": true, "data": {"...": "道路或公共交通折线数据"}}
```

下游异常返回 502，表示路线几何的上游服务失败；参数解析产生的 422 会原样保留。

## 5. 健康检查与错误边界

`GET /api/map/health` 不请求具体 POI，而是读取服务状态：

```json
{
  "status": "healthy",
  "service": "map-service",
  "mcp_tools_count": 0,
  "rest_api_configured": true
}
```

`mcp_tools_count` 在 MCP 已初始化时读取可用工具数量，否则为 0；`rest_api_configured` 反映 REST API key 是否存在。

POI 搜索、天气和地址路线中，服务层抛出的异常会被路由捕获并转换为 500，同时记录简短错误日志。健康检查异常则返回 503。这样客户端可以把 422 看作请求格式问题，把 500 看作地图业务调用失败，把 502 看作路线几何上游异常，把 503 看作服务暂不可用。

## 6. 端到端流程

```text
浏览器
  -> GET /api/map/poi
  -> FastAPI Query 校验
  -> get_amap_service()
  -> asyncio.to_thread(AmapService.search_poi)
  -> 高德 REST
  -> POIInfo 列表
  -> POISearchResponse

浏览器地图
  -> GET /api/map/route-geometry
  -> 坐标/route_type 校验
  -> asyncio.to_thread(get_route_geometry)
  -> 高德路线服务或 MCP
  -> 折线几何
```

设计重点有三个：同步 SDK 与异步路由之间用线程隔离；输入校验尽量在边界完成；响应模型把外部服务结果稳定成前端可消费的结构。

## 7. 常见故障定位

| 现象 | 检查位置 | 处理建议 |
| --- | --- | --- |
| POI 或天气返回 500 | `AMAP_API_KEY`、高德响应、网络 | 检查 key、城市名称和下游超时 |
| route-geometry 返回 422 | `origin`、`destination`、`route_type` | 使用 `经度,纬度`，确认数值范围与类型 |
| route-geometry 返回 502 | 高德路线服务/MCP 日志 | 暂时显示直线或重试，避免伪造真实道路 |
| health 返回 503 | 服务初始化与配置 | 检查 REST key、MCP 依赖和环境变量 |
| 事件循环吞吐下降 | `asyncio.to_thread` 与同步调用 | 新增同步地图调用时沿用线程卸载，并配置合理超时 |

## 8. 练习

1. 分别调用 `citylimit=true` 和 `false`，比较高德返回范围。
2. 构造 `origin=116.397`、`origin=200,30`，观察两种 422 的区别。
3. 用 `route_type=walking` 调用 `/route-geometry`，解释为什么会被正则拒绝。
4. 给地图服务增加一个“指定日期天气”接口，思考应放在地图路由还是旅行规划服务。
5. 模拟 `AmapService.search_poi` 阻塞 5 秒，说明 `to_thread` 对事件循环的影响。

## 9. 检查清单

- [ ] 使用完整的 `/api/map/...` 路径。
- [ ] 同步高德/MCP 调用通过 `asyncio.to_thread()` 执行。
- [ ] POI 查询显式传入正确城市。
- [ ] 坐标始终使用 `longitude,latitude`，并检查范围。
- [ ] 客户端区分 422、500、502、503。
- [ ] 地图 key 只放服务端配置，不写入前端请求。
- [ ] 无路线几何时提供明确的重试或占位体验。

## 10. 继续阅读

- `backend/app/api/main.py`：查看 `/api` 挂载、CORS 和启动流程。
- `backend/app/services/amap_service.py`：查看高德 REST、MCP、天气和路线实现。
- `backend/app/models/schemas.py`：查看 `POIInfo`、`RouteRequest`、`WeatherInfo` 等模型。
- `backend/app/api/routes/poi.py`：比较直接 POI 服务与向量检索接口。
- `backend/app/api/routes/trip.py`：查看路线和天气如何进入完整旅行计划。
