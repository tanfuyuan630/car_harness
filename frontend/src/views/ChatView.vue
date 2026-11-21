<script setup>
import { ref, nextTick, onMounted, watch, computed } from 'vue'
import { useChatStore } from '../stores/chat'
import { resumeThread, getInterrupts, listWorkspaceFiles, downloadWorkspaceFile, retryThread } from '../api'

const store = useChatStore()
const input = ref('')
const toolEvents = ref([])
const pendingApproval = ref(null)
const inputRequired = ref('')
const retryState = ref(null)
const messagesEl = ref(null)
const workspaceFiles = ref([])

onMounted(async () => {
  await store.initThread()
  await store.loadConversations()
  await store.loadHistory()
  await checkInterrupts()
  await refreshFiles()
  scrollToBottom()
})

// 消息内容变化（含流式追加）时自动滚到底部
watch(() => store.messages.map(m => m.content).join('|'), scrollToBottom)

function scrollToBottom() {
  nextTick(() => {
    const el = messagesEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function onCreateThread() {
  pendingApproval.value = null
  retryState.value = null
  inputRequired.value = ''
  await store.newThread()
  await store.loadConversations()
  scrollToBottom()
}

async function refreshFiles() {
  try {
    const res = await listWorkspaceFiles()
    workspaceFiles.value = res.files || []
  } catch {
    workspaceFiles.value = []
  }
}

function formatSize(size) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

async function onDownload(file) {
  try {
    const blob = await downloadWorkspaceFile(file.name)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = file.name.split('/').pop()
    link.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    alert(`下载失败：${e.message || e}`)
  }
}

async function onSwitchThread(id) {
  if (id === store.threadId) return
  pendingApproval.value = null
  retryState.value = null
  inputRequired.value = ''
  await store.switchThread(id)
  await checkInterrupts()
  scrollToBottom()
}

// 中断值来自 HumanInTheLoopMiddleware：{ action_requests: [{ name, args, description }] }
function displayValue(value) {
  const action = value?.action_requests?.[0] || {}
  const args = action.args || {}
  return args.recommendation || args.question || action.description || '待确认内容'
}

const approvalText = computed(() =>
  pendingApproval.value ? displayValue(pendingApproval.value.value) : '',
)

function parseEventBlock(block) {
  let event = 'message'
  const dataLines = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  return { event, data: dataLines.join('\n') }
}

async function sendMessage() {
  if (!input.value.trim() || store.loading) return
  const text = input.value.trim()
  input.value = ''
  store.addMessage({ role: 'user', content: text })
  store.addMessage({ role: 'assistant', content: '' })
  store.loading = true
  toolEvents.value = []
  retryState.value = null
  scrollToBottom()

  const url = `${import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'}/api/chat/stream`
  try {
    const token = localStorage.getItem('token')
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': token ? `Bearer ${token}` : '' },
      body: JSON.stringify({ thread_id: store.threadId, message: text }),
    })
    if (!resp.ok || !resp.body) throw new Error(`接口返回 ${resp.status}`)

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop()
      for (const block of blocks) {
        if (!block.trim()) continue
        handleEvent(parseEventBlock(block))
      }
    }
  } catch (e) {
    store.appendToLastMessage(`\n[请求失败] ${e.message || e}`)
  } finally {
    store.loading = false
    await store.loadHistory()
    await store.loadConversations()
    await refreshFiles()
    scrollToBottom()
  }
}

function handleEvent({ event, data }) {
  if (event === 'token') {
    store.appendToLastMessage(JSON.parse(data).content)
  } else if (event === 'tool_start') {
    toolEvents.value.push({ name: JSON.parse(data).name, status: 'running' })
  } else if (event === 'tool_end') {
    const payload = JSON.parse(data)
    const last = toolEvents.value[toolEvents.value.length - 1]
    if (last && last.name === payload.name) last.status = 'done'
  } else if (event === 'error') {
    const payload = JSON.parse(data)
    retryState.value = payload.retryable
      ? { retryable: true, message: `生成中断：${payload.error || '临时错误'}，可重试` }
      : { retryable: false, message: `已保留会话进度，请联系开发排查：${payload.error || '未知错误'}` }
  } else if (event === 'done') {
    checkInterrupts()
  }
}

async function checkInterrupts() {
  try {
    const res = await getInterrupts(store.threadId)
    pendingApproval.value = res.interrupts && res.interrupts.length > 0 ? res.interrupts[0] : null
  } catch (e) {
    pendingApproval.value = null
  }
}

