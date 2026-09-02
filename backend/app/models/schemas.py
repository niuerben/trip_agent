"""数据模型定义"""

from typing import Any, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import date


# ============ 请求模型 ============

class Preference(BaseModel):
    """用户偏好，由 talk_agent 对话产出。"""
    prompt: str = Field(default="", description="用户偏好提示词")


class ChangeSelector(BaseModel):
    """LLM 指向当前计划节点的结构化选择器。"""
    name: Optional[str] = Field(default=None, description="节点名称或名称片段")
    semantic: Optional[str] = Field(default=None, description="节点语义类别，如寺庙、大学")
    day_index: Optional[int] = Field(default=None, ge=0, description="从 0 开始的行程日索引")


class ChangeTarget(BaseModel):
    """新增或替换时需要查询的真实 POI 目标。"""
    name: Optional[str] = Field(default=None, description="目标 POI 名称")
    semantic: Optional[str] = Field(default=None, description="目标 POI 类别，如大学、博物馆")


class ChangeOperation(BaseModel):
    """由 talk LLM 决定、由后端白名单执行的一项旅行计划操作。"""
    operation: Literal[
        "add_attraction",
        "delete_attraction",
        "replace_attraction",
        "update_day",
        "update_dates",
        "full_replan",
    ]
    selector: Optional[ChangeSelector] = None
    target: Optional[ChangeTarget] = None
    fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_date_update(self):
        if self.operation == "update_dates":
            for field in ("start_date", "end_date"):
                value = self.fields.get(field)
                if not isinstance(value, str) or len(value) != 10:
                    raise ValueError(f"update_dates.{field} 必须是 YYYY-MM-DD 字符串")
                try:
                    date.fromisoformat(value)
                except ValueError as error:
                    raise ValueError(f"update_dates.{field} 不是有效日期") from error
        return self


class ChangeSet(BaseModel):
    """一次对话产生的受控计划变更集合，禁止包含 SQL。"""
    operations: List[ChangeOperation] = Field(min_length=1)

class TripRequest(BaseModel):
    """
        旅行规划请求
        city: 目的城市
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        travel_days: 旅行天数
        transportation: 交通方式
        accommodation: 住宿偏好
        preferences: 旅行偏好标签
        free_text_input: 额外要求
    """
    city: str = Field(..., description="目的地城市", example="北京")
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD", example="2025-06-01")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD", example="2025-06-03")
    travel_days: int = Field(..., description="旅行天数", ge=1, le=30, example=3)
    transportation: str = Field(..., description="交通方式", example="公共交通")
    accommodation: str = Field(..., description="住宿偏好", example="经济型酒店")
    preferences: List[str] = Field(default=[], description="旅行偏好标签", example=["历史文化", "美食"])
    free_text_input: Optional[str] = Field(default="", description="额外要求", example="希望多安排一些博物馆")
    conversation_id: Optional[str] = Field(default=None, description="关联的行程对话ID")
    preference: Optional[Preference] = Field(default=None, description="talk_agent 提炼的用户偏好")
    current_plan: Optional[dict] = Field(default=None, description="当前旅行计划，用于定向修改")
    change_request: Optional[str] = Field(default="", description="用户要求修改的内容")
    change_set: Optional[ChangeSet] = Field(default=None, description="talk LLM 输出的结构化计划操作")
    
    class Config:
        json_schema_extra = {
            "example": {
                "city": "北京",
                "start_date": "2025-06-01",
                "end_date": "2025-06-03",
                "travel_days": 3,
                "transportation": "公共交通",
                "accommodation": "经济型酒店",
                "preferences": ["历史文化", "美食"],
                "free_text_input": "希望多安排一些博物馆",
                "conversation_id": "conversation_demo",
                "preference": {"prompt": "偏好自然风光和当地美食，节奏悠闲"},
                "change_request": "将第二天改为自然风光路线"
            }
        }


class TalkMessage(BaseModel):
    """单条对话消息"""
    role: str = Field(..., description="角色: user / assistant")
    content: str = Field(..., description="消息内容")


