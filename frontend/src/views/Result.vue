<template>
  <div class="result-page">
    <div ref="mapContainer" class="map-canvas" aria-label="旅行路线地图"></div>
    <div v-if="!mapReady" class="map-fallback" aria-hidden="true">
      <span class="map-grid"></span>
      <span class="map-fallback-label">正在加载路线地图</span>
    </div>

    <div class="map-toolbar" aria-label="地图状态">
      <span class="map-live-dot"></span>
      <span>{{ mapRouteNodes.length ? `${mapRouteNodes.length} 个路线节点` : '等待旅行计划' }}</span>
      <span v-if="mapRouteStatus" class="map-route-status">{{ mapRouteStatus }}</span>
      <span v-if="plan?.days?.length" class="map-day-legend">
        <span v-for="(_, index) in plan.days" :key="index"><i :style="{ backgroundColor: routeDayColor(index) }"></i>第{{ index + 1 }}天</span>
      </span>
      <span v-if="focusedNode?.location" class="map-focus-info">
        {{ focusedNode.name }} · {{ focusedNode.location.longitude.toFixed(6) }}, {{ focusedNode.location.latitude.toFixed(6) }}
      </span>
    </div>

    <aside class="conversation-panel conversation-float" :class="{ 'conversation-collapsed': chatCollapsed }">
      <div class="conversation-panel-header">
        <div class="chat-heading">
          <h2>我要改计划</h2>
        </div>
        <div class="chat-header-actions">
          <span class="conversation-status">● 在线</span>
          <button
            class="chat-collapse-button"
            type="button"
            :aria-label="chatCollapsed ? '展开聊天' : '折叠聊天'"
            :title="chatCollapsed ? '展开聊天' : '折叠聊天'"
            @click="chatCollapsed = !chatCollapsed"
          >
            <span aria-hidden="true">{{ chatCollapsed ? '⌁' : '—' }}</span>
          </button>
        </div>
      </div>
      <div v-if="!chatCollapsed" class="conversation-messages" aria-live="polite">
        <div class="assistant-message">
          <strong>行旅助手</strong>
          <p>{{ plan ? `已为你整理${plan.city}的旅行计划，可以继续告诉我想调整的内容。` : '填写旅行信息后，我会帮你安排景点、餐饮、交通和住宿。' }}</p>
        </div>
        <div
          v-for="message in chatMessages"
          :key="message.id"
          :class="message.role === 'user' ? 'user-message' : 'assistant-message'"
        >
          <template v-if="message.role === 'assistant'">
            <strong>行旅助手</strong>
            <p>{{ message.content }}</p>
          </template>
          <template v-else>{{ message.content }}</template>
        </div>
        <div v-if="chatSending" class="assistant-message">
          <strong>行旅助手</strong>
          <p>正在思考…</p>
        </div>
        <div v-if="plan && !chatSending" class="topk-suggestions" aria-label="快捷建议">
          <button
            v-for="suggestion in topKSuggestions"
            :key="suggestion"
            type="button"
            class="topk-suggestion"
            @click="chatInput = suggestion"
          >{{ suggestion }}</button>
        </div>
      </div>
      <form v-if="!chatCollapsed" class="conversation-composer" @submit.prevent="sendMessage">
        <textarea
          v-model="chatInput"
          rows="2"
          placeholder="告诉我想怎么调整行程"
          aria-label="行程对话输入框"
        />
        <button type="submit" :disabled="!chatInput.trim() || chatSending">发送</button>
      </form>
    </aside>

    <section ref="manualPanel" class="route-panel" :class="{ 'route-panel-collapsed': manualCollapsed }">
      <button
        v-if="manualCollapsed"
        type="button"
        class="route-expand-button"
        aria-label="展开旅游路线"
        title="展开旅游路线"
        @click="manualCollapsed = false"
      >‹</button>
      <template v-else>
        <div class="manual-toolbar">
          <div>
            <p class="eyebrow">旅游路线</p>
            <h2>路线安排</h2>
          </div>
          <div class="manual-toolbar-actions">
            <button class="route-collapse-button" type="button" aria-label="收缩旅游路线" title="收缩旅游路线" @click="manualCollapsed = true">›</button>
            <button class="pdf-button" type="button" :disabled="pdfExporting" @click="downloadPdf">
              {{ pdfExporting ? '生成中…' : '⇩ 下载 PDF' }}
            </button>
          </div>
        </div>

      <template v-if="plan">
        <header class="result-header">
          <div>
            <p class="eyebrow">你的专属旅行路线</p>
            <h1>{{ plan.city }} · {{ plan.days?.length || 0 }}天</h1>
            <p class="date-range">{{ plan.start_date }} 至 {{ plan.end_date }}</p>
          </div>
          <button class="replan-button" type="button" @click="startNewPlan">重新规划</button>
        </header>

        <section class="route-summary">
          <div><span>路线节点</span><strong>{{ routeNodes.length }}</strong></div>
          <div><span>旅行天数</span><strong>{{ plan.days?.length || 0 }} 天</strong></div>
          <div v-if="plan.budget"><span>预计总预算</span><strong>¥{{ plan.budget.total }}</strong></div>
        </section>

        <section class="route-days">
          <div class="section-heading">
            <button class="route-days-title" type="button" @click="showAllRouteDays">
              每日路线
            </button>
          </div>
          <article
            v-for="(day, dayIndex) in plan.days"
            :key="day.day_index"
            class="day-route"
            :class="{ 'day-route-selected': selectedRouteDay === dayIndex }"
            role="button"
            tabindex="0"
            :aria-pressed="selectedRouteDay === dayIndex"
            @click="showRouteDay(dayIndex)"
            @keydown.enter.prevent="showRouteDay(dayIndex)"
            @keydown.space.prevent="showRouteDay(dayIndex)"
          >
            <div class="day-route-header">
              <span class="day-number">{{ dayIndex + 1 }}</span>
              <div>
                <h3>第 {{ dayIndex + 1 }} 天</h3>
                <p>{{ day.date }} · {{ day.description }}</p>
              </div>
              <span class="transport">{{ day.transportation }}</span>
            </div>
            <div class="route-track">
              <div
                v-for="node in routeNodesForDay(dayIndex)"
                :key="node.id"
                class="route-node"
                :class="[
                  `route-node-${node.type}`,
                  {
                    'route-node-fixed': node.type === 'hotel',
                    'route-node-drop-before': dragOverNodeId === node.id && dragOverPosition === 'before',
                    'route-node-drop-after': dragOverNodeId === node.id && dragOverPosition === 'after',
                  },
                ]"
                :draggable="node.type !== 'hotel'"
                :data-node-id="node.id"
                :data-node-type="node.type"
                :data-route-role="node.routeRole"
                @dragstart.stop="startNodeDrag(node.id)"
                @dragover.stop.prevent="updateDropPosition(node.id, $event)"
                @dragleave="clearDropPosition(node.id)"
                @drop.stop="dropNode(node.id, $event)"
                @dragend="finishNodeDrag"
                @click.stop="focusNodeOnMap(node)"
              >
                <span class="node-marker">{{ nodeIcon(node.type) }}</span>
                <div class="node-content">
                  <div class="node-title-row">
                    <strong>{{ node.name }}</strong>
                    <span class="node-actions">
                      <button
                        v-if="node.type !== 'hotel'"
                        class="node-delete"
                        type="button"
                        :aria-label="`删除${node.name}`"
                        title="删除节点"
                        @click.stop="requestNodeDeletion(node)"
                      >×</button>
                      <span v-if="node.type !== 'hotel'" class="drag-handle" aria-hidden="true">⠿</span>
                      <span v-else class="fixed-label">固定</span>
                    </span>
                  </div>
                  <p>{{ node.description }}</p>
                  <small v-if="node.address">{{ node.address }}</small>
                  <small v-if="node.type === 'meal' && node.cost !== undefined">{{ node.mealType }} · ¥{{ node.cost }}</small>
                  <small v-if="node.type === 'hotel' && node.price">{{ node.hotelType }} · {{ node.price }}</small>
                </div>
              </div>
              <div v-if="!routeNodesForDay(dayIndex).length" class="route-empty">当天暂无路线节点</div>
            </div>
          </article>
        </section>

        <section v-if="plan.days?.length" class="weather-section">
          <div class="section-heading"><h2>天气信息</h2><span class="map-hint">逐日预报</span></div>
          <div class="weather-row">
            <article v-for="card in travelWeatherCards" :key="card.date" class="weather-item">
              <strong>{{ card.date }}</strong>
              <template v-if="card.weather">
                <span>☀️ {{ card.weather.day_weather }} {{ card.weather.day_temp }}°</span>
                <span>🌙 {{ card.weather.night_weather }} {{ card.weather.night_temp }}°</span>
                <small>{{ card.weather.wind_direction }} {{ card.weather.wind_power }} · {{ card.weather.source || '高德' }}</small>
              </template>
              <template v-else>
                <span class="weather-unavailable">高德预报暂未覆盖</span>
                <small>该日期超出当前预报窗口</small>
              </template>
            </article>
          </div>
        </section>
      </template>

      <a-empty v-else description="暂未找到旅行计划">
        <a-button type="primary" @click="startNewPlan">开始规划</a-button>
      </a-empty>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'
