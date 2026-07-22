<template>
  <div class="result-page">
    <template v-if="plan">
      <header class="result-header">
        <div>
          <p class="eyebrow">你的专属旅行计划</p>
          <h1>{{ plan.city }} · {{ plan.days?.length || 0 }}天行程</h1>
          <p class="date-range">{{ plan.start_date }} 至 {{ plan.end_date }}</p>
        </div>
        <a-button type="primary" ghost @click="startNewPlan">重新规划</a-button>
      </header>

      <a-alert
        v-if="plan.overall_suggestions"
        class="suggestion"
        type="info"
        show-icon
        message="行程建议"
        :description="plan.overall_suggestions"
      />

      <section class="summary-grid">
        <div class="summary-card"><span class="summary-icon">📅</span><div><span>旅行日期</span><strong>{{ plan.start_date }} - {{ plan.end_date }}</strong></div></div>
        <div class="summary-card"><span class="summary-icon">🗺️</span><div><span>行程天数</span><strong>{{ plan.days?.length || 0 }} 天</strong></div></div>
      </section>
      <section class="day-list">
        <h2>每日行程</h2>
        <a-card v-for="(day, dayIndex) in plan.days" :key="day.day_index" class="day-card" :bordered="false">
          <div class="day-title">
            <div class="day-number">{{ dayIndex + 1 }}</div>
            <div><h3>第 {{ dayIndex + 1 }} 天</h3><p>{{ day.date }} · {{ day.description }}</p></div>
            <span class="transport">🚇 {{ day.transportation }}</span>
          </div>
          <div class="day-content">
            <div class="day-main">
              <h4 class="subsection-title">📍 景点安排</h4>
              <div class="attraction-grid">
                <article v-for="(attraction, attractionIndex) in day.attractions" :key="attraction.name" class="attraction-card">
                  <div class="attraction-image-wrap">
                    <img v-if="attraction.image_url" :src="attraction.image_url" :alt="attraction.name" class="attraction-image" loading="lazy" />
                    <div v-else class="image-placeholder">🏞️</div>
                    <span class="attraction-index">{{ attractionIndex + 1 }}</span>
                  </div>
                  <div class="attraction-body">
                    <strong>{{ attraction.name }}</strong>
                    <p><b>地址:</b> {{ attraction.address }}</p>
                    <p><b>游览时长:</b> {{ attraction.visit_duration }} 分钟</p>
                    <p><b>描述:</b> {{ attraction.description }}</p>
                    <p v-if="attraction.rating"><b>评分:</b> {{ attraction.rating }} ⭐</p>
                    <p v-if="attraction.ticket_price !== undefined"><b>门票:</b> ¥{{ attraction.ticket_price }}</p>
                  </div>
                </article>
              </div>
              <div class="timeline">
                <div v-for="meal in day.meals" :key="`${meal.type}-${meal.name}`" class="timeline-item meal-item">
                  <span class="timeline-dot">🍜</span>
                  <div><strong>{{ meal.name }}</strong><p>{{ meal.description || meal.address || meal.type }}</p></div>
                </div>
              </div>
            </div>
            <div v-if="day.hotel" class="hotel-card"><span>🏨</span><div><strong>{{ day.hotel.name }}</strong><p>{{ day.hotel.type }} · {{ day.hotel.price_range }}</p><small>{{ day.hotel.address }}</small></div></div>
          </div>
        </a-card>
      </section>
      <section v-if="plan.weather_info?.length" class="weather-section">
        <h2>天气预报</h2>
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
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { TripPlan } from '@/types'
import { enrichTripPlanImages } from '@/services/api'
import { clearLegacyPlan, createConversation, getConversation, getCurrentConversationId, loadLegacyPlan, setCurrentConversationId, updateConversation } from '@/services/conversations'

const router = useRouter()
const route = useRoute()
const plan = ref<TripPlan | null>(null)
let loadVersion = 0

function loadConversation() {
  const version = ++loadVersion
  plan.value = null

  try {
    const conversationId = typeof route.query.conversation === 'string'
      ? route.query.conversation
      : getCurrentConversationId()
    const conversation = getConversation(conversationId)
    if (conversation?.plan) {
      setCurrentConversationId(conversation.id)
      plan.value = conversation.plan
      void enrichMissingImages(conversation.id, conversation.plan, version)
      return
    }

    // Migrate the old one-off result into the unified conversation store.
    const legacyPlan = loadLegacyPlan()
    if (legacyPlan) {
      const migrated = createConversation(legacyPlan)
      plan.value = legacyPlan
      router.replace({ path: '/result', query: { conversation: migrated.id } })
    }
  } catch {
    clearLegacyPlan()
    plan.value = null
  }
}

watch(() => route.query.conversation, loadConversation, { immediate: true })

