<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login } from '../api'

const router = useRouter()
const form = ref({ user_id: '', user_pwd: '' })
const loading = ref(false)
const error = ref('')

async function onLogin() {
  if (!form.value.user_id || !form.value.user_pwd) {
    error.value = '请输入用户ID和密码'
    return
  }
  error.value = ''
  loading.value = true
  try {
    const res = await login(form.value)
    localStorage.setItem('token', res.token)
    localStorage.setItem('user', JSON.stringify(res.user))
    router.push('/chat')
  } catch (e) {
    error.value = e.response?.data?.detail || '登录失败，请检查账号密码'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1>汽车销售助手</h1>
      <p class="subtitle">登录后使用全部功能</p>
      <form @submit.prevent="onLogin">
        <div class="field">
          <label>用户ID</label>
          <input v-model="form.user_id" type="text" placeholder="请输入用户ID" autocomplete="username" />
        </div>
        <div class="field">
          <label>密码</label>
          <input v-model="form.user_pwd" type="password" placeholder="请输入密码" autocomplete="current-password" />
        </div>
        <p v-if="error" class="error">{{ error }}</p>
        <button type="submit" :disabled="loading">{{ loading ? '登录中...' : '登 录' }}</button>
      </form>
      <p class="tip">
        还没有账号？<router-link to="/register">立即注册</router-link>
      </p>
    </div>
  </div>
</template>

<style scoped>
.auth-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #f0f2f5; }
.auth-card { width: 380px; background: #fff; padding: 36px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,.08); }
.auth-card h1 { font-size: 22px; text-align: center; color: #0f3460; }
.subtitle { text-align: center; color: #888; font-size: 13px; margin: 6px 0 24px; }
.field { margin-bottom: 18px; }
.field label { display: block; font-size: 13px; color: #555; margin-bottom: 6px; }
.field input { width: 100%; padding: 10px 12px; border: 1px solid #dcdfe6; border-radius: 6px; font-size: 14px; box-sizing: border-box; }
.field input:focus { outline: none; border-color: #0f3460; }
button { width: 100%; padding: 11px; background: #0f3460; color: #fff; border: none; border-radius: 6px; font-size: 15px; cursor: pointer; }
button:disabled { opacity: .6; cursor: not-allowed; }
.error { color: #e94560; font-size: 13px; margin: -6px 0 14px; }
.tip { text-align: center; margin-top: 18px; font-size: 13px; color: #666; }
.tip a { color: #0f3460; text-decoration: none; }
</style>
