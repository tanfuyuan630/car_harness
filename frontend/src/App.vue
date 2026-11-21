<script setup>
import { computed } from 'vue'
import { useRoute, useRouter, RouterLink, RouterView } from 'vue-router'
import { logout } from './api'

const route = useRoute()
const router = useRouter()

const isAuthPage = computed(() => !!route.meta.public)
// 依赖 route.fullPath 使登录后路由切换时重新读取 localStorage
const userName = computed(() => {
  route.fullPath
  try { return JSON.parse(localStorage.getItem('user') || '{}').user_name || '' } catch { return '' }
})

async function onLogout() {
  try { await logout() } catch {}
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  localStorage.removeItem('car_harness_thread_id')
  router.push('/login')
}
</script>

<template>
  <div v-if="isAuthPage" class="auth-layout">
    <RouterView />
  </div>
  <div v-else class="app-layout">
    <nav class="sidebar">
      <div class="logo">汽车销售助手</div>
      <RouterLink to="/chat" class="nav-item">智能对话</RouterLink>
      <RouterLink to="/browser" class="nav-item">车型浏览</RouterLink>
      <RouterLink to="/compare" class="nav-item">车型对比</RouterLink>
      <div class="sidebar-footer">
        <div class="user-info">{{ userName || '已登录' }}</div>
        <button class="logout-btn" @click="onLogout">退出登录</button>
      </div>
    </nav>
    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }
.app-layout { display: flex; height: 100vh; }
.auth-layout { min-height: 100vh; }
.sidebar { width: 220px; background: #1a1a2e; color: #fff; padding: 20px 0; display: flex; flex-direction: column; }
.logo { font-size: 18px; font-weight: 600; padding: 0 20px 30px; }
.nav-item { padding: 12px 20px; color: #ccc; text-decoration: none; transition: all .2s; }
.nav-item:hover { background: #16213e; color: #fff; }
.nav-item.router-link-active { background: #0f3460; color: #fff; border-left: 3px solid #e94560; }
.sidebar-footer { margin-top: auto; padding: 16px 20px; border-top: 1px solid #2a2a4a; }
.user-info { font-size: 13px; color: #aaa; margin-bottom: 10px; word-break: break-all; }
.logout-btn { width: 100%; padding: 8px; background: #e94560; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.logout-btn:hover { background: #d63850; }
.content { flex: 1; overflow: auto; background: #f5f5f5; }
</style>