import AMapLoader from '@amap/amap-jsapi-loader'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Location, TripFormData, TripPlan } from '@/types'
import { enrichTripPlanImages, generateTripPlan, getChatHistory, getChatSuggestions, getRouteGeometry, sendChatMessage, type RouteGeometrySegment } from '@/services/api'
import { clearCurrentConversationId, clearLegacyPlan, createConversation, getConversation, getCurrentConversationId, loadLegacyPlan, setCurrentConversationId, updateConversation } from '@/services/conversations'

const router = useRouter()
const route = useRoute()
const plan = ref<TripPlan | null>(null)
const manualPanel = ref<HTMLElement | null>(null)
const mapContainer = ref<HTMLElement | null>(null)
const mapReady = ref(false)
const routeNodes = ref<RouteNode[]>([])
const selectedRouteDay = ref<number | null>(null)
const mapRouteNodes = computed(() => (
  selectedRouteDay.value === null
    ? routeNodes.value
    : routeNodes.value.filter((node) => node.dayIndex === selectedRouteDay.value)
))
const pdfExporting = ref(false)
const chatInput = ref('')
const chatSending = ref(false)
const chatCollapsed = ref(false)
const manualCollapsed = ref(false)
const conversationId = ref<string | null>(null)
const chatMessages = ref<Array<{ id: number | string; role: 'user' | 'assistant'; content: string }>>([])
const focusedNode = ref<RouteNode | null>(null)
const topKSuggestions = ref<string[]>([])
// 历史会话可能包含旧版本透传的“本日预报”；界面只渲染实际行程日对应的天气。
const travelWeather = computed(() => {
  if (!plan.value) return []
  const travelDates = new Set(plan.value.days.map((day) => day.date))
  return (plan.value.weather_info || []).filter((weather) => travelDates.has(weather.date))
})
const travelWeatherCards = computed(() => {
  if (!plan.value) return []
  const weatherByDate = new Map(travelWeather.value.map((weather) => [weather.date, weather]))
  return plan.value.days.map((day) => ({
    date: day.date,
    weather: weatherByDate.get(day.date),
  }))
})
const planContext = computed(() => {
  if (!plan.value) return ''
  const days = plan.value.days.map((day) => {
    const attractions = day.attractions.map((item) => item.name).join('、') || '暂无景点'
    return `第${day.day_index + 1}天：${attractions}`
  }).join('；')
  return `${plan.value.city}，${days}`
})
let nextMessageId = 1
let loadVersion = 0
let mapInstance: any = null
let mapMarkers: any[] = []
let mapPolylines: any[] = []
let mapRouteServices: any[] = []
let activeGuideMarker: any = null
let activeGuideFrame: number | null = null
let activeGuidePathId: string | null = null
let activeGuidePolylines: any[] = []
const routePolylineBaseStyles = new Map<any, { strokeWeight: number; strokeOpacity: number }>()
let mapRenderVersion = 0
let amapNamespace: any = null
const mapRouteStatus = ref('')
const routeDayColors = ['#1677ff', '#f97316', '#16a34a', '#d946ef', '#0891b2']
const locationEnrichmentInFlight = new Set<string>()
const locationEnrichmentCompleted = new Set<string>()

interface RouteNode {
  id: string
  dayIndex: number
  type: 'hotel' | 'attraction' | 'meal'
  name: string
  description: string
  address?: string
  location?: Location
  cost?: number
  price?: string
  mealType?: string
  hotelType?: string
  sourceIndex?: number
  routeRole?: 'start' | 'end'
}

function hasMapLocation(location?: Location): boolean {
  return Boolean(
    location
    && Number.isFinite(location.longitude)
    && Number.isFinite(location.latitude)
    && Math.abs(location.longitude) <= 180
    && Math.abs(location.latitude) <= 90,
  )
}

function rebuildRouteNodes(value: TripPlan | null) {
  if (!value) {
    routeNodes.value = []
    return
  }

  const nodes: RouteNode[] = []
  value.days.forEach((day, dayIndex) => {
    const dayNodes: RouteNode[] = []
    const makeHotelNode = (routeRole: 'start' | 'end'): RouteNode | null => {
      if (!day.hotel || !hasMapLocation(day.hotel.location)) return null
      return {
        id: `day-${dayIndex}-hotel-${routeRole}`,
        dayIndex,
        type: 'hotel',
        name: `${routeRole === 'start' ? '出发' : '返程'} · ${day.hotel.name}`,
        description: routeRole === 'start' ? '当天从酒店出发' : '当天返回酒店休息',
        address: day.hotel.address,
        location: day.hotel.location,
        price: day.hotel.price_range,
        hotelType: day.hotel.type,
        routeRole,
      }
    }
    const startHotel = makeHotelNode('start')
    if (startHotel) dayNodes.push(startHotel)
    const addMealNodes = (meals: typeof day.meals) => {
      meals.filter((meal) => hasMapLocation(meal.location)).forEach((meal) => {
        const sourceIndex = day.meals.indexOf(meal)
        dayNodes.push({
          id: `day-${dayIndex}-meal-${sourceIndex}`,
          dayIndex,
          type: 'meal',
          name: meal.name,
          description: meal.description || meal.address || '当地特色餐饮',
          address: meal.address,
          location: meal.location,
          cost: meal.estimated_cost,
          mealType: meal.type,
          sourceIndex,
        })
      })
    }
    const breakfast = day.meals.filter((meal) => meal.type === 'breakfast')
    const lunch = day.meals.filter((meal) => meal.type === 'lunch')
    const dinner = day.meals.filter((meal) => meal.type === 'dinner')
    const otherMeals = day.meals.filter((meal) => !['breakfast', 'lunch', 'dinner'].includes(meal.type))
    addMealNodes(breakfast)
    const attractionNodes = day.attractions
      .filter((attraction) => hasMapLocation(attraction.location))
      .map((attraction, attractionIndex) => ({
        id: `day-${dayIndex}-attraction-${attractionIndex}`,
        dayIndex,
        type: 'attraction',
        name: attraction.name,
        description: `${attraction.visit_duration} 分钟 · ${attraction.description}`,
        address: attraction.address,
        location: attraction.location,
        sourceIndex: attractionIndex,
      } satisfies RouteNode))
    // 同日景点按与上一站的空间距离排序，并以午餐把上午/下午行程自然分开。
    const nearbyAttractions = orderNodesByProximity(
      attractionNodes,
      dayNodes[dayNodes.length - 1]?.location,
    )
    const morningCount = Math.ceil(nearbyAttractions.length / 2)
    dayNodes.push(...nearbyAttractions.slice(0, morningCount))
    addMealNodes(lunch)
    dayNodes.push(...orderNodesByProximity(
      nearbyAttractions.slice(morningCount),
      dayNodes[dayNodes.length - 1]?.location,
    ))
    addMealNodes(dinner)
    addMealNodes(otherMeals)
    const endHotel = makeHotelNode('end')
    if (endHotel) dayNodes.push(endHotel)
    nodes.push(...dayNodes)
  })
  routeNodes.value = nodes
  const schoolNodes = nodes.filter((node) => /大学|学院|学校|校园/.test(node.name))
  if (import.meta.env.DEV && schoolNodes.length) {
    console.info('地图节点坐标', JSON.stringify(schoolNodes.map((node) => ({
      name: node.name,
      address: node.address,
      location: node.location,
    }))))
  }
}

