<template>
  <div class="home-page">
    <div class="bg-decoration">
      <div class="circle circle-1"></div>
      <div class="circle circle-2"></div>
      <div class="circle circle-3"></div>
    </div>
    <div class="home-content">
      <a-card class="form-card" :bordered="false">
        <a-form :model="formData" layout="vertical" @finish="handleSubmit">
          <div class="form-section">
            <div class="section-header">
              <span class="section-icon">📍</span
              ><span class="section-title">目的地与日期</span>
            </div>
            <a-row :gutter="24"
              ><a-col :span="8"
                ><a-form-item
                  name="city"
                  :rules="[{ required: true, message: '请输入目的地城市' }]"
                  label="目的地城市"
                  ><a-input
                    v-model:value="formData.city"
                    placeholder="例如: 北京"
                    size="large" /></a-form-item></a-col
              ><a-col :span="6"
                ><a-form-item
                  name="start_date"
                  :rules="[{ required: true, message: '请选择开始日期' }]"
                  label="开始日期"
                  ><a-date-picker
                    v-model:value="formData.start_date"
                    style="width: 100%"
                    size="large"
                    placeholder="选择日期" /></a-form-item></a-col
              ><a-col :span="6"
                ><a-form-item
                  name="end_date"
                  :rules="[{ required: true, message: '请选择结束日期' }]"
                  label="结束日期"
                  ><a-date-picker
                    v-model:value="formData.end_date"
                    style="width: 100%"
                    size="large"
                    placeholder="选择日期" /></a-form-item></a-col
              ><a-col :span="4"
                ><a-form-item label="旅行天数"
                  ><div class="days-display-compact">
                    <span class="days-value">{{ formData.travel_days }}</span
                    ><span>天</span>
                  </div></a-form-item
                ></a-col
              ></a-row
            >
          </div>
          <div class="form-section">
            <div class="section-header">
              <span class="section-icon">⚙️</span
              ><span class="section-title">偏好设置</span>
            </div>
            <a-row :gutter="24"
              ><a-col :span="8"
                ><a-form-item label="交通方式"
                  ><a-select
                    v-model:value="formData.transportation"
                    size="large"
                    style="width: 100%"
                    ><a-select-option value="公共交通"
                      >🚇 公共交通</a-select-option
                    ><a-select-option value="自驾">🚗 自驾</a-select-option
                    ><a-select-option value="步行">🚶 步行</a-select-option
                    ><a-select-option value="混合"
                      >🔀 混合</a-select-option
                    ></a-select
                  ></a-form-item
                ></a-col
              ><a-col :span="8"
                ><a-form-item label="住宿偏好"
                  ><a-select
                    v-model:value="formData.accommodation"
                    size="large"
                    style="width: 100%"
                    ><a-select-option value="经济型酒店"
                      >💰 经济型酒店</a-select-option
                    ><a-select-option value="舒适型酒店"
                      >🏨 舒适型酒店</a-select-option
                    ><a-select-option value="豪华酒店"
                      >⭐ 豪华酒店</a-select-option
                    ><a-select-option value="民宿"
                      >🏡 民宿</a-select-option
                    ></a-select
                  ></a-form-item
                ></a-col
              ><a-col :span="8"
                ><a-form-item label="旅行偏好"
                  ><a-checkbox-group
                    v-model:value="formData.preferences"
                    class="custom-checkbox-group"
                    ><a-checkbox value="历史文化">🏛️ 历史文化</a-checkbox
                    ><a-checkbox value="自然风光">🏞️ 自然风光</a-checkbox
                    ><a-checkbox value="美食">🍜 美食</a-checkbox
                    ><a-checkbox value="购物">🛍️ 购物</a-checkbox
                    ><a-checkbox value="艺术">🎨 艺术</a-checkbox
                    ><a-checkbox value="休闲"
                      >☕ 休闲</a-checkbox
                    ></a-checkbox-group
                  ></a-form-item
                ></a-col
              ></a-row
            >
          </div>
          <div class="form-section">
            <div class="section-header">
              <span class="section-icon">💬</span
              ><span class="section-title">额外要求</span>
            </div>
            <a-form-item
              ><a-textarea
                v-model:value="formData.free_text_input"
                placeholder="请输入您的额外要求,例如:想去看升旗、需要无障碍设施、对海鲜过敏等..."
                :rows="3"
                size="large"
            /></a-form-item>
          </div>
          <a-form-item
            ><a-button
              type="primary"
              html-type="submit"
              :loading="loading"
              size="large"
              block
              class="submit-button"
              >{{ loading ? "正在生成中..." : "🚀 开始规划我的旅行" }}</a-button
            ></a-form-item
          >
          <a-form-item v-if="loading"
            ><div class="loading-container">
              <a-progress :percent="loadingProgress" status="active" />
              <p class="loading-status">{{ loadingStatus }}</p>
            </div></a-form-item
          >
        </a-form>
      </a-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { message } from "ant-design-vue";
