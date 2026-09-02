import type { TripPlan } from '@/types'
import apiClient from '@/services/api'

export interface ConversationRecord {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  provider?: 'myCodex' | 'rightcode' | 'local'
  plan?: TripPlan
}

const LEGACY_PLAN_KEY = 'tripPlan'

function getUserNamespace() {
  try {
    const user = JSON.parse(localStorage.getItem('trip_planner_user') || 'null')
    return String(user?.id || user?.name || 'guest')
  } catch {
    return 'guest'
  }
}

function getStorageKey(prefix: string) {
  return `${prefix}:${encodeURIComponent(getUserNamespace())}`
}

function nowBeijingIso() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hourCycle: 'h23'
  }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}:${values.second}+08:00`
}

function readRecords(): ConversationRecord[] {
  try {
    const namespacedKey = getStorageKey('trip_planner_conversations')
    const stored = localStorage.getItem(namespacedKey)
    const legacyGuestRecords = getUserNamespace() === 'guest'
      ? localStorage.getItem('trip_planner_conversations')
      : null
    const value = JSON.parse(stored ?? legacyGuestRecords ?? '[]')
    return Array.isArray(value) ? value : []
  } catch {
    return []
  }
}

function writeRecords(records: ConversationRecord[]) {
  localStorage.setItem(getStorageKey('trip_planner_conversations'), JSON.stringify(records))
  window.dispatchEvent(new CustomEvent('trip-planner-conversations-changed'))
}

export function listConversations(): ConversationRecord[] {
  return readRecords().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
}

export function getConversation(id: string | null): ConversationRecord | null {
  if (!id) return null
  return readRecords().find((conversation) => conversation.id === id) || null
}

export function getCurrentConversationId(): string | null {
  return localStorage.getItem(getStorageKey('trip_planner_current_conversation'))
}

export function setCurrentConversationId(id: string) {
  localStorage.setItem(getStorageKey('trip_planner_current_conversation'), id)
}

export function clearCurrentConversationId() {
  localStorage.removeItem(getStorageKey('trip_planner_current_conversation'))
}

export function createConversation(plan: TripPlan, provider: ConversationRecord['provider'] = 'local') {
  const now = nowBeijingIso()
  const record: ConversationRecord = {
    id: `conversation_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    title: `${plan.city} · ${plan.days?.length || 0}天旅行计划`,
    createdAt: now,
    updatedAt: now,
    provider,
    plan
  }
  writeRecords([record, ...readRecords()])
  setCurrentConversationId(record.id)
  void persistConversation(record)
  return record
}

export function updateConversation(
  id: string,
  plan: TripPlan,
  options: { touchUpdatedAt?: boolean } = {}
) {
  const current = readRecords().find((record) => record.id === id)
  const updatedAt = options.touchUpdatedAt === false
    ? current?.updatedAt || nowBeijingIso()
    : nowBeijingIso()
  const records = readRecords().map((record) => record.id === id
    ? { ...record, title: `${plan.city} · ${plan.days?.length || 0}天旅行计划`, updatedAt, plan }
    : record)
  writeRecords(records)
  setCurrentConversationId(id)
  const updated = records.find((record) => record.id === id)
  if (updated) void persistConversation(updated)
}

export function removeConversation(id: string) {
  writeRecords(readRecords().filter((record) => record.id !== id))
  if (getCurrentConversationId() === id) clearCurrentConversationId()
}

export async function deleteConversation(id: string) {
  await apiClient.delete(`/api/conversations/${encodeURIComponent(id)}`)
  removeConversation(id)
}

export function loadLegacyPlan(): TripPlan | null {
  try {
    const value = sessionStorage.getItem(LEGACY_PLAN_KEY)
    return value ? JSON.parse(value) as TripPlan : null
  } catch {
    return null
  }
}

export function clearLegacyPlan() {
  sessionStorage.removeItem(LEGACY_PLAN_KEY)
}

export function subscribeToConversationChanges(listener: () => void) {
  const eventName = 'trip-planner-conversations-changed'
  window.addEventListener(eventName, listener)
  window.addEventListener('storage', listener)
  return () => {
    window.removeEventListener(eventName, listener)
    window.removeEventListener('storage', listener)
  }
}

async function persistConversation(record: ConversationRecord) {
  try {
    await apiClient.post('/api/conversations', record)
  } catch {
    // Local storage remains available when the backend is offline.
  }
}

export async function syncConversations() {
  if (!localStorage.getItem('trip_planner_access_token')) return
  try {
    const response = await apiClient.get<ConversationRecord[]>('/api/conversations')
    const remoteRecords = Array.isArray(response.data) ? response.data : []
    // 当前用户的远端数据是权威来源，禁止把其他用户的本地缓存上传过来。
    writeRecords(remoteRecords)
  } catch {
    // The UI intentionally continues to work from local storage offline.
  }
}