class TalkRequest(BaseModel):
    """talk_agent 对话请求"""
    conversation_id: Optional[str] = Field(default=None, description="所属行程对话ID，用于持久化聊天记录")
    city: Optional[str] = Field(default=None, description="当前旅行计划目的地，用于消解大学、公园等模糊地点")
    plan_context: Optional[str] = Field(default=None, description="当前行程摘要，供对话记忆和建议生成使用")
    preference: Optional[Preference] = Field(default=None, description="当前会话已持久化的长期偏好")
    messages: List[TalkMessage] = Field(default=[], description="历史对话")
    message: str = Field(..., description="用户本轮输入")


class ChatMessage(BaseModel):
    """持久化的聊天消息"""
    id: int = Field(..., description="消息ID")
    conversation_id: str = Field(..., description="所属行程对话ID")
    role: str = Field(..., description="角色: user / assistant")
    content: str = Field(..., description="消息内容")
    created_at: str = Field(..., description="创建时间(北京时间)")


class TalkResponse(BaseModel):
    """talk_agent 对话响应"""
    success: bool = Field(default=True, description="是否成功")
    reply: str = Field(default="", description="assistant 回复")
    intent: str = Field(default="chat", description="语义意图: chat / replan")
    change_request: Optional[str] = Field(default=None, description="提炼后的行程修改要求")
    change_set: Optional[ChangeSet] = Field(default=None, description="LLM 输出的结构化计划操作")
    top_suggestions: List[str] = Field(default_factory=list, description="基于当前会话记忆生成的 3 条后续建议")
    preference: Optional["Preference"] = Field(default=None, description="提炼出的偏好")
    done: bool = Field(default=False, description="偏好是否收集完成")
    messages: List[ChatMessage] = Field(default=[], description="持久化后的完整聊天记录")


class ChatHistoryResponse(BaseModel):
    """聊天历史响应"""
    success: bool = Field(default=True, description="是否成功")
    messages: List[ChatMessage] = Field(default=[], description="聊天记录")


class TalkSuggestionsRequest(BaseModel):
    """为已存在的会话恢复基于记忆的后续建议。"""
    conversation_id: str = Field(..., min_length=1, description="所属行程对话 ID")
    city: Optional[str] = Field(default=None, description="当前旅行计划目的地")
    plan_context: Optional[str] = Field(default=None, description="当前行程摘要")


class TalkSuggestionsResponse(BaseModel):
    """会话记忆生成的可点击建议。"""
    success: bool = Field(default=True, description="是否成功")
    top_suggestions: List[str] = Field(default_factory=list, description="3 条基于会话记忆的后续建议")


class POISearchRequest(BaseModel):
    """POI搜索请求"""
    keywords: str = Field(..., description="搜索关键词", example="故宫")
    city: str = Field(..., description="城市", example="北京")
    citylimit: bool = Field(default=True, description="是否限制在城市范围内")


class RouteRequest(BaseModel):
    """路线规划请求"""
    origin_address: str = Field(..., description="起点地址", example="北京市朝阳区阜通东大街6号")
    destination_address: str = Field(..., description="终点地址", example="北京市海淀区上地十街10号")
    origin_city: Optional[str] = Field(default=None, description="起点城市")
    destination_city: Optional[str] = Field(default=None, description="终点城市")
    route_type: str = Field(default="walking", description="路线类型: walking/driving/transit")


# ============ 响应模型 ============

class Location(BaseModel):
    """地理位置"""
    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")


class Attraction(BaseModel):
    """景点信息"""
    name: str = Field(..., description="景点名称")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    visit_duration: int = Field(..., description="建议游览时间(分钟)")
    description: str = Field(..., description="景点描述")
    category: Optional[str] = Field(default="景点", description="景点类别")
    rating: Optional[float] = Field(default=None, description="评分")
    photos: Optional[List[str]] = Field(default_factory=list, description="景点图片URL列表")
    poi_id: Optional[str] = Field(default="", description="POI ID")
    image_url: Optional[str] = Field(default=None, description="图片URL")
    ticket_price: int = Field(default=0, description="门票价格(元)")


