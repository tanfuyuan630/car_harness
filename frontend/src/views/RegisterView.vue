<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { register } from '../api'

const router = useRouter()
const form = ref({ user_id: '', user_name: '', user_pwd: '', age: '' })
const loading = ref(false)
const error = ref('')

async function onRegister() {
  if (!form.value.user_id || !form.value.user_name || !form.value.user_pwd) {
    error.value = '用户ID、用户名、密码为必填项'
    return
  }
  if (form.value.user_pwd.length < 6) {
    error.value = '密码长度至少6位'
    return
  }
  error.value = ''
  loading.value = true
  try {
    const payload = { ...form.value }
    if (form.value.age === '') delete payload.age
    else payload.age = Number(form.value.age)
    await register(payload)
    alert('注册成功，请登录')
    router.push('/login')
  } catch (e) {
    const detail = e.response?.data?.detail
    if (e.response?.status === 409) error.value = '该用户ID已被注册'
    else error.value = detail || '注册失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1>注册账号</h1>
      <p class="subtitle">创建账号以使用汽车销售助手</p>
      <form @submit.prevent="onRegister">
        <div class="field">
          <label>用户ID</label>
          <input v-model="form.user_id" type="text" placeholder="登录用的ID" />
        </div>
        <div class="field">
          <label>用户名</label>
          <input v-model="form.user_name" type="text" placeholder="显示名称" />
        </div>
        <div class="field">
          <label>密码</label>
          <input v-model="form.user_pwd" type="password" placeholder="至少6位" />
        </div>
        <div class="field">
          <label>年龄（可选）</label>
          <input v-model="form.age" type="number" placeholder="请输入年龄" />
        </div>
        <p v-if="error" class="error">{{ error }}</p>
        <button type="submit" :disabled="loading">{{ loading ? '注册中...' : '注 册' }}</button>
      </form>
      <p class="tip">
        已有账号？<router-link to="/login">返回登录</router-link>
      </p>
    </div>
  </div>
</template>

<style scoped>
.auth-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #f0f2f5; }
.auth-card { width: 380px; background: #fff; padding: 36px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,.08); }
.auth-card h1 { font-size: 22px; text-align: center; color: #0f3460; }
.subtitle { text-align: center; color: #888; font-size: 13px; margin: 6px 0 24px; }
.field { margin-bottom: 16px; }
.field label { display: block; font-size: 13px; color: #555; margin-bottom: 6px; }
.field input { width: 100%; padding: 10px 12px; border: 1px solid #dcdfe6; border-radius: 6px; font-size: 14px; box-sizing: border-box; }
.field input:focus { outline: none; border-color: #0f3460; }
button { width: 100%; padding: 11px; background: #0f3460; color: #fff; border: none; border-radius: 6px; font-size: 15px; cursor: pointer; }
button:disabled { opacity: .6; cursor: not-allowed; }
.error { color: #e94560; font-size: 13px; margin: -6px 0 14px; }
.tip { text-align: center; margin-top: 18px; font-size: 13px; color: #666; }
.tip a { color: #0f3460; text-decoration: none; }
</style>
