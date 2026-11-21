import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '../views/ChatView.vue'
import CarBrowser from '../views/CarBrowser.vue'
import CompareView from '../views/CompareView.vue'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
  { path: '/register', name: 'register', component: RegisterView, meta: { public: true } },
  { path: '/chat', name: 'chat', component: ChatView },
  { path: '/browser', name: 'browser', component: CarBrowser },
  { path: '/compare', name: 'compare', component: CompareView },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录访问受保护页面 → 跳转登录；已登录访问登录页 → 跳转首页
router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  if (to.meta.public) {
    if (token && to.name === 'login') return { name: 'chat' }
    return true
  }
  if (!token) return { name: 'login' }
  return true
})

export default router