import { generateTripPlan, isAuthenticated } from "@/services/api";
import type { TripFormData, TripFormState } from "@/types";
import { createConversation } from "@/services/conversations";
const router = useRouter();
const loading = ref(false);
const loadingProgress = ref(0);
const loadingStatus = ref("");

const formData = reactive<TripFormState>({
  city: "",
  start_date: null,
  end_date: null,
  travel_days: 1,
  transportation: "公共交通",
  accommodation: "经济型酒店",
  preferences: [],
  free_text_input: "",
});

watch([() => formData.start_date, () => formData.end_date], ([start, end]) => {
  if (!start || !end) return;

  const days = end.diff(start, "day") + 1;
  if (days > 0 && days <= 30) {
    formData.travel_days = days;
    return;
  }

  message.warning(
    days > 30 ? "旅行天数不能超过30天" : "结束日期不能早于开始日期",
  );
  formData.end_date = null;
});

function buildRequestData(): TripFormData | null {
  if (!formData.start_date || !formData.end_date) {
    message.error("请选择日期");
    return null;
  }

  return {
    city: formData.city,
    start_date: formData.start_date.format("YYYY-MM-DD"),
    end_date: formData.end_date.format("YYYY-MM-DD"),
    travel_days: formData.travel_days,
    transportation: formData.transportation,
    accommodation: formData.accommodation,
    preferences: formData.preferences,
    free_text_input: formData.free_text_input,
  };
}

function startProgress() {
  loadingProgress.value = 0;
  loadingStatus.value = "正在初始化...";

  return window.setInterval(() => {
    if (loadingProgress.value >= 90) return;

    loadingProgress.value += 10;
    loadingStatus.value = getProgressStatus(loadingProgress.value);
  }, 500);
}

function getProgressStatus(progress: number) {
  if (progress <= 30) return "🔍 正在搜索景点...";
  if (progress <= 50) return "🌤️ 正在查询天气...";
  if (progress <= 70) return "🏨 正在推荐酒店...";
  return "📋 正在生成行程计划...";
}

function resetLoading() {
  loading.value = false;
  loadingProgress.value = 0;
  loadingStatus.value = "";
}

async function handleSubmit() {
  if (!isAuthenticated()) {
    message.warning("请先登录后再生成旅行计划");
    window.dispatchEvent(new CustomEvent("trip-planner-login-required"));
    return;
  }

  const requestData = buildRequestData();
  if (!requestData) return;

  loading.value = true;
  const timer = startProgress();

  try {
    const response = await generateTripPlan(requestData);
    window.clearInterval(timer);
    loadingProgress.value = 100;
    loadingStatus.value = "✅ 完成!";

    if (!response.success || !response.data) {
      message.error(response.message || "生成失败");
      return;
    }

    const conversation = createConversation(response.data, "local");
    sessionStorage.setItem("tripPlan", JSON.stringify(response.data));
    message.success("旅行计划生成成功!");
    await router.push({
      path: "/result",
      query: { conversation: conversation.id },
    });
  } catch (error: any) {
    window.clearInterval(timer);
    resetLoading();
    message.error(error.message || "生成旅行计划失败,请稍后重试");
  } finally {
    if (loading.value) window.setTimeout(resetLoading, 1000);
  }
}
</script>