async function handleApproval(decision) {
  const edited = decision === 'edit' ? approvalText.value : null
  await submitResume(decision, edited)
}

async function submitInput() {
  if (!inputRequired.value.trim()) return
  await submitResume('edit', inputRequired.value.trim())
}

async function submitResume(decision, edited) {
  try {
    const res = await resumeThread(store.threadId, decision, edited)
    pendingApproval.value = null
    inputRequired.value = ''
    // 恢复执行后，用返回的最终回答替换最后一条助手消息（中断前可能有部分流式输出）
    if (res?.content) {
      store.setLastMessage(res.content)
    }
    if (res?.interrupted) {
      await checkInterrupts()
    }
    await store.loadHistory()
    await refreshFiles()
  } catch (e) {
    retryState.value = {
      retryable: false,
      message: `处理失败：${e.response?.data?.detail || e.message || e}`,
    }
  }
  scrollToBottom()
}

async function onRetry() {
  try {
    const res = await retryThread(store.threadId)
    retryState.value = null
    if (res?.content) {
      store.setLastMessage(res.content)
    }
    if (res?.interrupted) {
      await checkInterrupts()
    }
    await store.loadHistory()
  } catch (e) {
    retryState.value = {
      retryable: false,
      message: `重试失败：${e.response?.data?.detail || e.message || e}`,
    }
  }
  scrollToBottom()
}
</script>

<template>
  <div class="chat-layout">
    <aside class="conv-sidebar">
      <button class="new-btn" @click="onCreateThread">+ 新建对话</button>
      <div class="conv-list">
        <div
          v-for="c in store.conversations"
          :key="c.thread_id"
          class="conv-item"
          :class="{ active: c.thread_id === store.threadId }"
          @click="onSwitchThread(c.thread_id)"
          :title="c.title"
        >
          <div class="conv-title">{{ c.title }}</div>
          <div class="conv-time">{{ c.updated_at }}</div>
        </div>
        <div v-if="!store.conversations.length" class="conv-empty">暂无历史对话</div>
      </div>
    </aside>

    <div class="chat-container">
      <div class="messages" ref="messagesEl">
        <div v-for="(msg, i) in store.messages" :key="i" class="msg" :class="msg.role">
          <div class="bubble">
            <div class="role-tag">{{ msg.role === 'user' ? '我' : '顾问' }}</div>
            <div class="content">{{ msg.content }}</div>
          </div>
        </div>
        <div v-if="store.loading" class="loading">思考中...</div>
      </div>

      <div class="tool-events" v-if="toolEvents.length">
        <div v-for="(t, i) in toolEvents" :key="i" class="tool-event">
          <span :class="t.status">{{ t.status === 'done' ? '✓' : '⟳' }}</span>
          调用工具: {{ t.name }}
        </div>
      </div>

      <div class="approval-card" v-if="pendingApproval">
        <template v-if="pendingApproval.kind === 'input_required'">
          <div class="approval-title">需要补充信息</div>
          <div class="approval-content">{{ approvalText }}</div>
          <input v-model="inputRequired" class="approval-input" placeholder="请输入补充信息..." @keyup.enter="submitInput" />
          <div class="approval-actions">
            <button @click="submitInput">提交</button>
            <button class="danger" @click="handleApproval('reject')">取消</button>
          </div>
        </template>
        <template v-else>
          <div class="approval-title">待确认推荐</div>
          <div class="approval-content">{{ approvalText }}</div>
          <div class="approval-actions">
            <button @click="handleApproval('approve')">批准</button>
            <button class="danger" @click="handleApproval('reject')">拒绝</button>
            <button class="edit" @click="handleApproval('edit')">修改后通过</button>
          </div>
        </template>
      </div>

      <div class="retry-bar" v-if="retryState">
        <span>{{ retryState.message }}</span>
        <button v-if="retryState.retryable" @click="onRetry">重试</button>
      </div>

      <div class="input-bar">
        <input v-model="input" @keyup.enter="sendMessage" placeholder="输入您的购车需求..." :disabled="store.loading" />
        <button @click="sendMessage" :disabled="store.loading || !input.trim()">发送</button>
      </div>
    </div>

    <aside class="file-panel">
      <div class="file-panel-title">生成文件</div>
      <div class="file-list">
        <div
          v-for="f in workspaceFiles"
          :key="f.name"
          class="file-item"
          :title="f.name"
          @click="onDownload(f)"
        >
          <div class="file-name">{{ f.name }}</div>
          <div class="file-meta">{{ formatSize(f.size) }} · {{ f.modified_at }}</div>
        </div>
        <div v-if="!workspaceFiles.length" class="file-empty">暂无生成文件</div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.chat-layout { display: flex; height: 100%; }
