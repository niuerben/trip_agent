import axios from 'axios'
import type { ChatHistoryResponse, TalkRequest, TalkResponse, TripFormData, TripPlan, TripPlanResponse } from '@/types'

// 开发模式使用空 baseURL（同源相对路径），请求经 Vite 代理转发到后端，
// 这样局域网设备访问 http://<本机IP>:5173 时 API 也走同一来源，无需暴露后端或改 CORS。
const API_BASE_URL = import.meta.env.DEV
  ? ''
  : (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000')

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000, // 2分钟超时
  headers: {
    'Content-Type': 'application/json'
  }
})

const TOKEN_KEY = 'trip_planner_access_token'
const USER_KEY = 'trip_planner_user'

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    console.log('发送请求:', config.method?.toUpperCase(), config.url)
    return config
  },
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => {
    console.log('收到响应:', response.status, response.config.url)
    return response
  },
  (error) => {
    console.error('响应错误:', error.response?.status, error.message)
    if (error.response?.status === 401) {
      clearSession()
    }
    return Promise.reject(error)
  }
)

/**
 * 生成旅行计划
 */
export async function generateTripPlan(formData: TripFormData): Promise<TripPlanResponse> {
  try {
    const response = await apiClient.post<TripPlanResponse>('/api/trip/plan', formData)
    return response.data
  } catch (error: any) {
    console.error('生成旅行计划失败:', error)
    throw new Error(error.response?.data?.detail || error.message || '生成旅行计划失败')
  }
}

export async function enrichTripPlanImages(plan: TripPlan): Promise<TripPlanResponse> {
  const response = await apiClient.post<TripPlanResponse>('/api/trip/enrich-images', plan, {
    timeout: 15000
  })
  return response.data
}

/**
 * 与 AI 助手对话（收集/提炼旅行偏好，聊天记录按行程持久化）
 */
export async function sendChatMessage(payload: TalkRequest): Promise<TalkResponse> {
  const response = await apiClient.post<TalkResponse>('/api/talk', payload)
  return response.data
}

/**
 * 读取某个行程对话的 AI 助手聊天历史
 */
export async function getChatHistory(conversationId: string): Promise<ChatHistoryResponse> {
  const response = await apiClient.get<ChatHistoryResponse>(`/api/talk/${encodeURIComponent(conversationId)}`, {
    timeout: 15000
  })
  return response.data
}

/**
 * 健康检查
 */
export async function healthCheck(): Promise<any> {
  try {
    const response = await apiClient.get('/health')
    return response.data
  } catch (error: any) {
    console.error('健康检查失败:', error)
    throw new Error(error.message || '健康检查失败')
  }
}

export function beginOAuth(provider: 'wechat' | 'github'): string {
  const base = API_BASE_URL.replace(/\/$/, '')
  return `${base}/api/auth/${provider}/start?redirect_uri=${encodeURIComponent(window.location.origin)}`
}

export async function loginWithPassword(username: string, password: string): Promise<{ access_token: string; user: { id?: string; name: string; avatar?: string } }> {
  const response = await apiClient.post('/api/auth/login', { username, password }, { timeout: 10000 })
  return response.data
}

export async function registerUser(username: string, password: string): Promise<{ access_token: string; user: { id?: string; name: string; avatar?: string } }> {
  const response = await apiClient.post('/api/auth/register', { username, password }, { timeout: 10000 })
  return response.data
}

export function saveSession(token: string, user: { id?: string; name: string; avatar?: string }) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function getCurrentUser(): { id?: string; name: string; avatar?: string } | null {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') } catch { return null }
}

export function clearSession() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY) }

export default apiClient