function planarDistance(left?: Location, right?: Location): number {
  if (!left || !right) return Number.POSITIVE_INFINITY
  const latitudeScale = Math.cos(((left.latitude + right.latitude) / 2) * Math.PI / 180)
  const longitude = (left.longitude - right.longitude) * latitudeScale
  const latitude = left.latitude - right.latitude
  return longitude * longitude + latitude * latitude
}

function orderNodesByProximity(nodes: RouteNode[], anchor?: Location): RouteNode[] {
  const remaining = [...nodes]
  const ordered: RouteNode[] = []
  let current = anchor
  while (remaining.length) {
    const nextIndex = current
      ? remaining.reduce((bestIndex, candidate, index) => (
        planarDistance(candidate.location, current) < planarDistance(remaining[bestIndex].location, current)
          ? index
          : bestIndex
      ), 0)
      : 0
    const [next] = remaining.splice(nextIndex, 1)
    ordered.push(next)
    current = next.location
  }
  return ordered
}

function routeNodesForDay(dayIndex: number) {
  return routeNodes.value.filter((node) => node.dayIndex === dayIndex)
}

function showRouteDay(dayIndex: number) {
  if (selectedRouteDay.value === dayIndex) return
  selectedRouteDay.value = dayIndex
  renderMap()
}

function showAllRouteDays() {
  if (selectedRouteDay.value === null) return
  selectedRouteDay.value = null
  renderMap()
}

function routeDayColor(dayIndex: number): string {
  return routeDayColors[dayIndex % routeDayColors.length]
}

function buildMarkerOffsets(nodes: RouteNode[]): Map<string, { x: number; y: number }> {
  const groups = new Map<string, RouteNode[]>()
  nodes.forEach((node) => {
    const key = `${node.location!.longitude.toFixed(5)},${node.location!.latitude.toFixed(5)}`
    const group = groups.get(key) || []
    group.push(node)
    groups.set(key, group)
  })
  const offsets = new Map<string, { x: number; y: number }>()
  groups.forEach((group) => {
    if (group.length === 1) {
      offsets.set(group[0].id, { x: 0, y: 0 })
      return
    }
    group.forEach((node, index) => {
      const ring = Math.floor(index / 6)
      const angle = -Math.PI / 2 + (index % 6) * (Math.PI * 2 / Math.min(group.length, 6))
      const radius = 20 + ring * 14
      offsets.set(node.id, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius })
    })
  })
  return offsets
}

function nodeIcon(type: RouteNode['type']) {
  return type === 'hotel' ? 'H' : type === 'meal' ? '♨' : '●'
}

let draggingNodeId: string | null = null
const dragOverNodeId = ref<string | null>(null)
const dragOverPosition = ref<'before' | 'after' | null>(null)
function startNodeDrag(id: string) {
  if (routeNodes.value.find((node) => node.id === id)?.type === 'hotel') return
  draggingNodeId = id
}

function finishNodeDrag() {
  draggingNodeId = null
  dragOverNodeId.value = null
  dragOverPosition.value = null
}

function focusNodeOnMap(node: RouteNode) {
  if (!mapInstance || !node.location) return
  focusedNode.value = node
  console.info('双击定位节点', JSON.stringify({
    name: node.name,
    address: node.address,
    location: node.location,
  }))
  mapInstance.setZoomAndCenter(16, [node.location.longitude, node.location.latitude], false, 500)
}

function updateDropPosition(targetId: string, event: DragEvent) {
  if (!draggingNodeId || draggingNodeId === targetId) return
  const target = routeNodes.value.find((node) => node.id === targetId)
  if (!target || target.type === 'hotel') return
  const element = event.currentTarget as HTMLElement | null
  if (!element) return
  const bounds = element.getBoundingClientRect()
  dragOverNodeId.value = targetId
  dragOverPosition.value = event.clientY >= bounds.top + bounds.height / 2 ? 'after' : 'before'
}

function clearDropPosition(targetId: string) {
  if (dragOverNodeId.value !== targetId) return
  dragOverNodeId.value = null
  dragOverPosition.value = null
}

function dropNode(targetId: string, event: DragEvent) {
  if (!draggingNodeId || draggingNodeId === targetId) return
  updateDropPosition(targetId, event)
  const sourceIndex = routeNodes.value.findIndex((node) => node.id === draggingNodeId)
  let targetIndex = routeNodes.value.findIndex((node) => node.id === targetId)
  if (sourceIndex < 0 || targetIndex < 0) return
  const source = routeNodes.value[sourceIndex]
  const target = routeNodes.value[targetIndex]
  if (source.type === 'hotel' || target.type === 'hotel') return
  if (source.dayIndex !== target.dayIndex) return
  const insertAfter = dragOverPosition.value === 'after'
  const [moved] = routeNodes.value.splice(sourceIndex, 1)
  targetIndex = routeNodes.value.findIndex((node) => node.id === targetId)
  routeNodes.value.splice(targetIndex + (insertAfter ? 1 : 0), 0, moved)
  finishNodeDrag()
  renderMap()
}

function requestNodeDeletion(node: RouteNode) {
  if (!plan.value || node.type === 'hotel' || node.sourceIndex === undefined) return
  if (!window.confirm(`确认从第 ${node.dayIndex + 1} 天路线中删除“${node.name}”吗？`)) return
  const day = plan.value.days[node.dayIndex]
  if (!day) return
  if (node.type === 'meal') {
    day.meals.splice(node.sourceIndex, 1)
  } else {
    day.attractions.splice(node.sourceIndex, 1)
  }
  if (focusedNode.value?.id === node.id) focusedNode.value = null
  if (conversationId.value) updateConversation(conversationId.value, plan.value)
}

async function initMap() {
  if (!mapContainer.value) return
  const key = import.meta.env.VITE_AMAP_WEB_JS_KEY || import.meta.env.VITE_AMAP_WEB_KEY
  if (!key) return

  try {
    amapNamespace = await AMapLoader.load({
      key,
      version: '2.0',
      plugins: ['AMap.Scale', 'AMap.ToolBar'],
    })
    mapInstance = new amapNamespace.Map(mapContainer.value, {
      zoom: 11,
      resizeEnable: true,
      viewMode: '2D',
      mapStyle: 'amap://styles/normal',
    })
    mapInstance.addControl(new amapNamespace.Scale())
    mapInstance.addControl(new amapNamespace.ToolBar({ position: 'RB' }))
    mapReady.value = true
    renderMap()
  } catch (error) {
    console.warn('高德地图加载失败:', error)
  }
}

function clearRouteOverlays() {
  stopRouteGuideCar()
  mapPolylines.forEach((polyline) => polyline.setMap(null))
  mapPolylines = []
  routePolylineBaseStyles.clear()
  mapRouteServices.forEach((service) => service.clear?.())
  mapRouteServices = []
}

