import { defineStore } from 'pinia'
import { ref } from 'vue'
import { createThread, getHistory, listConversations } from '../api'

// 会话ID持久化到 localStorage，刷新页面后仍能恢复历史
const THREAD_KEY = 'car_harness_thread_id'

export const useChatStore = defineStore('chat', () => {
  const threadId = ref(localStorage.getItem(THREAD_KEY) || '')
  const messages = ref([])
  const loading = ref(false)
  const conversations = ref([])

  async function initThread() {
    if (!threadId.value) {
      const res = await createThread()
      threadId.value = res.thread_id
      localStorage.setItem(THREAD_KEY, threadId.value)
    }
    return threadId.value
  }

  async function loadHistory() {
    if (!threadId.value) return
    const res = await getHistory(threadId.value)
    messages.value = res.messages
      .filter(m => (m.role === 'user' || m.role === 'assistant') && m.content && m.content.trim())
      .map(m => ({ role: m.role, content: m.content }))
  }

  async function loadConversations() {
    try {
      const res = await listConversations()
      conversations.value = res.conversations || []
    } catch { conversations.value = [] }
  }

  async function switchThread(id) {
    threadId.value = id
    localStorage.setItem(THREAD_KEY, id)
    messages.value = []
    await loadHistory()
  }

  async function newThread() {
    const res = await createThread()
    threadId.value = res.thread_id
    localStorage.setItem(THREAD_KEY, threadId.value)
    messages.value = []
  }

  function addMessage(msg) {
    messages.value.push(msg)
  }

  function appendToLastMessage(chunk) {
    if (messages.value.length > 0) {
      messages.value[messages.value.length - 1].content += chunk
    }
  }

  function setLastMessage(content) {
    if (messages.value.length > 0) {
      messages.value[messages.value.length - 1].content = content
    }
  }

  return {
    threadId, messages, loading, conversations,
    initThread, loadHistory, loadConversations, switchThread, newThread,
    addMessage, appendToLastMessage, setLastMessage,
  }
})
