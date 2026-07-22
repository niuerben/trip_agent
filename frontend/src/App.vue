<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="topbar-title">行旅天下</div>
      <button v-if="!authUser" class="login-button" type="button" @click="loginVisible = true">登录</button>
      <button v-else class="user-button" type="button" @click="logout">{{ authUser.name }} · 退出</button>
    </header>
    <aside class="sidebar">
      <button class="new-chat" type="button" @click="startNewChat">
        <span>✎</span> 新行程 <kbd>Ctrl K</kbd>
      </button>
      <nav class="nav-links">
        <button type="button"><span>♡</span> 灵感收藏</button>
      </nav>
      <div class="history-label">历史对话</div>
      <div class="history-list">
        <div v-for="conversation in conversations" :key="conversation.id" class="history-item" :class="{ active: conversation.id === currentConversationId }">
          <button class="history-select" type="button" @click="selectConversation(conversation.id)">
            <span class="history-dot">●</span>
            <span class="history-title">{{ conversation.title }}</span>
          </button>
          <button class="history-more" type="button" aria-label="更多操作" @click.stop="toggleConversationMenu(conversation.id)">⋯</button>
          <div v-if="openConversationMenuId === conversation.id" class="history-menu" @click.stop>
            <button class="history-delete" type="button" @click="removeConversation(conversation.id)">删除</button>
          </div>
        </div>
        <div v-if="!conversations.length" class="history-empty">暂无对话</div>
      </div>
      <div class="sidebar-bottom">
        <button v-if="!authUser" type="button"><span>ⓘ</span> 关于行旅天下</button>
        <button v-else class="user-profile" type="button" @click="logout">
          <img v-if="authUser.avatar" class="user-avatar" :src="authUser.avatar" alt="用户头像" />
          <span v-else class="user-avatar user-avatar-fallback">{{ userInitial }}</span>
          <span class="user-profile-name">{{ authUser.name }}</span>
          <span class="user-profile-action">退出</span>
        </button>
      </div>
    </aside>
    <main class="main-content">
      <router-view />
    </main>
    <a-modal v-model:open="loginVisible" :title="isRegistering ? '注册行旅天下' : '登录行旅天下'" :footer="null" centered :width="420">
      <a-form :model="loginForm" layout="vertical" @finish="handleAuthSubmit">
        <p v-if="!isRegistering" class="login-description">没有账户？<button class="switch-auth" type="button" @click="isRegistering = true">注册</button></p>
        <p v-else class="login-description">注册后即可同步你的对话与旅行计划</p>
        <a-form-item label="用户名" name="username" :rules="[{ required: true, message: '请输入用户名' }]">
          <a-input v-model:value="loginForm.username" size="large" placeholder="请输入用户名" />
        </a-form-item>
        <a-form-item label="密码" name="password" :rules="[{ required: true, message: '请输入密码' }]">
          <a-input-password v-model:value="loginForm.password" size="large" placeholder="请输入密码" />
        </a-form-item>
        <a-form-item v-if="isRegistering" label="确认密码" name="confirmPassword" :rules="[{ required: true, message: '请再次输入密码' }, { validator: validateConfirmPassword }]">
          <a-input-password v-model:value="loginForm.confirmPassword" size="large" placeholder="请再次输入密码" />
        </a-form-item>
        <a-button html-type="submit" type="primary" block size="large" :loading="loginLoading">{{ isRegistering ? '注册' : '登录' }}</a-button>
        <template v-if="!isRegistering">
          <div class="oauth-divider"><span>其他登录方式</span></div>
          <div class="oauth-actions">
            <a-button block @click="startOAuth('github')">🐙 使用 GitHub 登录</a-button>
            <a-button block @click="startOAuth('wechat')">💬 使用微信登录</a-button>
          </div>
        </template>
        <button v-if="isRegistering" class="back-to-login" type="button" @click="isRegistering = false">返回登录</button>
        <p v-if="!isRegistering" class="login-note">本地默认账号：admin，密码：admin123；生产环境请通过环境变量修改。</p>
        <p v-else class="login-note">注册后会自动登录并同步你的对话。</p>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { beginOAuth, clearSession, getCurrentUser, loginWithPassword, registerUser, saveSession } from '@/services/api'
import { clearCurrentConversationId, deleteConversation, getCurrentConversationId, listConversations, subscribeToConversationChanges, syncConversations, type ConversationRecord } from '@/services/conversations'