async function renderMap() {
  if (!mapInstance || !amapNamespace) return
  const renderVersion = ++mapRenderVersion
  mapMarkers.forEach((marker) => marker.setMap(null))
  mapMarkers = []
  clearRouteOverlays()

  const locatedNodes = mapRouteNodes.value.filter((node) => node.location)
  if (!locatedNodes.length) {
    mapRouteStatus.value = ''
    return
  }

  const markerOffsets = buildMarkerOffsets(locatedNodes)
  locatedNodes.forEach((node, index) => {
    if (import.meta.env.DEV && /大学|学院|学校|校园/.test(node.name)) {
      console.info('地图 Marker 坐标', JSON.stringify({
        name: node.name,
        address: node.address,
        location: node.location,
      }))
    }
    const marker = new amapNamespace.Marker({
      position: [node.location!.longitude, node.location!.latitude],
      title: `${index + 1}. ${node.name}`,
      draggable: true,
      anchor: 'center',
      offset: new amapNamespace.Pixel(
        markerOffsets.get(node.id)?.x || 0,
        markerOffsets.get(node.id)?.y || 0,
      ),
      zIndex: 100 + index,
      content: `<span style="display:grid;place-items:center;width:29px;height:29px;border:3px solid #fff;border-radius:50%;background:${routeDayColor(node.dayIndex)};box-shadow:0 2px 7px rgba(30,55,80,.38);color:#fff;font:700 12px/1 system-ui,sans-serif">${index + 1}</span>`,
    })
    marker.on('dragend', (event: any) => {
      const current = routeNodes.value.find((item) => item.id === node.id)
      if (!current) return
      current.location = {
        longitude: event.lnglat.getLng(),
        latitude: event.lnglat.getLat(),
      }
      renderMap()
    })
    marker.setMap(mapInstance)
    mapMarkers.push(marker)
  })
  mapInstance.setFitView(mapMarkers, false, [100, 100, 100, 100])
  const dailyRoutes = (plan.value?.days || [])
    .filter((_, dayIndex) => selectedRouteDay.value === null || selectedRouteDay.value === dayIndex)
    .map((day) => ({
      dayIndex: day.day_index,
      city: plan.value?.city || '',
      useTransit: /公共交通|地铁|公交/.test(day.transportation || ''),
      nodes: routeNodesForDay(day.day_index),
    }))
    .filter((route) => route.nodes.length >= 2)
  if (!dailyRoutes.length) {
    mapRouteStatus.value = '当天节点不足，未绘制道路路线'
    return
  }
  const routeLegs = dailyRoutes.flatMap((route) => route.nodes.slice(1).map((node, index) => ({
    ...route,
    origin: route.nodes[index],
    destination: node,
  })))
  mapRouteStatus.value = `正在绘制 ${routeLegs.length} 段道路${routeLegs.some((leg) => leg.useTransit) ? '和地铁/公交' : ''}路线…`
  const completed = await Promise.all(routeLegs.map((leg) => drawRouteLeg(leg, renderVersion)))
  if (renderVersion !== mapRenderVersion) return
  const roadCount = completed.filter((result) => result.road).length
  const transitCount = completed.filter((result) => result.transit).length
  mapRouteStatus.value = roadCount
    ? `已绘制 ${roadCount}/${routeLegs.length} 段道路${transitCount ? ` · ${transitCount} 段地铁/公交` : ''} · 点击路线查看行进方向`
    : '道路路线暂不可用，仅显示地点标记'
}

function addGeometrySegments(
  segments: RouteGeometrySegment[],
  layer: 'road' | 'transit',
  dayIndex: number,
  onClick?: () => void,
): any[] {
  const polylines: any[] = []
  segments.forEach((segment) => {
    if (segment.points.length < 2) return
    const strokeWeight = layer === 'road' ? 8 : (segment.kind === 'subway' ? 10 : 7)
    const strokeOpacity = layer === 'road' ? 0.78 : 0.92
    const polyline = new amapNamespace.Polyline({
      path: segment.points,
      // 颜色仅表达日期；所有路线均用实线与连续箭头表达行进方向。
      strokeColor: routeDayColor(dayIndex),
      strokeWeight,
      strokeOpacity,
      strokeStyle: 'solid',
      showDir: true,
      isOutline: true,
      borderWeight: layer === 'road' ? 2 : 3,
      outlineColor: '#ffffff',
      lineJoin: 'round',
      lineCap: 'round',
      cursor: 'pointer',
      zIndex: layer === 'road' ? 20 : 30,
    })
    routePolylineBaseStyles.set(polyline, { strokeWeight, strokeOpacity })
    polyline.on('click', () => onClick?.())
    polyline.setMap(mapInstance)
    mapPolylines.push(polyline)
    polylines.push(polyline)
  })
  return polylines
}

function routeGuideCarContent(dayIndex: number): string {
  const color = routeDayColor(dayIndex)
  return `<span style="display:block;width:34px;height:44px;filter:drop-shadow(0 3px 4px rgba(28,46,63,.35))" title="第${dayIndex + 1}天路线方向"><svg width="34" height="44" viewBox="0 0 34 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M10 4.5C10.8 2.2 13 1 15.4 1h3.2C21 1 23.2 2.2 24 4.5l2.5 7.3c2.2 1 3.5 3.1 3.5 5.5v17.2c0 2.5-2 4.5-4.5 4.5h-17C6 39 4 37 4 34.5V17.3c0-2.4 1.3-4.5 3.5-5.5L10 4.5Z" fill="${color}" stroke="#fff" stroke-width="2"/><path d="m11.2 7.2-1.5 6.1h14.6l-1.5-6.1c-.4-1.3-1.5-2.2-2.9-2.2h-5.8c-1.4 0-2.5.9-2.9 2.2Z" fill="#dff3ff"/><rect x="9" y="18" width="16" height="10" rx="3" fill="#fff" fill-opacity=".2"/><circle cx="10" cy="33" r="2.3" fill="#fff"/><circle cx="24" cy="33" r="2.3" fill="#fff"/><rect x="8" y="39" width="6" height="3" rx="1.5" fill="#24384a"/><rect x="20" y="39" width="6" height="3" rx="1.5" fill="#24384a"/><text x="17" y="25.5" text-anchor="middle" fill="#fff" font-size="9" font-family="system-ui,sans-serif" font-weight="700">${dayIndex + 1}</text></svg></span>`
}

function normalizeRoutePath(points: [number, number][]): [number, number][] {
  return points.filter((point, index) => {
    const previous = points[index - 1]
    return !previous || previous[0] !== point[0] || previous[1] !== point[1]
  })
}

function routePathLengthKm(path: [number, number][]): number {
  return path.slice(1).reduce((total, point, index) => {
    const previous = path[index]
    const latitudeScale = Math.cos(((previous[1] + point[1]) / 2) * Math.PI / 180)
    const longitudeKm = (point[0] - previous[0]) * 111.32 * latitudeScale
    const latitudeKm = (point[1] - previous[1]) * 110.57
    return total + Math.hypot(longitudeKm, latitudeKm)
  }, 0)
}

function stopRouteGuideCar() {
  if (activeGuideFrame !== null) {
    window.cancelAnimationFrame(activeGuideFrame)
    activeGuideFrame = null
  }
  activeGuideMarker?.setMap(null)
  activeGuideMarker = null
  activeGuidePathId = null
  activeGuidePolylines.forEach((polyline) => {
    const baseStyle = routePolylineBaseStyles.get(polyline)
    if (baseStyle) polyline.setOptions(baseStyle)
  })
  activeGuidePolylines = []
}

function playRouteGuideCar(target: {
  id: string
  dayIndex: number
  origin: RouteNode
  destination: RouteNode
  path: [number, number][]
  polylines: any[]
}) {
  const path = normalizeRoutePath(target.path)
  if (!mapInstance || !amapNamespace || path.length < 2) return

  stopRouteGuideCar()
  activeGuidePathId = target.id
  activeGuidePolylines = target.polylines
  activeGuidePolylines.forEach((polyline) => {
    const baseStyle = routePolylineBaseStyles.get(polyline)
    if (!baseStyle) return
    polyline.setOptions({
      strokeWeight: baseStyle.strokeWeight + 3,
      strokeOpacity: 1,
    })
  })

  const marker = new amapNamespace.Marker({
    position: path[0],
    title: `${target.origin.name} → ${target.destination.name}`,
    anchor: 'center',
    content: routeGuideCarContent(target.dayIndex),
    zIndex: 90,
  })
  marker.setMap(mapInstance)
  activeGuideMarker = marker
  mapRouteStatus.value = `正在演示：${target.origin.name} → ${target.destination.name}`

  const cumulativeDistances = [0]
  for (let index = 1; index < path.length; index += 1) {
    cumulativeDistances.push(cumulativeDistances[index - 1] + routePathLengthKm([path[index - 1], path[index]]))
  }
  const totalDistance = cumulativeDistances[cumulativeDistances.length - 1]
  // 车辆演示速度降为原来的一半，给用户足够时间辨认路线方向。
  const duration = Math.round(Math.max(3200, Math.min(6400, routePathLengthKm(path) * 840)))
  const startedAt = performance.now()

  const animate = (now: number) => {
    if (activeGuidePathId !== target.id || activeGuideMarker !== marker) return
    const progress = ((now - startedAt) % duration) / duration
    const distance = totalDistance * progress
    let segmentIndex = 1
    while (segmentIndex < cumulativeDistances.length && cumulativeDistances[segmentIndex] < distance) {
      segmentIndex += 1
    }
    const startIndex = Math.max(0, segmentIndex - 1)
    const segmentStart = cumulativeDistances[startIndex]
    const segmentEnd = cumulativeDistances[segmentIndex] || segmentStart
    const segmentProgress = segmentEnd === segmentStart ? 0 : (distance - segmentStart) / (segmentEnd - segmentStart)
    const start = path[startIndex]
    const end = path[segmentIndex] || start
    const heading = Math.atan2(end[0] - start[0], end[1] - start[1]) * 180 / Math.PI
    marker.setAngle?.(heading)
    marker.setPosition([
      start[0] + (end[0] - start[0]) * segmentProgress,
      start[1] + (end[1] - start[1]) * segmentProgress,
    ])
    activeGuideFrame = window.requestAnimationFrame(animate)
  }
  activeGuideFrame = window.requestAnimationFrame(animate)
}

