<template>
  <div class="result-page">
    <div ref="mapContainer" class="map-canvas" aria-label="旅行路线地图"></div>
    <div v-if="!mapReady" class="map-fallback" aria-hidden="true">
      <span class="map-grid"></span>
      <span class="map-fallback-label">正在加载路线地图</span>
    </div>

    <div class="map-toolbar" aria-label="地图状态">
      <span class="map-live-dot"></span>
      <span>{{ routeNodes.length ? `${routeNodes.length} 个路线节点` : '等待旅行计划' }}</span>
    </div>

    <aside class="conversation-panel conversation-float" :class="{ 'conversation-collapsed': chatCollapsed }">
      <div class="conversation-panel-header">
        <div class="chat-heading">
          <p class="eyebrow">AI 助手</p>
          <h2>行程讨论</h2>
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

    <section ref="manualPanel" class="route-panel">
      <div class="manual-toolbar">
        <div>
          <p class="eyebrow">旅游路线</p>
          <h2>路线安排</h2>
        </div>
        <button class="pdf-button" type="button" :disabled="pdfExporting" @click="downloadPdf">
          {{ pdfExporting ? '生成中…' : '⇩ 下载 PDF' }}
        </button>
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

        <div v-if="plan.overall_suggestions" class="route-note">
          <span class="route-note-icon">i</span>
          <p>{{ plan.overall_suggestions }}</p>
        </div>

        <section class="route-summary">
          <div><span>路线节点</span><strong>{{ routeNodes.length }}</strong></div>
          <div><span>旅行天数</span><strong>{{ plan.days?.length || 0 }} 天</strong></div>
          <div v-if="plan.budget"><span>预计总预算</span><strong>¥{{ plan.budget.total }}</strong></div>
        </section>

        <section class="route-days">
          <div class="section-heading">
            <div>
              <p class="eyebrow">可拖拽调整顺序</p>
              <h2>每日路线</h2>
            </div>
            <span class="map-hint">拖动节点，地图路线会同步更新</span>
          </div>
          <article v-for="(day, dayIndex) in plan.days" :key="day.day_index" class="day-route">
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
                :class="`route-node-${node.type}`"
                draggable="true"
                @dragstart="startNodeDrag(node.id)"
                @dragover.prevent
                @drop="dropNode(node.id)"
                @dragend="finishNodeDrag"
                @dblclick="focusNodeOnMap(node)"
              >
                <span class="node-marker">{{ nodeIcon(node.type) }}</span>
                <div class="node-content">
                  <div class="node-title-row">
                    <strong>{{ node.name }}</strong>
                    <span class="drag-handle" aria-hidden="true">⠿</span>
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

        <section v-if="plan.weather_info?.length" class="weather-section">
          <div class="section-heading"><h2>天气信息</h2><span class="map-hint">高德天气</span></div>
          <div class="weather-row">
            <article v-for="weather in plan.weather_info" :key="weather.date" class="weather-item">
              <strong>{{ weather.date }}</strong>
              <span>☀️ {{ weather.day_weather }} {{ weather.day_temp }}°</span>
              <span>🌙 {{ weather.night_weather }} {{ weather.night_temp }}°</span>
              <small>{{ weather.wind_direction }} {{ weather.wind_power }}</small>
            </article>
          </div>
        </section>
      </template>

      <a-empty v-else description="暂未找到旅行计划">
        <a-button type="primary" @click="startNewPlan">开始规划</a-button>
      </a-empty>
    </section>
  </div>
</template>

<script setup lang="ts">
import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'
import AMapLoader from '@amap/amap-jsapi-loader'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Location, TripFormData, TripPlan } from '@/types'
import { enrichTripPlanImages, generateTripPlan, getChatHistory, sendChatMessage } from '@/services/api'
import { clearLegacyPlan, createConversation, getConversation, getCurrentConversationId, loadLegacyPlan, setCurrentConversationId, updateConversation } from '@/services/conversations'