const router = useRouter()
const loginVisible = ref(false)
const loginLoading = ref(false)
const isRegistering = ref(false)
const authUser = ref<{ id?: string; name: string; avatar?: string } | null>(null)
const loginForm = reactive({ username: '', password: '', confirmPassword: '' })
const conversations = ref<ConversationRecord[]>([])
const currentConversationId = ref<string | null>(null)
const openConversationMenuId = ref<string | null>(null)
let unsubscribeConversationChanges: (() => void) | undefined
const userInitial = computed(() => {
  const name = authUser.value?.name?.trim() || 'U'
  return name.slice(0, 1).toUpperCase()
})

onMounted(() => {
  authUser.value = getCurrentUser()
  refreshConversations()
  unsubscribeConversationChanges = subscribeToConversationChanges(refreshConversations)
  void syncConversations().then(refreshConversations)
  const params = new URLSearchParams(window.location.search)
  const token = params.get('access_token')
  const userName = params.get('user')
  if (token && userName) {
    const user = { name: userName }
    saveSession(token, user)
    authUser.value = user
    window.history.replaceState({}, document.title, window.location.pathname)
    message.success('登录成功')
  }
})

function refreshConversations() {
  conversations.value = listConversations()
  currentConversationId.value = getCurrentConversationId()
}

function startNewChat() {
  currentConversationId.value = null
  clearCurrentConversationId()
  sessionStorage.removeItem('tripPlan')
  router.push('/')
}

function selectConversation(id: string) {
  openConversationMenuId.value = null
  localStorage.setItem('trip_planner_current_conversation', id)
  currentConversationId.value = id
  router.push({ path: '/result', query: { conversation: id } })
}

function toggleConversationMenu(id: string) {
  openConversationMenuId.value = openConversationMenuId.value === id ? null : id
}

async function removeConversation(id: string) {
  openConversationMenuId.value = null
  try {
    await deleteConversation(id)
    if (currentConversationId.value === id) {
      currentConversationId.value = null
      await router.push('/')
    }
    refreshConversations()
    message.success('对话已删除')
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || '删除对话失败')
  }
}

async function loginWithJWT() {
  loginLoading.value = true
  try {
    const result = await loginWithPassword(loginForm.username, loginForm.password)
    saveSession(result.access_token, result.user)
    authUser.value = result.user
    loginVisible.value = false
    loginForm.password = ''
    void syncConversations().then(refreshConversations)
    message.success('登录成功')
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || '登录失败')
  } finally {
    loginLoading.value = false
  }
}

async function handleAuthSubmit() {
  if (isRegistering.value) await registerAccount()
  else await loginWithJWT()
}

function validateConfirmPassword(_: unknown, value: string) {
  return value === loginForm.password
    ? Promise.resolve()
    : Promise.reject(new Error('两次输入的密码不一致'))
}

async function registerAccount() {
  loginLoading.value = true
  try {
    const result = await registerUser(loginForm.username, loginForm.password)
    saveSession(result.access_token, result.user)
    authUser.value = result.user
    loginVisible.value = false
    loginForm.password = ''
    loginForm.confirmPassword = ''
    void syncConversations().then(refreshConversations)
    message.success('注册成功，已自动登录')
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || '注册失败')
  } finally {
    loginLoading.value = false
  }
}

function startOAuth(provider: 'wechat' | 'github') {
  window.location.href = beginOAuth(provider)
}

function logout() {
  clearSession()
  authUser.value = null
  void syncConversations().then(refreshConversations)
  message.success('已退出登录')
}