async function drawRouteLeg(
  leg: { origin: RouteNode; destination: RouteNode; city: string; useTransit: boolean; dayIndex: number },
  renderVersion: number,
): Promise<{ road: boolean; transit: boolean }> {
  if (!leg.origin.location || !leg.destination.location) return { road: false, transit: false }
  const city = leg.city.replace(/坪山|龙岗|宝安|龙华|光明|盐田|大鹏/g, '') || leg.city
  try {
    const [roadResponse, transitResponse] = await Promise.all([
      getRouteGeometry(leg.origin.location, leg.destination.location, city, 'driving'),
      leg.useTransit
        ? getRouteGeometry(leg.origin.location, leg.destination.location, city, 'transit').catch(() => null)
        : Promise.resolve(null),
    ])
    if (renderVersion !== mapRenderVersion) return { road: false, transit: false }
    const roadSegments = roadResponse.data?.segments || []
    const transitSegments = transitResponse?.data?.segments || []
    const roadPath = normalizeRoutePath(roadSegments.flatMap((segment) => segment.points))
    const transitPath = normalizeRoutePath(transitSegments.flatMap((segment) => segment.points))
    let roadPolylines: any[] = []
    let transitPolylines: any[] = []
    const routeId = `${leg.dayIndex}:${leg.origin.id}:${leg.destination.id}`
    roadPolylines = addGeometrySegments(roadSegments, 'road', leg.dayIndex, () => {
      playRouteGuideCar({
        id: `${routeId}:road`,
        dayIndex: leg.dayIndex,
        origin: leg.origin,
        destination: leg.destination,
        path: roadPath,
        polylines: roadPolylines,
      })
    })
    transitPolylines = addGeometrySegments(transitSegments, 'transit', leg.dayIndex, () => {
      playRouteGuideCar({
        id: `${routeId}:transit`,
        dayIndex: leg.dayIndex,
        origin: leg.origin,
        destination: leg.destination,
        path: transitPath,
        polylines: transitPolylines,
      })
    })
    return {
      road: roadSegments.length > 0,
      transit: transitSegments.length > 0,
    }
  } catch (error) {
    console.warn('路线几何加载失败:', error)
    return { road: false, transit: false }
  }
}

async function sendMessage() {
  const text = chatInput.value.trim()
  if (!text || chatSending.value) return

  chatInput.value = ''
  chatMessages.value.push({ id: `local-${nextMessageId++}`, role: 'user', content: text })
  chatSending.value = true

  try {
    const response = await sendChatMessage({
      conversation_id: conversationId.value || undefined,
      city: plan.value?.city,
      plan_context: planContext.value,
      message: text,
    })
    if (response.messages?.length) {
      // 后端已落库，以持久化记录为权威来源。
      chatMessages.value = response.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
      }))
    } else {
      chatMessages.value.push({ id: `local-${nextMessageId++}`, role: 'assistant', content: response.reply })
    }
    topKSuggestions.value = response.top_suggestions || []

    const shouldReplan = Boolean(plan.value)
      && response.intent === 'replan'
      && Boolean(response.change_set?.operations?.length)
    if (!shouldReplan || !plan.value) {
      if (import.meta.env.DEV && response.intent === 'replan') {
        console.warn('意图为 replan 但没有有效的 change_set，不触发重规划', { response })
      }
      return
    }

    console.log('🔄 触发重规划', { change_request: response.change_request, operations: response.change_set?.operations?.length })

    const currentPlan = plan.value
    const changeRequest = response.change_request?.trim() || text
    chatMessages.value.push({
      id: `local-${nextMessageId++}`,
      role: 'assistant',
      content: '正在根据你的要求重新安排旅行计划…',
    })

    const firstDay = currentPlan.days?.[0]
    const dateUpdate = response.change_set?.operations?.find((operation) => operation.operation === 'update_dates')
    const updatedStartDate = typeof dateUpdate?.fields?.start_date === 'string'
      ? dateUpdate.fields.start_date
      : currentPlan.start_date
    const updatedEndDate = typeof dateUpdate?.fields?.end_date === 'string'
      ? dateUpdate.fields.end_date
      : currentPlan.end_date
    const replanRequest: TripFormData = {
      city: currentPlan.city,
      start_date: updatedStartDate,
      end_date: updatedEndDate,
      travel_days: currentPlan.days?.length || 1,
      transportation: firstDay?.transportation || '公共交通',
      accommodation: firstDay?.accommodation || '经济型酒店',
      preferences: [],
      free_text_input: changeRequest,
      conversation_id: conversationId.value || undefined,
      preference: response.preference,
      current_plan: currentPlan,
      change_request: changeRequest,
      change_set: response.change_set,
    }
    const replanned = await generateTripPlan(replanRequest)
    if (!replanned.success || !replanned.data) {
      throw new Error(replanned.message || '重新规划失败')
    }

    console.log('✅ 重规划成功，更新行程', { days: replanned.data.days.length })

    // 初次打开历史会话时，坐标/图片补齐可能仍在请求中。重新规划的结果已
    // 通过后端 Validator，含有当前路线所需的真实 POI 坐标；提升版本号可
    // 让旧请求的回包失效，防止它把新计划覆盖回旧计划。
    loadVersion += 1
    plan.value = replanned.data
    if (conversationId.value) {
      updateConversation(conversationId.value, replanned.data)
    }

    // 强制刷新地图以确保路线立即显示
    nextTick(() => {
      renderMap()
    })

    chatMessages.value.push({
      id: `local-${nextMessageId++}`,
      role: 'assistant',
      content: '✅ 行程已调整完成，请查看上方的路线安排。',
    })
  } catch (error) {
    console.error('对话或重新规划失败:', error)
    const detail = error instanceof Error ? error.message : '未知错误'
    chatMessages.value.push({
      id: `local-${nextMessageId++}`,
      role: 'assistant',
      content: `重新规划失败：${detail}。原计划已保留。`,
    })
  } finally {
    chatSending.value = false
  }
}

async function loadChatHistory(id: string, version: number) {
  try {
    const response = await getChatHistory(id)
    if (version !== loadVersion) return
    chatMessages.value = (response.messages || []).map((message) => ({
      id: message.id,
      role: message.role,
      content: message.content,
    }))
  } catch {
    // 聊天历史加载失败不影响行程展示。
  }
}

async function loadChatSuggestions(id: string, version: number) {
  if (!plan.value) return
  try {
    const response = await getChatSuggestions({
      conversation_id: id,
      city: plan.value.city,
      plan_context: planContext.value,
    })
    if (version !== loadVersion) return
    topKSuggestions.value = response.top_suggestions || []
  } catch {
    // 推荐加载失败不影响当前行程和聊天记录。
    topKSuggestions.value = []
  }
}

async function downloadPdf() {
  if (!manualPanel.value || pdfExporting.value) return

  pdfExporting.value = true
  const capture = manualPanel.value.cloneNode(true) as HTMLElement
  capture.querySelector('.pdf-button')?.remove()
  capture.style.cssText = [
    'position:fixed',
    'left:-100000px',
    'top:0',
    `width:${manualPanel.value.clientWidth}px`,
    'height:auto',
    'max-height:none',
    'overflow:visible',
    'background:#fff',
  ].join(';')
  document.body.appendChild(capture)

  try {
    const canvas = await html2canvas(capture, {
      backgroundColor: '#ffffff',
      scale: 2,
      useCORS: true,
      logging: false,
    })
    const pdf = new jsPDF({ orientation: 'portrait', unit: 'pt', format: 'a4' })
    const pageWidth = pdf.internal.pageSize.getWidth()
    const pageHeight = pdf.internal.pageSize.getHeight()
    const imageHeight = (canvas.height * pageWidth) / canvas.width
    const imageData = canvas.toDataURL('image/png')
    let remainingHeight = imageHeight
    let yOffset = 0

    pdf.addImage(imageData, 'PNG', 0, yOffset, pageWidth, imageHeight)
    remainingHeight -= pageHeight
    while (remainingHeight > 0) {
      yOffset = remainingHeight - imageHeight
      pdf.addPage()
      pdf.addImage(imageData, 'PNG', 0, yOffset, pageWidth, imageHeight)
      remainingHeight -= pageHeight
    }

    const city = plan.value?.city || '旅行'
    pdf.save(`${city}旅行手册.pdf`)
  } finally {
    capture.remove()
    pdfExporting.value = false
  }
}