.conv-sidebar { width: 220px; background: #fff; border-right: 1px solid #e0e0e0; display: flex; flex-direction: column; }
.new-btn { margin: 12px; padding: 10px; background: #0f3460; color: #fff; border: none; border-radius: 6px; cursor: pointer; }
.conv-list { flex: 1; overflow-y: auto; }
.conv-item { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; cursor: pointer; }
.conv-item:hover { background: #f5f5f5; }
.conv-item.active { background: #e8f0fe; }
.conv-title { font-size: 13px; color: #333; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-time { font-size: 11px; color: #999; margin-top: 3px; }
.conv-empty { padding: 20px; text-align: center; color: #bbb; font-size: 13px; }
.chat-container { flex: 1; display: flex; flex-direction: column; }
.messages { flex: 1; overflow-y: auto; padding: 20px; }
.msg { margin-bottom: 16px; display: flex; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 70%; min-width: 72px; padding: 12px 16px; border-radius: 12px; }
.msg.assistant .bubble { background: #fff; border: 1px solid #e0e0e0; color: #333; }
.msg.user .bubble { background: #e8f0fe; border: 1px solid #c6d8f5; color: #1a1a1a; }
.msg.user .content { color: #1a1a1a; font-size: 14px; line-height: 1.6; }
.role-tag { font-size: 12px; opacity: .7; margin-bottom: 4px; }
.content { white-space: pre-wrap; word-break: break-word; }
.loading { text-align: center; color: #999; padding: 10px; }
.tool-events { padding: 0 20px 10px; }
.tool-event { font-size: 13px; color: #666; padding: 4px 0; }
.tool-event .done { color: #52c41a; }
.tool-event .running { color: #faad14; }
.approval-card { margin: 0 20px 10px; padding: 16px; background: #fff7e6; border: 1px solid #ffd591; border-radius: 8px; }
.approval-title { font-weight: 600; margin-bottom: 8px; color: #d46b08; }
.approval-content { white-space: pre-wrap; margin-bottom: 12px; color: #333; }
.approval-actions button { margin-right: 8px; padding: 6px 16px; border: none; border-radius: 4px; cursor: pointer; }
.approval-actions button:first-child { background: #52c41a; color: #fff; }
.approval-actions button.danger { background: #ff4d4f; color: #fff; }
.approval-actions button.edit { background: #1890ff; color: #fff; }
.approval-input { width: 100%; box-sizing: border-box; padding: 8px 12px; margin-bottom: 10px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 14px; }
.retry-bar { margin: 0 20px 10px; padding: 10px 16px; background: #fff1f0; border: 1px solid #ffa39e; border-radius: 8px; display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 13px; color: #a8071a; }
.retry-bar button { padding: 6px 16px; background: #1890ff; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
.input-bar { display: flex; padding: 16px 20px; background: #fff; border-top: 1px solid #e0e0e0; gap: 10px; }
.input-bar input { flex: 1; padding: 10px 14px; border: 1px solid #d9d9d9; border-radius: 8px; font-size: 14px; }
.input-bar button { padding: 10px 24px; background: #0f3460; color: #fff; border: none; border-radius: 8px; cursor: pointer; }
.input-bar button:disabled { background: #ccc; cursor: not-allowed; }
.file-panel { width: 240px; background: #fff; border-left: 1px solid #e0e0e0; display: flex; flex-direction: column; }
.file-panel-title { padding: 14px 16px; font-size: 14px; font-weight: 600; color: #333; border-bottom: 1px solid #f0f0f0; }
.file-list { flex: 1; overflow-y: auto; }
.file-item { padding: 10px 16px; border-bottom: 1px solid #f5f5f5; cursor: pointer; }
.file-item:hover { background: #f5f7fb; }
.file-name { font-size: 13px; color: #0f3460; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-meta { font-size: 11px; color: #999; margin-top: 4px; }
.file-empty { padding: 20px 16px; text-align: center; color: #bbb; font-size: 13px; }
</style>