const router = useRouter()
const route = useRoute()
const plan = ref<TripPlan | null>(null)
const manualPanel = ref<HTMLElement | null>(null)
const mapContainer = ref<HTMLElement | null>(null)
const mapReady = ref(false)
const routeNodes = ref<RouteNode[]>([])
const pdfExporting = ref(false)
const chatInput = ref('')
const chatSending = ref(false)
const chatCollapsed = ref(false)
const conversationId = ref<string | null>(null)
const chatMessages = ref<Array<{ id: number | string; role: 'user' | 'assistant'; content: string }>>([])
let nextMessageId = 1
let loadVersion = 0
let mapInstance: any = null
let mapMarkers: any[] = []
let mapPolyline: any = null
let amapNamespace: any = null
const locationEnrichmentAttempted = new Set<string>()

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
}

function rebuildRouteNodes(value: TripPlan | null) {
  if (!value) {
    routeNodes.value = []
    return
  }

  const nodes: RouteNode[] = []
  value.days.forEach((day, dayIndex) => {
    if (day.hotel) {
      nodes.push({
        id: `day-${dayIndex}-hotel`,
        dayIndex,
        type: 'hotel',
        name: day.hotel.name,
        description: day.hotel.address || day.hotel.type,
        address: day.hotel.address,
        location: day.hotel.location,
        price: day.hotel.price_range,
        hotelType: day.hotel.type,
      })
    }
    day.attractions.forEach((attraction, attractionIndex) => {
      nodes.push({
        id: `day-${dayIndex}-attraction-${attractionIndex}`,
        dayIndex,
        type: 'attraction',
        name: attraction.name,
        description: `${attraction.visit_duration} 分钟 · ${attraction.description}`,
        address: attraction.address,
        location: attraction.location,
      })
    })
    day.meals.forEach((meal, mealIndex) => {
      nodes.push({
        id: `day-${dayIndex}-meal-${mealIndex}`,
        dayIndex,
        type: 'meal',
        name: meal.name,
        description: meal.description || meal.address || '当地特色餐饮',
        address: meal.address,
        location: meal.location,
        cost: meal.estimated_cost,
        mealType: meal.type,
      })
    })
  })
  routeNodes.value = nodes
}

function routeNodesForDay(dayIndex: number) {
  return routeNodes.value.filter((node) => node.dayIndex === dayIndex)
}

function nodeIcon(type: RouteNode['type']) {
  return type === 'hotel' ? '⌂' : type === 'meal' ? '♨' : '●'
}

let draggingNodeId: string | null = null
function startNodeDrag(id: string) {
  draggingNodeId = id
}

function finishNodeDrag() {
  draggingNodeId = null
}

function focusNodeOnMap(node: RouteNode) {
  if (!mapInstance || !node.location) return
  mapInstance.setZoomAndCenter(16, [node.location.longitude, node.location.latitude], false, 500)
}