<style scoped>
.home-page {
  height: 100%;
  min-height: 0;
  padding: clamp(12px, 3vh, 32px) clamp(12px, 2.5vw, 24px)
    clamp(16px, 4vh, 48px);
  position: relative;
  overflow: hidden;
}
.home-content {
  --content-scale: clamp(0.42, calc((100vh - 120px) / 780), 1);
  position: relative;
  z-index: 1;
  width: calc(100% / var(--content-scale));
  max-width: calc(1120px / var(--content-scale));
  margin: 0 auto;
  transform-origin: top center;
  zoom: var(--content-scale);
}
.bg-decoration {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}
.circle {
  position: absolute;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.1);
  animation: float 20s infinite ease-in-out;
}
.circle-1 {
  width: 220px;
  height: 220px;
  top: -100px;
  left: -100px;
}
.circle-2 {
  width: 160px;
  height: 160px;
  top: 50%;
  right: -50px;
  animation-delay: 5s;
}
.circle-3 {
  width: 120px;
  height: 120px;
  bottom: -50px;
  left: 30%;
  animation-delay: 10s;
}
@keyframes float {
  0%,
  100% {
    transform: translateY(0) rotate(0);
  }
  50% {
    transform: translateY(-30px) rotate(180deg);
  }
}
.page-header {
  text-align: center;
  margin-bottom: clamp(12px, 3vh, 28px);
}
.icon-wrapper {
  margin-bottom: clamp(8px, 2vh, 20px);
}
.icon {
  font-size: clamp(32px, 6vh, 56px);
}
.page-title {
  font-size: clamp(24px, 5vh, 40px);
  font-weight: 700;
  color: #fff;
  margin: 0 0 12px;
  text-shadow: 3px 3px 6px rgba(0, 0, 0, 0.3);
  letter-spacing: 2px;
}
.page-subtitle {
  font-size: clamp(12px, 2.2vh, 16px);
  color: rgba(255, 255, 255, 0.95);
  margin: 0;
}
.form-card {
  width: 100%;
  max-width: 1120px;
  margin: 0 auto;
  border-radius: 20px;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.4);
  background: rgba(255, 255, 255, 0.98) !important;
}
.form-section {
  margin-bottom: clamp(10px, 2vh, 20px);
  padding: clamp(10px, 2vh, 20px);
  background: linear-gradient(135deg, #f7f8fa 0%, #fff 100%);
  border-radius: 16px;
  border: 1px solid #e8e8e8;
}
.section-header {
  display: flex;
  align-items: center;
  margin-bottom: clamp(10px, 2vh, 20px);
  padding-bottom: clamp(8px, 1.5vh, 12px);
  border-bottom: 2px solid #074098;
}
.section-icon {
  font-size: clamp(18px, 3vh, 24px);
  margin-right: 12px;
}
.section-title {
  font-size: clamp(14px, 2.5vh, 18px);
  font-weight: 600;
  color: #333;
}
.days-display-compact {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 40px;
  padding: 8px 16px;
  background: linear-gradient(135deg, #074098 0%, #0a54c2 100%);
  border-radius: 12px;
  color: #fff;
}
.days-value {
  font-size: 24px;
  font-weight: 700;
  margin-right: 4px;
}
.custom-checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}
.submit-button {
  height: 48px;
  border-radius: 24px;
  font-size: 16px;
  font-weight: 600;
  background: linear-gradient(135deg, #074098 0%, #0a54c2 100%);
  border: none;
  box-shadow: 0 8px 24px rgba(102, 126, 234, 0.4);
}
.loading-container {
  text-align: center;
  padding: 24px;
  background: #f7f8fa;
  border-radius: 16px;
  border: 2px dashed #074098;
}
.loading-status {
  margin-top: 16px;
  color: #074098;
  font-size: 18px;
  font-weight: 500;
}
@media (max-width: 1366px) {
  .home-container {
    padding: clamp(10px, 2vh, 24px) clamp(12px, 2vw, 20px)
      clamp(16px, 3vh, 40px);
  }
  .form-card {
    max-width: 1040px;
    border-radius: 16px;
  }
  .submit-button {
    height: 44px;
    font-size: 15px;
  }
}
@media (max-width: 700px) {
  .home-container :deep(.ant-col) {
    width: 100%;
    max-width: 100%;
    flex: 0 0 100%;
  }
  .home-container :deep(.ant-row) {
    row-gap: 0;
  }
  .form-section {
    padding: 12px;
  }
  .form-card :deep(.ant-card-body) {
    padding: 12px;
  }
  .custom-checkbox-group {
    gap: 5px;
  }
}
@media (max-width: 700px) {
  .home-page :deep(.ant-col) {
    width: 100%;
    max-width: 100%;
    flex: 0 0 100%;
  }
  .home-page :deep(.ant-row) {
    row-gap: 0;
  }
  .form-card :deep(.ant-card-body) {
    padding: 12px;
  }
}

/* Keep the planner as an open workspace instead of a nested card surface. */
.home-page {
  background: #fff;
  overflow: auto;
}
.bg-decoration {
  display: none;
}
.form-card {
  max-width: 1120px;
  border-radius: 0;
  box-shadow: none;
  background: transparent !important;
}
.form-card :deep(.ant-card-body) {
  padding: 0;
}
.form-section {
  padding-inline: 0;
  background: transparent;
  border: 0;
  border-bottom: 1px solid #eef0f2;
  border-radius: 0;
}
@media (max-width: 1366px) {
  .form-card {
    border-radius: 0;
  }
}
@media (max-width: 700px) {
  .form-section {
    padding-inline: 0;
  }
  .form-card :deep(.ant-card-body) {
    padding: 0;
  }
}
</style>