function loadConversation() {
  const version = ++loadVersion
  plan.value = null
  conversationId.value = null
  chatMessages.value = []
  topKSuggestions.value = []
  selectedRouteDay.value = null

  try {
    const routeConversationId = typeof route.query.conversation === 'string'
      ? route.query.conversation
      : getCurrentConversationId()
    const conversation = getConversation(routeConversationId)
    if (conversation?.plan) {
      setCurrentConversationId(conversation.id)
      conversationId.value = conversation.id
      plan.value = conversation.plan
      void loadChatHistory(conversation.id, version)
      void loadChatSuggestions(conversation.id, version)
      // 同一会话首次加载时补齐坐标、图片及缺失旅行日天气。
      if (needsPlanEnrichment(conversation.plan)) {
        void enrichPlanLocationsAndImages(conversation.id, conversation.plan, version)
      }
      return
    }

    // Migrate the old one-off result into the unified conversation store.
    const legacyPlan = loadLegacyPlan()
    if (legacyPlan) {
      const migrated = createConversation(legacyPlan)
      conversationId.value = migrated.id
      plan.value = legacyPlan
      void loadChatHistory(migrated.id, version)
      void loadChatSuggestions(migrated.id, version)
      router.replace({ path: '/result', query: { conversation: migrated.id } })
    }
  } catch {
    clearLegacyPlan()
    plan.value = null
  }
}

watch(() => route.query.conversation, loadConversation, { immediate: true })
watch(plan, (value) => {
  rebuildRouteNodes(value)
  renderMap()
}, { deep: true, immediate: true })

onMounted(() => {
  void initMap()
})

onBeforeUnmount(() => {
  mapMarkers.forEach((marker) => marker.setMap(null))
  clearRouteOverlays()
  mapInstance?.destroy()
  mapInstance = null
})

async function enrichPlanLocationsAndImages(
  conversationId: string,
  currentPlan: TripPlan,
  version: number,
  force = false,
) {
  if (!force && locationEnrichmentCompleted.has(conversationId)) return
  if (locationEnrichmentInFlight.has(conversationId)) return
  locationEnrichmentInFlight.add(conversationId)

  try {
    const response = await enrichTripPlanImages(currentPlan)
    if (response.success && response.data) {
      if (version !== loadVersion) return
      plan.value = response.data
      // 图片补齐不是用户的新对话，不能刷新历史记录排序或覆盖生成时间。
      updateConversation(conversationId, response.data, { touchUpdatedAt: false })
      locationEnrichmentCompleted.add(conversationId)
    }
  } catch {
    // 图片补齐失败不影响已有行程内容展示。
  } finally {
    locationEnrichmentInFlight.delete(conversationId)
  }
}

function startNewPlan() {
  clearLegacyPlan()
  clearCurrentConversationId()
  router.push('/')
}

function needsPlanEnrichment(value: TripPlan) {
  const attractions = value.days.flatMap((day) => day.attractions || [])
  const meals = value.days.flatMap((day) => day.meals || [])
  const hasMissingPoi = attractions.some((attraction) => !attraction.poi_id)
  const hasMissingMealPoi = meals.some((meal) => !meal.poi_id || !hasMapLocation(meal.location))
  const weatherDates = new Set((value.weather_info || []).map((weather) => weather.date))
  const hasMissingTravelWeather = value.days.some((day) => !weatherDates.has(day.date))
  return hasMissingPoi || hasMissingMealPoi || hasMissingTravelWeather
}
</script>