function dropNode(targetId: string) {
  if (!draggingNodeId || draggingNodeId === targetId) return
  const sourceIndex = routeNodes.value.findIndex((node) => node.id === draggingNodeId)
  const targetIndex = routeNodes.value.findIndex((node) => node.id === targetId)
  if (sourceIndex < 0 || targetIndex < 0) return
  if (routeNodes.value[sourceIndex].dayIndex !== routeNodes.value[targetIndex].dayIndex) return
  const [moved] = routeNodes.value.splice(sourceIndex, 1)
  routeNodes.value.splice(sourceIndex < targetIndex ? targetIndex - 1 : targetIndex, 0, moved)
  draggingNodeId = null
  renderMap()
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

function renderMap() {
  if (!mapInstance || !amapNamespace) return
  mapMarkers.forEach((marker) => marker.setMap(null))
  mapMarkers = []
  mapPolyline?.setMap(null)

  const locatedNodes = routeNodes.value.filter((node) => node.location)
  if (!locatedNodes.length) return
  const path = locatedNodes.map((node) => [node.location!.longitude, node.location!.latitude])
  mapPolyline = new amapNamespace.Polyline({
    path,
    strokeColor: '#1668d7',
    strokeWeight: 5,
    strokeOpacity: 0.82,
    showDir: true,
    lineJoin: 'round',
  })
  mapPolyline.setMap(mapInstance)

  locatedNodes.forEach((node, index) => {
    const marker = new amapNamespace.Marker({
      position: [node.location!.longitude, node.location!.latitude],
      title: `${index + 1}. ${node.name}`,
      draggable: true,
      anchor: 'bottom-center',
      label: { content: `${index + 1}`, direction: 'top' },
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

    if (response.intent !== 'replan' || !plan.value) return

    const currentPlan = plan.value
    chatMessages.value.push({
      id: `local-${nextMessageId++}`,
      role: 'assistant',
      content: '正在根据你的要求重新安排旅行计划…',
    })

    const firstDay = currentPlan.days?.[0]
    const replanRequest: TripFormData = {
      city: currentPlan.city,
      start_date: currentPlan.start_date,
      end_date: currentPlan.end_date,
      travel_days: currentPlan.days?.length || 1,
      transportation: firstDay?.transportation || '公共交通',
      accommodation: firstDay?.accommodation || '经济型酒店',
      preferences: [],
      free_text_input: response.change_request || text,
      conversation_id: conversationId.value || undefined,
      preference: response.preference,
      current_plan: currentPlan,
      change_request: response.change_request || text,
    }
    const replanned = await generateTripPlan(replanRequest)
    if (!replanned.success || !replanned.data) {
      throw new Error(replanned.message || '重新规划失败')
    }

    plan.value = replanned.data
    if (conversationId.value) {
      updateConversation(conversationId.value, replanned.data)
      void enrichPlanLocationsAndImages(conversationId.value, replanned.data, loadVersion)
    }
  } catch {
    chatMessages.value.push({ id: `local-${nextMessageId++}`, role: 'assistant', content: '抱歉，暂时无法回复，请稍后再试。' })
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
      void enrichPlanLocationsAndImages(conversation.id, conversation.plan, version)
      return
    }

    // Migrate the old one-off result into the unified conversation store.
    const legacyPlan = loadLegacyPlan()
    if (legacyPlan) {
      const migrated = createConversation(legacyPlan)
      conversationId.value = migrated.id
      plan.value = legacyPlan
      void loadChatHistory(migrated.id, version)
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
  mapPolyline?.setMap(null)
  mapInstance?.destroy()
  mapInstance = null
})

async function enrichPlanLocationsAndImages(
  conversationId: string,
  currentPlan: TripPlan,
  version: number
) {
  if (locationEnrichmentAttempted.has(conversationId)) return
  locationEnrichmentAttempted.add(conversationId)

  try {
    const response = await enrichTripPlanImages(currentPlan)
    if (response.success && response.data) {
      if (version !== loadVersion) return
      plan.value = response.data
      // 图片补齐不是用户的新对话，不能刷新历史记录排序或覆盖生成时间。
      updateConversation(conversationId, response.data, { touchUpdatedAt: false })
    }
  } catch {
    // 图片补齐失败不影响已有行程内容展示。
  }
}

function startNewPlan() {
  clearLegacyPlan()
  localStorage.removeItem('trip_planner_current_conversation')
  router.push('/')
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
.route-panel .result-header, .route-panel .route-note, .route-panel .route-summary, .route-panel .route-days, .route-panel .weather-section, .route-panel > .ant-empty { margin-left: 22px; margin-right: 22px; }
.route-panel .result-header { margin-top: 22px; margin-bottom: 16px; }
.route-panel .result-header h1 { font-size: 29px; line-height: 1.15; }.route-panel .eyebrow { margin-bottom: 5px; }
.replan-button { padding: 8px 13px; border: 1px solid #1768d4; border-radius: 9px; background: #fff; color: #1768d4; cursor: pointer; white-space: nowrap; }
.route-note { display: flex; gap: 10px; margin-bottom: 14px; padding: 12px 14px; border: 1px solid #c8e0fa; border-radius: 12px; background: #eef7ff; color: #52667d; font-size: 12px; line-height: 1.6; }
.route-note p { margin: 0; }.route-note-icon { flex: 0 0 19px; width: 19px; height: 19px; display: grid; place-items: center; border: 1px solid #2779dd; border-radius: 50%; color: #2779dd; font-weight: 700; }
.route-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; margin-bottom: 22px; }
.route-summary > div { display: flex; flex-direction: column; gap: 4px; padding: 11px 12px; border: 1px solid #e4ebf2; border-radius: 11px; background: rgba(249,251,253,.84); }.route-summary span { color: #8492a1; font-size: 11px; }.route-summary strong { color: #25384c; font-size: 16px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 12px; margin-bottom: 10px; }.section-heading h2 { margin: 0; color: #23384e; font-size: 20px; }.map-hint { color: #8a98a7; font-size: 11px; white-space: nowrap; }
.day-route { margin-bottom: 16px; padding: 15px 15px 16px; border: 1px solid #e1eaf1; border-radius: 14px; background: rgba(255,255,255,.8); }.day-route-header { display: flex; align-items: center; gap: 10px; padding-bottom: 12px; border-bottom: 1px solid #edf1f5; }.day-route-header h3 { margin: 0 0 3px; color: #263b51; font-size: 15px; }.day-route-header p { margin: 0; color: #8492a1; font-size: 11px; line-height: 1.45; }.day-route-header .transport { margin-left: auto; color: #637589; font-size: 11px; }
.day-number { width: 31px; height: 31px; display: grid; place-items: center; flex: 0 0 31px; border-radius: 9px; background: #1768d4; color: #fff; font-weight: 700; }
.route-track { position: relative; display: flex; flex-direction: column; gap: 8px; padding: 13px 0 0 16px; }.route-track::before { content: ''; position: absolute; top: 16px; bottom: 16px; left: 28px; width: 2px; background: linear-gradient(#75a9e9, #c7d8e8); }.route-node { position: relative; z-index: 1; display: flex; align-items: flex-start; gap: 10px; min-height: 54px; padding: 9px 10px; border: 1px solid transparent; border-radius: 10px; background: rgba(247,250,253,.9); cursor: grab; transition: border-color .16s, background .16s, transform .16s; }.route-node:hover { border-color: #a7c9ef; background: #f3f8ff; transform: translateX(2px); }.route-node:active { cursor: grabbing; }.node-marker { width: 25px; height: 25px; display: grid; place-items: center; flex: 0 0 25px; border-radius: 50%; background: #1768d4; color: #fff; font-size: 12px; font-weight: 700; box-shadow: 0 0 0 4px #fff; }.route-node-hotel .node-marker { background: #8b5cf6; }.route-node-meal .node-marker { background: #e58a35; }.node-content { min-width: 0; flex: 1; }.node-title-row { display: flex; align-items: center; gap: 8px; }.node-title-row strong { overflow: hidden; color: #2d4054; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }.drag-handle { margin-left: auto; color: #9aabb9; font-size: 17px; line-height: 1; }.node-content p { margin: 3px 0; overflow: hidden; color: #617487; font-size: 11px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }.node-content small { display: block; overflow: hidden; color: #93a0ad; font-size: 10px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }.route-empty { padding: 12px; color: #99a6b2; font-size: 12px; }
.weather-section { margin-top: 24px; }.weather-section .section-heading { align-items: center; }.weather-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(125px, 1fr)); gap: 8px; }.weather-item { display: flex; flex-direction: column; gap: 5px; padding: 11px; border: 1px solid #e4ebf2; border-radius: 10px; background: rgba(249,251,253,.82); }.weather-item strong { color: #344b62; font-size: 11px; }.weather-item span, .weather-item small { color: #718397; font-size: 10px; }
@media (max-width: 1100px) { .route-panel { width: min(510px, calc(100% - 350px)); min-width: 350px; }.conversation-float { width: 315px; } }
@media (max-width: 760px) { .map-toolbar { top: 10px; left: 10px; }.conversation-float { left: 10px; bottom: 10px; width: calc(100% - 20px); height: 275px; }.conversation-float .conversation-messages { padding: 12px 14px; }.route-panel { top: 10px; right: 10px; width: calc(100% - 20px); min-width: 0; height: calc(100% - 295px); border-radius: 14px; }.route-panel .manual-toolbar { padding: 13px 16px 11px; }.route-panel .result-header, .route-panel .route-note, .route-panel .route-summary, .route-panel .route-days, .route-panel .weather-section, .route-panel > .ant-empty { margin-left: 16px; margin-right: 16px; }.route-panel .result-header h1 { font-size: 23px; }.route-summary { grid-template-columns: repeat(2, 1fr); }.route-summary > div:last-child { grid-column: 1 / -1; }.map-hint { display: none; } }
</style>