class Meal(BaseModel):
    """餐饮信息"""
    type: str = Field(..., description="餐饮类型: breakfast/lunch/dinner/snack")
    name: str = Field(..., description="餐饮名称")
    address: Optional[str] = Field(default=None, description="地址")
    location: Optional[Location] = Field(default=None, description="经纬度坐标")
    description: Optional[str] = Field(default=None, description="描述")
    estimated_cost: int = Field(default=0, description="预估费用(元)")
    poi_id: Optional[str] = Field(default="", description="真实餐馆的高德 POI ID")


class Hotel(BaseModel):
    """酒店信息"""
    name: str = Field(..., description="酒店名称")
    address: str = Field(default="", description="酒店地址")
    location: Optional[Location] = Field(default=None, description="酒店位置")
    price_range: str = Field(default="", description="价格范围")
    rating: str = Field(default="", description="评分")
    distance: str = Field(default="", description="距离景点距离")
    type: str = Field(default="", description="酒店类型")
    estimated_cost: int = Field(default=0, description="预估费用(元/晚)")
    poi_id: Optional[str] = Field(default="", description="真实酒店的高德 POI ID")


class DayPlan(BaseModel):
    """单日行程"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_index: int = Field(..., description="第几天(从0开始)")
    description: str = Field(..., description="当日行程描述")
    transportation: str = Field(..., description="交通方式")
    accommodation: str = Field(..., description="住宿")
    hotel: Optional[Hotel] = Field(default=None, description="推荐酒店")
    attractions: List[Attraction] = Field(default=[], description="景点列表")
    meals: List[Meal] = Field(default=[], description="餐饮列表")


class WeatherInfo(BaseModel):
    """天气信息"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_weather: str = Field(default="", description="白天天气")
    night_weather: str = Field(default="", description="夜间天气")
    day_temp: Union[int, str] = Field(default=0, description="白天温度")
    night_temp: Union[int, str] = Field(default=0, description="夜间温度")
    wind_direction: str = Field(default="", description="风向")
    wind_power: str = Field(default="", description="风力")
    source: str = Field(default="高德", description="天气数据来源")

    @field_validator('day_temp', 'night_temp', mode='before')
    @classmethod
    def parse_temperature(cls, v):
        """解析温度,移除°C等单位"""
        if isinstance(v, str):
            # 移除°C, ℃等单位符号
            v = v.replace('°C', '').replace('℃', '').replace('°', '').strip()
            try:
                return int(v)
            except ValueError:
                return 0
        return v


class Budget(BaseModel):
    """预算信息"""
    total_attractions: int = Field(default=0, description="景点门票总费用")
    total_hotels: int = Field(default=0, description="酒店总费用")
    total_meals: int = Field(default=0, description="餐饮总费用")
    total_transportation: int = Field(default=0, description="交通总费用")
    total: int = Field(default=0, description="总费用")


class TripPlan(BaseModel):
    """旅行计划"""
    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    days: List[DayPlan] = Field(..., description="每日行程")
    weather_info: List[WeatherInfo] = Field(default=[], description="天气信息")
    overall_suggestions: str = Field(..., description="总体建议")
    budget: Optional[Budget] = Field(default=None, description="预算信息")


class TripPlanResponse(BaseModel):
    """旅行计划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[TripPlan] = Field(default=None, description="旅行计划数据")


class POIInfo(BaseModel):
    """POI信息"""
    id: str = Field(..., description="POI ID")
    name: str = Field(..., description="名称")
    type: str = Field(..., description="类型")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    tel: Optional[str] = Field(default=None, description="电话")


class POISearchResponse(BaseModel):
    """POI搜索响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[POIInfo] = Field(default=[], description="POI列表")


class RouteInfo(BaseModel):
    """路线信息"""
    distance: float = Field(..., description="距离(米)")
    duration: int = Field(..., description="时间(秒)")
    route_type: str = Field(..., description="路线类型")
    description: str = Field(..., description="路线描述")


class RouteResponse(BaseModel):
    """路线规划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[RouteInfo] = Field(default=None, description="路线信息")


class WeatherResponse(BaseModel):
    """天气查询响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[WeatherInfo] = Field(default=[], description="天气信息")


# ============ 错误响应 ============

class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = Field(default=False, description="是否成功")
    message: str = Field(..., description="错误消息")
    error_code: Optional[str] = Field(default=None, description="错误代码")