async function enrichMissingImages(
  conversationId: string,
  currentPlan: TripPlan,
  version: number
) {
  const hasMissingImages = currentPlan.days.some((day) =>
    day.attractions.some((attraction) => !isAmapImageUrl(attraction.image_url))
  )
  if (!hasMissingImages) return

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

function isAmapImageUrl(url?: string | null) {
  return Boolean(url && url.toLowerCase().includes('autonavi.com'))
}

function startNewPlan() {
  clearLegacyPlan()
  localStorage.removeItem('trip_planner_current_conversation')
  router.push('/')
}
</script>

<style scoped>
.result-page{min-height:calc(100vh - 48px);padding:28px 36px 56px;background:#f7f8fa}.result-header{max-width:1120px;margin:0 auto 24px;display:flex;align-items:center;justify-content:space-between}.eyebrow{margin:0 0 8px;color:#2764c8;font-size:14px;font-weight:600}.result-header h1{margin:0;color:#1f2937;font-size:32px}.date-range{margin:8px 0 0;color:#8a919c}.suggestion,.summary-grid,.day-list{max-width:1120px;margin-left:auto;margin-right:auto}.suggestion{margin-bottom:20px}.summary-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:28px}.summary-card{display:flex;align-items:center;gap:14px;padding:18px 20px;background:#fff;border-radius:14px;box-shadow:0 5px 20px rgba(31,41,55,.05)}.summary-icon{font-size:27px}.summary-card div{display:flex;flex-direction:column;gap:5px}.summary-card span:not(.summary-icon){color:#8a919c;font-size:13px}.summary-card strong{color:#26364b}.day-list h2{margin:0 0 16px;color:#1f2937}.day-card{margin-bottom:18px;border-radius:16px;box-shadow:0 5px 20px rgba(31,41,55,.05)}.day-title{display:flex;align-items:center;gap:14px;padding-bottom:16px;border-bottom:1px solid #edf0f4}.day-number{width:42px;height:42px;display:grid;place-items:center;border-radius:12px;background:#1760c4;color:#fff;font-size:20px;font-weight:700}.day-title h3{margin:0 0 4px;color:#26364b}.day-title p{margin:0;color:#8993a1;font-size:13px}.transport{margin-left:auto;color:#607087;font-size:13px}.day-content{display:grid;grid-template-columns:1fr 280px;gap:24px;padding-top:18px}.subsection-title{margin:0 0 14px;color:#26364b;font-size:15px}.attraction-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-bottom:22px}.attraction-card{overflow:hidden;border:1px solid #e8edf5;border-radius:12px;background:#fff;box-shadow:0 3px 12px rgba(31,41,55,.06)}.attraction-image-wrap{height:150px;position:relative;background:linear-gradient(135deg,#dbeafe,#bfdbfe)}.attraction-image{width:100%;height:100%;display:block;object-fit:cover}.image-placeholder{height:100%;display:grid;place-items:center;font-size:42px}.attraction-index{position:absolute;top:10px;left:10px;width:30px;height:30px;display:grid;place-items:center;border-radius:50%;background:#1760c4;color:#fff;font-weight:700}.attraction-body{padding:12px}.attraction-body strong{color:#26364b}.attraction-body p{margin:7px 0 4px;color:#687589;font-size:13px;line-height:1.5}.attraction-body small,.timeline-item small,.hotel-card small{color:#9aa3af}.timeline{display:flex;flex-direction:column;gap:16px}.timeline-item{display:flex;gap:12px}.timeline-dot{flex:0 0 26px;font-size:18px}.timeline-item strong{color:#26364b}.timeline-item p{margin:5px 0 3px;color:#687589;font-size:13px;line-height:1.5}.hotel-card{display:flex;gap:10px;padding:15px;background:#f6f9ff;border-radius:12px;height:max-content}.hotel-card>span{font-size:22px}.hotel-card strong{color:#26364b}.hotel-card p{margin:5px 0;color:#687589;font-size:13px}@media(max-width:760px){.result-page{padding:20px 14px 40px}.result-header{align-items:flex-start;gap:16px}.result-header h1{font-size:25px}.summary-grid{grid-template-columns:1fr}.day-content{grid-template-columns:1fr}.attraction-grid{grid-template-columns:1fr}.transport{display:none}}
.weather-section{max-width:1120px;margin:32px auto 0}.weather-section h2{margin:0 0 16px;color:#1f2937}.weather-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}.weather-item{display:flex;flex-direction:column;gap:8px;padding:16px;background:#fff;border:1px solid #e8edf5;border-radius:12px}.weather-item strong{color:#26364b}.weather-item span{color:#687589;font-size:13px}.weather-item small{color:#9aa3af}
.summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
</style>