onBeforeUnmount(() => unsubscribeConversationChanges?.())
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: system-ui, -apple-system, sans-serif; }
.app-shell { height: 100vh; min-height: 0; display: grid; grid-template-columns: 210px minmax(0, 1fr); grid-template-rows: 64px minmax(0, 1fr); overflow: hidden; }
.topbar { position: relative; z-index: 10; grid-column: 1 / -1; grid-row: 1; height: 64px; display: flex; align-items: center; justify-content: flex-end; padding: 0 24px; border-bottom: 1px solid #f0f0f0; background: rgba(255,255,255,.94); backdrop-filter: blur(12px); }
.topbar-title { position: absolute; left: 18px; display: flex; align-items: center; gap: 7px; color: #25272b; font-size: 15px; font-weight: 600; }.topbar-logo { font-size: 18px; line-height: 1; }
.login-button, .user-button { padding: 9px 22px; border: 0; border-radius: 12px; background: #202124; color: #fff; cursor: pointer; font-size: 14px; }
.user-button { background: #f2f3f5; color: #303238; }
.login-description { margin: -4px 0 20px; color: #96989c; font-size: 13px; }
.switch-auth, .back-to-login { border: 0; background: transparent; color: #1677ff; cursor: pointer; font: inherit; font-weight: 700; text-decoration: underline; }
.back-to-login { display: block; margin: 16px auto 0; font-size: 13px; }
.oauth-divider { display: flex; align-items: center; gap: 12px; margin: 22px 0 14px; color: #a0a4aa; font-size: 12px; }.oauth-divider::before,.oauth-divider::after { content: ''; flex: 1; height: 1px; background: #eceef1; }
.oauth-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }.login-note { margin: 16px 0 0; color: #a0a4aa; font-size: 11px; text-align: center; }
.sidebar {
  position: relative;
  grid-column: 1;
  grid-row: 2;
  width: auto;
  height: 100%;
  padding: 20px 14px 14px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #f0f0f0;
  background: #fbfbfc;
}
.brand {
  height: 38px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  font-weight: 700;
  font-size: 18px;
}
.brand-mark { color: #f29bba; font-size: 23px; }
.new-chat, .nav-links button, .sidebar-bottom button, .history-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  border: 0;
  border-radius: 12px;
  background: transparent;
  color: #34363b;
  cursor: pointer;
  text-align: left;
  font-size: 14px;
}
.new-chat {
  height: 44px;
  padding: 0 13px;
  margin: 16px 0 10px;
  background: #fff;
  box-shadow: 0 4px 15px rgba(30,30,30,.06);
  font-weight: 600;
}
kbd { margin-left: auto; color: #a5a7aa; font-size: 11px; font-weight: 400; }
.nav-links { display: flex; flex-direction: column; gap: 3px; }
.nav-links button, .sidebar-bottom button { height: 42px; padding: 0 13px; }
.nav-links button:hover, .sidebar-bottom button:hover, .history-item:hover, .history-item.active {
  background: #f0f0f1;
}
.history-label { margin: 32px 12px 11px; color: #b0b2b5; font-size: 13px; }
.history-list { display: flex; flex-direction: column; gap: 3px; }
.history-item { position: relative; min-height: 40px; font-size: 13px; }
.history-select { width: 100%; min-height: 40px; padding: 0 38px 0 12px; display: flex; align-items: center; gap: 12px; border: 0; border-radius: 12px; background: transparent; color: #34363b; cursor: pointer; text-align: left; font-size: inherit; }
.history-more { position: absolute; top: 7px; right: 7px; width: 28px; height: 26px; display: grid; place-items: center; border: 0; border-radius: 7px; background: transparent; color: #8c8f95; cursor: pointer; font-size: 18px; line-height: 1; opacity: 0; }
.history-item:hover .history-more, .history-item.active .history-more, .history-more:focus-visible { opacity: 1; }
.history-more:hover { background: #e4e5e7; color: #34363b; }
.history-menu { position: absolute; z-index: 20; top: 38px; right: 6px; min-width: 92px; padding: 5px; border: 1px solid #ececef; border-radius: 9px; background: #fff; box-shadow: 0 8px 24px rgba(30,30,30,.14); }
.history-delete { width: 100%; padding: 7px 9px; border: 0; border-radius: 6px; background: transparent; color: #d9363e; cursor: pointer; text-align: left; font-size: 13px; }
.history-delete:hover { background: #fff1f0; }
.history-dot { color: #b5b7bb; font-size: 9px; }
.history-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-empty { padding: 10px 12px; color: #b0b2b5; font-size: 12px; }
.sidebar-bottom { margin-top: auto; border-top: 1px solid #eee; padding-top: 10px; }
.user-profile { min-width: 0; }
.user-avatar { width: 30px; height: 30px; flex: 0 0 30px; border-radius: 50%; object-fit: cover; }
.user-avatar-fallback { display: grid; place-items: center; background: #202124; color: #fff; font-size: 14px; font-weight: 700; }
.user-profile-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.user-profile-action { margin-left: auto; color: #9b9da2; font-size: 12px; }
.main-content {
  grid-column: 2;
  grid-row: 2;
  min-width: 0;
  min-height: 0;
  height: 100%;
  margin-left: 0;
  padding: 24px 0 0;
  background: #f7f8fa;
  overflow: hidden;
}
.main-content:has(.result-page) { overflow-y: auto; }
.main-content:has(.home-page) { padding: 0; background: #fff; }
@media (max-width: 1400px) {
  .app-shell { grid-template-columns: 190px minmax(0, 1fr); }
  .main-content { padding: 16px 0 0; }
  .topbar-title { left: 18px; }
}
@media (max-width: 600px) { .topbar { padding: 0 12px; }.topbar-title { left: 16px; transform: none; font-size: 13px; }.oauth-actions { grid-template-columns: 1fr; } }
</style>
