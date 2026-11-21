import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

const api = axios.create({ baseURL: API_BASE, timeout: 120000 })

// 请求拦截器：自动携带登录 Token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截器：401 清除登录态并跳转登录页
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (location.pathname !== '/login') location.href = '/login'
    }
    return Promise.reject(err)
  },
)

// 认证接口
export const register = (data) => api.post('/api/auth/register', data).then(r => r.data)
export const login = (data) => api.post('/api/auth/login', data).then(r => r.data)
export const logout = () => api.post('/api/auth/logout').then(r => r.data)
export const getMe = () => api.get('/api/auth/me').then(r => r.data)

// 历史会话接口
export const listConversations = () => api.get('/api/conversations').then(r => r.data)
export const getConversation = (threadId) => api.get(`/api/conversations/${threadId}`).then(r => r.data)

// 聊天接口
export const createThread = () => api.post('/api/threads').then(r => r.data)
export const getHistory = (threadId) => api.get(`/api/threads/${threadId}/history`).then(r => r.data)
export const getInterrupts = (threadId) => api.get(`/api/threads/${threadId}/interrupts`).then(r => r.data)
export const resumeThread = (threadId, decision, editedContent) =>
  api.post(`/api/threads/${threadId}/resume`, { decision, edited_content: editedContent }).then(r => r.data)
export const chat = (threadId, message) =>
  api.post('/api/chat', { thread_id: threadId, message }).then(r => r.data)
export const retryThread = (threadId) =>
  api.post(`/api/threads/${threadId}/retry`).then(r => r.data)

// 工作区文件接口
export const listWorkspaceFiles = () => api.get('/api/workspace/files').then(r => r.data)
export const downloadWorkspaceFile = (path) =>
  api.get(`/api/workspace/files/${path.split('/').map(encodeURIComponent).join('/')}`, { responseType: 'blob' }).then(r => r.data)

// 汽车数据接口
export const getBrands = () => api.get('/api/brands').then(r => r.data)
export const getSeries = (brand) => api.get(`/api/brands/${encodeURIComponent(brand)}/series`).then(r => r.data)
export const searchCars = (params) => api.get('/api/cars', { params }).then(r => r.data)
export const getCarDetail = (modelId) => api.get(`/api/cars/${modelId}`).then(r => r.data)

export default api