<style scoped>
.result-page{height:100%;min-height:0;padding:0;overflow:hidden;background:#f7f8fa}.result-header{max-width:1120px;margin:0 auto 24px;display:flex;align-items:center;justify-content:space-between}.eyebrow{margin:0 0 8px;color:#2764c8;font-size:14px;font-weight:600}.result-header h1{margin:0;color:#1f2937;font-size:32px}.date-range{margin:8px 0 0;color:#8a919c}.suggestion,.summary-grid,.day-list{max-width:1120px;margin-left:auto;margin-right:auto}.suggestion{margin-bottom:20px}.summary-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:28px}.summary-card{display:flex;align-items:center;gap:14px;padding:18px 20px;background:#fff;border-radius:14px;box-shadow:0 5px 20px rgba(31,41,55,.05)}.summary-icon{font-size:27px}.summary-card div{display:flex;flex-direction:column;gap:5px}.summary-card span:not(.summary-icon){color:#8a919c;font-size:13px}.summary-card strong{color:#26364b}.day-list h2{margin:0 0 16px;color:#1f2937}.day-card{margin-bottom:18px;border-radius:16px;box-shadow:0 5px 20px rgba(31,41,55,.05)}.day-title{display:flex;align-items:center;gap:14px;padding-bottom:16px;border-bottom:1px solid #edf0f4}.day-number{width:42px;height:42px;display:grid;place-items:center;border-radius:12px;background:#1760c4;color:#fff;font-size:20px;font-weight:700}.day-title h3{margin:0 0 4px;color:#26364b}.day-title p{margin:0;color:#8993a1;font-size:13px}.transport{margin-left:auto;color:#607087;font-size:13px}.day-content{display:grid;grid-template-columns:1fr 280px;gap:24px;padding-top:18px}.subsection-title{margin:0 0 14px;color:#26364b;font-size:15px}.attraction-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-bottom:22px}.attraction-card{overflow:hidden;border:1px solid #e8edf5;border-radius:12px;background:#fff;box-shadow:0 3px 12px rgba(31,41,55,.06)}.attraction-image-wrap{height:150px;position:relative;background:linear-gradient(135deg,#dbeafe,#bfdbfe)}.attraction-image{width:100%;height:100%;display:block;object-fit:cover}.image-placeholder{height:100%;display:grid;place-items:center;font-size:42px}.attraction-index{position:absolute;top:10px;left:10px;width:30px;height:30px;display:grid;place-items:center;border-radius:50%;background:#1760c4;color:#fff;font-weight:700}.attraction-body{padding:12px}.attraction-body strong{color:#26364b}.attraction-body p{margin:7px 0 4px;color:#687589;font-size:13px;line-height:1.5}.attraction-body small,.timeline-item small,.hotel-card small{color:#9aa3af}.timeline{display:flex;flex-direction:column;gap:16px}.timeline-item{display:flex;gap:12px}.timeline-dot{flex:0 0 26px;font-size:18px}.timeline-item strong{color:#26364b}.timeline-item p{margin:5px 0 3px;color:#687589;font-size:13px;line-height:1.5}.hotel-card{display:flex;gap:10px;padding:15px;background:#f6f9ff;border-radius:12px;height:max-content}.hotel-card>span{font-size:22px}.hotel-card strong{color:#26364b}.hotel-card p{margin:5px 0;color:#687589;font-size:13px}@media(max-width:760px){.result-page{padding:20px 14px 40px}.result-header{align-items:flex-start;gap:16px}.result-header h1{font-size:25px}.summary-grid{grid-template-columns:1fr}.day-content{grid-template-columns:1fr}.attraction-grid{grid-template-columns:1fr}.transport{display:none}}
.weather-section{max-width:1120px;margin:32px auto 0}.weather-section h2{margin:0 0 16px;color:#1f2937}.weather-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}.weather-item{display:flex;flex-direction:column;gap:8px;padding:16px;background:#fff;border:1px solid #e8edf5;border-radius:12px}.weather-item strong{color:#26364b}.weather-item span{color:#687589;font-size:13px}.weather-item small{color:#9aa3af}
.summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.result-workspace { width: 100%; max-width: none; height: 100%; min-height: 0; margin: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 0; }
.conversation-panel, .manual-panel { min-width: 0; background: #fff; border: 0; border-radius: 0; box-shadow: none; }
.conversation-panel { border-right: 1px solid #f0f0f0; }
.conversation-panel { height: 100%; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.conversation-panel-header, .manual-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 20px 22px; border-bottom: 1px solid #edf0f4; }
.conversation-panel-header h2, .manual-toolbar h2 { margin: 0; color: #1f2937; font-size: 20px; }
.conversation-status { color: #6e7783; font-size: 12px; white-space: nowrap; }
.conversation-status:first-letter { color: #22a06b; }
.conversation-messages { flex: 1; overflow-y: auto; padding: 20px; background: #fbfcfe; }
.assistant-message, .user-message { max-width: 92%; margin-bottom: 14px; padding: 13px 14px; border-radius: 13px; font-size: 13px; line-height: 1.65; }
.assistant-message { max-width: none; margin: 0; padding: 0 0 18px; background: transparent; color: #394b63; border: 0; border-radius: 0; }
.assistant-message strong { display: block; margin-bottom: 5px; color: #1760c4; }
.assistant-message p { margin: 0; }
.topk-suggestions { display: flex; flex-direction: column; gap: 7px; margin: -3px 0 16px; }
.topk-label { color: #8a98a7; font-size: 11px; }
.topk-suggestion { align-self: flex-start; padding: 7px 10px; border: 1px solid #d6e3f0; border-radius: 999px; background: #f7fbff; color: #35618c; cursor: pointer; font: inherit; font-size: 12px; text-align: left; }
.topk-suggestion:hover { border-color: #8bb6e8; background: #eef6ff; color: #1768d4; }
.user-message { margin-left: auto; background: #1760c4; color: #fff; }
.conversation-composer { display: flex; gap: 8px; padding: 14px; border-top: 1px solid #edf0f4; }
.conversation-composer textarea { flex: 1; resize: none; padding: 10px 11px; border: 1px solid #dfe5ee; border-radius: 10px; outline: none; font: inherit; font-size: 13px; }
.conversation-composer textarea:focus { border-color: #1760c4; box-shadow: 0 0 0 2px rgba(23,96,196,.1); }
.conversation-composer button, .pdf-button { align-self: flex-end; padding: 9px 13px; border: 0; border-radius: 9px; background: #1760c4; color: #fff; cursor: pointer; font-size: 13px; white-space: nowrap; }
.conversation-composer button:disabled { background: #c5cfdd; cursor: not-allowed; }
.manual-panel { min-height: 0; height: 100%; overflow-y: auto; padding-bottom: 30px; scrollbar-width: thin; scrollbar-color: #c6cbd3 transparent; }
.conversation-panel, .conversation-messages { scrollbar-width: thin; scrollbar-color: #c6cbd3 transparent; }
.conversation-messages { background: #fff; }
.manual-panel::-webkit-scrollbar, .conversation-panel::-webkit-scrollbar, .conversation-messages::-webkit-scrollbar { width: 6px; }
.manual-panel::-webkit-scrollbar-track, .conversation-panel::-webkit-scrollbar-track, .conversation-messages::-webkit-scrollbar-track { background: transparent; }
.manual-panel::-webkit-scrollbar-thumb, .conversation-panel::-webkit-scrollbar-thumb, .conversation-messages::-webkit-scrollbar-thumb { background: #c6cbd3; border-radius: 999px; }
.manual-panel::-webkit-scrollbar-thumb:hover, .conversation-panel::-webkit-scrollbar-thumb:hover, .conversation-messages::-webkit-scrollbar-thumb:hover { background: #adb4be; }
.manual-panel > .result-header, .manual-panel > .suggestion, .manual-panel > .summary-grid, .manual-panel > .day-list, .manual-panel > .weather-section { max-width: none; margin-left: 24px; margin-right: 24px; }
.manual-panel > .result-header { margin-top: 26px; }
.manual-panel > .suggestion { margin-top: 0; }
.manual-toolbar .eyebrow { margin: 0 0 5px; }
.pdf-button { background: #fff; color: #1760c4; border: 1px solid #1760c4; }
.pdf-button:hover { background: #f0f5ff; }
@media (max-width: 900px) { .result-page { height: auto; min-height: 100%; overflow: visible; }.result-workspace { height: auto; grid-template-columns: 1fr; }.conversation-panel { position: static; height: 360px; border-right: 0; border-bottom: 1px solid #f0f0f0; }.manual-panel { min-height: 0; height: auto; max-height: none; } }
@media print { .conversation-panel, .pdf-button, .manual-toolbar { display: none !important; }.result-page { padding: 0; background: #fff; }.result-workspace { display: block; }.manual-panel { border: 0; box-shadow: none; }.manual-panel > .result-header, .manual-panel > .suggestion, .manual-panel > .summary-grid, .manual-panel > .day-list, .manual-panel > .weather-section { margin-left: 0; margin-right: 0; } }

/* 地图工作台：地图铺满主内容，聊天和路线以浮层呈现。 */
.result-page { position: relative; height: 100%; min-height: 0; padding: 0; overflow: hidden; background: #dce9f1; }
.map-canvas, .map-fallback { position: absolute; inset: 0; z-index: 0; }
.map-fallback { display: grid; place-items: center; overflow: hidden; background: linear-gradient(135deg, #e3f0ea 0%, #d7e7ee 46%, #cbdceb 100%); color: #52687a; }
.map-grid { position: absolute; inset: -20%; opacity: .45; background-image: linear-gradient(27deg, transparent 46%, #fff 47%, #fff 48%, transparent 49%), linear-gradient(112deg, transparent 46%, #fff 47%, #fff 48%, transparent 49%), linear-gradient(90deg, transparent 49%, rgba(104,143,162,.24) 50%, transparent 51%); background-size: 170px 130px, 220px 170px, 70px 70px; transform: rotate(-8deg); }
.map-fallback-label { position: relative; z-index: 1; padding: 12px 18px; border-radius: 999px; background: rgba(255,255,255,.78); box-shadow: 0 8px 22px rgba(55,75,91,.12); font-size: 13px; }
.map-toolbar { position: absolute; top: 16px; left: 18px; z-index: 2; display: flex; align-items: center; gap: 8px; padding: 9px 12px; border: 1px solid rgba(255,255,255,.84); border-radius: 999px; background: rgba(255,255,255,.86); color: #526176; box-shadow: 0 5px 18px rgba(49,71,92,.12); font-size: 12px; backdrop-filter: blur(10px); }
.map-focus-info { padding-left: 8px; border-left: 1px solid #d9e0ea; color: #244b7a; }
.map-day-legend { display: inline-flex; gap: 6px; padding-left: 8px; border-left: 1px solid #d9e0ea; }.map-day-legend > span { display: inline-flex; align-items: center; gap: 3px; }.map-day-legend i { width: 8px; height: 8px; border-radius: 50%; box-shadow: 0 0 0 2px rgba(255,255,255,.9); }
.map-live-dot { width: 7px; height: 7px; border-radius: 50%; background: #16a36c; box-shadow: 0 0 0 4px rgba(22,163,108,.12); }
.conversation-float { position: absolute; left: 18px; bottom: 18px; z-index: 5; width: min(380px, calc(100% - 36px)); height: min(64vh, 590px); border: 1px solid rgba(213,224,234,.95); border-radius: 18px; background: rgba(255,255,255,.94); box-shadow: 0 18px 44px rgba(42,64,82,.2); backdrop-filter: blur(14px); }
.conversation-float .conversation-panel-header { padding: 18px 20px 15px; background: rgba(255,255,255,.82); border-radius: 18px 18px 0 0; }
.conversation-float .conversation-messages { padding: 18px 20px; background: rgba(249,252,255,.72); }
.conversation-float .conversation-composer { padding: 12px; background: rgba(255,255,255,.84); border-radius: 0 0 18px 18px; }
.chat-header-actions { display: flex; align-items: center; gap: 9px; }.chat-collapse-button { width: 27px; height: 27px; display: grid; place-items: center; border: 1px solid #dce5ed; border-radius: 8px; background: rgba(255,255,255,.75); color: #607487; cursor: pointer; font-size: 16px; line-height: 1; }.chat-collapse-button:hover { border-color: #8bb6e8; background: #f1f7ff; color: #1768d4; }
.conversation-collapsed { width: 58px; height: 58px; border-radius: 17px; }.conversation-collapsed .conversation-panel-header { width: 100%; height: 100%; padding: 0; justify-content: center; border-radius: 17px; }.conversation-collapsed .chat-heading, .conversation-collapsed .conversation-status { display: none; }.conversation-collapsed .chat-header-actions { width: 100%; height: 100%; justify-content: center; }.conversation-collapsed .chat-collapse-button { width: 100%; height: 100%; border: 0; background: transparent; font-size: 22px; }
.route-panel { position: absolute; top: 16px; right: 18px; z-index: 4; width: min(560px, calc(100% - 430px)); height: calc(100% - 32px); min-width: 430px; overflow-y: auto; padding-bottom: 28px; border: 1px solid rgba(213,224,234,.95); border-radius: 18px; background: rgba(255,255,255,.95); box-shadow: 0 18px 44px rgba(42,64,82,.18); scrollbar-width: thin; scrollbar-color: #aebdca transparent; backdrop-filter: blur(14px); }
.route-panel::-webkit-scrollbar { width: 6px; }.route-panel::-webkit-scrollbar-thumb { border-radius: 99px; background: #aebdca; }
.route-panel .manual-toolbar { position: sticky; top: 0; z-index: 2; padding: 18px 22px 14px; background: rgba(255,255,255,.94); border-radius: 18px 18px 0 0; }
.manual-toolbar-actions { display: flex; align-items: center; gap: 8px; }
.route-collapse-button, .route-expand-button { display: grid; place-items: center; border: 1px solid #d6e2ed; border-radius: 9px; background: #fff; color: #526b83; cursor: pointer; }
.route-collapse-button { width: 31px; height: 31px; font-size: 22px; line-height: 1; }
.route-collapse-button:hover, .route-expand-button:hover { border-color: #8bb6e8; background: #f1f7ff; color: #1768d4; }
.route-panel-collapsed { width: 48px; min-width: 48px; height: 48px; top: 16px; right: 18px; overflow: hidden; border-radius: 14px; }
.route-expand-button { width: 100%; height: 100%; border: 0; font-size: 27px; line-height: 1; }
.route-panel .result-header, .route-panel .route-summary, .route-panel .route-days, .route-panel .weather-section, .route-panel > .ant-empty { margin-left: 22px; margin-right: 22px; }
.route-panel .result-header { margin-top: 22px; margin-bottom: 16px; }
.route-panel .result-header h1 { font-size: 29px; line-height: 1.15; }.route-panel .eyebrow { margin-bottom: 5px; }
.replan-button { padding: 8px 13px; border: 1px solid #1768d4; border-radius: 9px; background: #fff; color: #1768d4; cursor: pointer; white-space: nowrap; }
.route-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; margin-bottom: 22px; }
.route-summary > div { display: flex; flex-direction: column; gap: 4px; padding: 11px 12px; border: 1px solid #e4ebf2; border-radius: 11px; background: rgba(249,251,253,.84); }.route-summary span { color: #8492a1; font-size: 11px; }.route-summary strong { color: #25384c; font-size: 16px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 12px; margin-bottom: 10px; }.section-heading h2 { margin: 0; color: #23384e; font-size: 20px; }.map-hint { color: #8a98a7; font-size: 11px; white-space: nowrap; }
.route-days .section-heading { margin-bottom: 10px; }.route-days-title { padding: 0; border: 0; background: transparent; color: #263b51; font-size: 21px; font-weight: 700; cursor: pointer; }.route-days-title:hover { color: #1768d4; }.day-route { margin-bottom: 16px; padding: 15px 15px 16px; border: 1px solid #e1eaf1; border-radius: 14px; background: rgba(255,255,255,.8); cursor: pointer; transition: border-color .16s, box-shadow .16s; }.day-route-selected { border-color: #68a5eb; box-shadow: 0 0 0 2px rgba(23,104,212,.12); }.day-route-header { display: flex; align-items: center; gap: 10px; padding-bottom: 12px; border-bottom: 1px solid #edf1f5; }.day-route-header h3 { margin: 0 0 3px; color: #263b51; font-size: 15px; }.day-route-header p { margin: 0; color: #8492a1; font-size: 11px; line-height: 1.45; }.day-route-header .transport { margin-left: auto; color: #637589; font-size: 11px; }
.day-number { width: 31px; height: 31px; display: grid; place-items: center; flex: 0 0 31px; border-radius: 9px; background: #1768d4; color: #fff; font-weight: 700; }
.route-track { position: relative; display: flex; flex-direction: column; gap: 8px; padding: 13px 0 0 16px; }.route-track::before { content: ''; position: absolute; top: 16px; bottom: 16px; left: 28px; width: 2px; background: linear-gradient(#75a9e9, #c7d8e8); }.route-node { position: relative; z-index: 1; display: flex; align-items: flex-start; gap: 10px; min-height: 54px; padding: 9px 10px; border: 1px solid transparent; border-radius: 10px; background: rgba(247,250,253,.9); cursor: grab; transition: border-color .16s, background .16s, transform .16s; }.route-node:hover { border-color: #a7c9ef; background: #f3f8ff; transform: translateX(2px); }.route-node:active { cursor: grabbing; }.route-node-fixed { background: rgba(246,243,255,.92); cursor: default; }.route-node-drop-before::before,.route-node-drop-after::after { content: ''; position: absolute; left: 8px; right: 8px; height: 3px; border-radius: 99px; background: #1768d4; box-shadow: 0 0 0 2px #fff; }.route-node-drop-before::before { top: -6px; }.route-node-drop-after::after { bottom: -6px; }.node-marker { width: 25px; height: 25px; display: grid; place-items: center; flex: 0 0 25px; border-radius: 50%; background: #1768d4; color: #fff; font-size: 12px; font-weight: 700; box-shadow: 0 0 0 4px #fff; }.route-node-hotel .node-marker { background: #8b5cf6; }.route-node-meal .node-marker { background: #e58a35; }.node-content { min-width: 0; flex: 1; }.node-title-row { display: flex; align-items: center; gap: 8px; }.node-title-row strong { overflow: hidden; color: #2d4054; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }.node-actions { display: inline-flex; align-items: center; gap: 7px; margin-left: auto; }.drag-handle { color: #9aabb9; font-size: 17px; line-height: 1; }.node-delete { display: grid; place-items: center; width: 22px; height: 22px; padding: 0; border: 1px solid transparent; border-radius: 6px; background: transparent; color: #a1adba; font: 18px/1 system-ui,sans-serif; cursor: pointer; }.node-delete:hover { border-color: #ffc9c9; background: #fff1f0; color: #d9363e; }.fixed-label { color: #8b78b8; font-size: 10px; font-weight: 600; }.node-content p { margin: 3px 0; overflow: hidden; color: #617487; font-size: 11px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }.node-content small { display: block; overflow: hidden; color: #93a0ad; font-size: 10px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }.route-empty { padding: 12px; color: #99a6b2; font-size: 12px; }
.weather-section { margin-top: 24px; }.weather-section .section-heading { align-items: center; }.weather-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(125px, 1fr)); gap: 8px; }.weather-item { display: flex; flex-direction: column; gap: 5px; padding: 11px; border: 1px solid #e4ebf2; border-radius: 10px; background: rgba(249,251,253,.82); }.weather-item strong { color: #344b62; font-size: 11px; }.weather-item span, .weather-item small { color: #718397; font-size: 10px; }.weather-unavailable { color: #8a98a7 !important; }
@media (max-width: 1100px) { .route-panel { width: min(510px, calc(100% - 350px)); min-width: 350px; }.conversation-float { width: 315px; } }
@media (max-width: 760px) { .map-toolbar { top: 10px; left: 10px; }.conversation-float { left: 10px; bottom: 10px; width: calc(100% - 20px); height: 275px; }.conversation-float .conversation-messages { padding: 12px 14px; }.route-panel { top: 10px; right: 10px; width: calc(100% - 20px); min-width: 0; height: calc(100% - 295px); border-radius: 14px; }.route-panel .manual-toolbar { padding: 13px 16px 11px; }.route-panel .result-header, .route-panel .route-summary, .route-panel .route-days, .route-panel .weather-section, .route-panel > .ant-empty { margin-left: 16px; margin-right: 16px; }.route-panel .result-header h1 { font-size: 23px; }.route-summary { grid-template-columns: repeat(2, 1fr); }.route-summary > div:last-child { grid-column: 1 / -1; }.map-hint { display: none; } }
</style>
