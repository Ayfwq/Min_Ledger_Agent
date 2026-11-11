<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiError, http } from '@/api/client'
import type { InputItem } from '@/api/types'
import StatusTag from '@/components/StatusTag.vue'

const router = useRouter()

const tab = ref<'text' | 'image'>('text')
const text = ref('')
const submitting = ref(false)
const inputs = ref<InputItem[]>([])
const loading = ref(false)
const file = ref<File | null>(null)
const previewUrl = ref('')
const dragOver = ref(false)
let timer: number | undefined

const examples = [
  '昨天中午和同事在海底捞吃饭花了 128.5 元；晚上打车回家 35 元',
  '上周五在星巴克买了两杯拿铁，一共 68 元',
  '昨天吃饭花了点钱',
]

const hasActive = computed(() =>
  inputs.value.some((i) => i.status === 'pending' || i.status === 'processing'),
)

async function load() {
  loading.value = true
  try {
    const { data } = await http.get<InputItem[]>('/inputs', { params: { limit: 60 } })
    inputs.value = data
  } catch (e) {
    ElMessage.error(apiError(e).message)
  } finally {
    loading.value = false
  }
}

function pickExample(value: string) {
  tab.value = 'text'
  text.value = value
}

function onFileChange(uploadFile: { raw?: File }) {
  if (!uploadFile.raw) return
  setFile(uploadFile.raw)
}

function setFile(f: File) {
  if (!f.type.startsWith('image/')) {
    ElMessage.warning('请选择图片文件')
    return
  }
  if (f.size > 10 * 1024 * 1024) {
    ElMessage.warning('图片不能超过 10MB')
    return
  }
  file.value = f
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(f)
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) setFile(f)
}

function clearFile() {
  file.value = null
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}

async function submit() {
  if (submitting.value) return
  if (tab.value === 'text' && !text.value.trim()) {
    ElMessage.warning('请先输入消费描述')
    return
  }
  if (tab.value === 'image' && !file.value) {
    ElMessage.warning('请先选择或拖入截图')
    return
  }
  submitting.value = true
  try {
    let data: { id: string }
    if (tab.value === 'text') {
      const resp = await http.post('/inputs', { text: text.value.trim() })
      data = resp.data
    } else {
      const form = new FormData()
      form.append('file', file.value as File)
      const resp = await http.post('/inputs/upload', form)
      data = resp.data
    }
    text.value = ''
    clearFile()
    ElMessage.success('已提交，正在识别…')
    router.push(`/inputs/${data.id}`)
  } catch (e) {
    ElMessage.error(apiError(e).message)
  } finally {
    submitting.value = false
  }
}

function ago(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

onMounted(() => {
  load()
  timer = window.setInterval(() => {
    if (hasActive.value) load()
  }, 3000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<template>
  <div class="workbench">
    <div class="grid-2">
      <section class="composer card">
        <div class="composer-head">
          <div>
            <h2>记一笔</h2>
            <p class="muted">自然语言或订单截图，支持一次多笔</p>
          </div>
          <el-radio-group v-model="tab" size="small">
            <el-radio-button value="text">文本</el-radio-button>
            <el-radio-button value="image">截图</el-radio-button>
          </el-radio-group>
        </div>

        <div v-if="tab === 'text'" class="pane">
          <el-input
            v-model="text"
            type="textarea"
            :rows="6"
            resize="none"
            maxlength="4000"
            show-word-limit
            placeholder="例如：昨天中午和同事在海底捞吃饭花了 128.5 元；晚上打车回家 35 元"
            @keydown.ctrl.enter="submit"
          />
          <div class="examples">
            <span class="muted">试试：</span>
            <button v-for="e in examples" :key="e" class="chip" @click="pickExample(e)">{{ e }}</button>
          </div>
        </div>

        <div v-else class="pane">
          <el-upload
            v-if="!previewUrl"
            drag
            :auto-upload="false"
            :show-file-list="false"
            accept="image/png,image/jpeg,image/webp"
            :on-change="onFileChange"
          >
            <div class="drop" :class="{ over: dragOver }" @dragover.prevent="dragOver = true" @dragleave="dragOver = false" @drop.prevent="onDrop">
              <el-icon :size="30"><UploadFilled /></el-icon>
              <p class="drop-title">拖拽截图到这里，或点击选择</p>
              <p class="muted">支持 PNG / JPEG / WebP，单张不超过 10MB</p>
            </div>
          </el-upload>
          <div v-else class="preview">
            <img :src="previewUrl" alt="截图预览" />
            <div class="preview-meta">
              <span class="muted">{{ file?.name }}</span>
              <el-button size="small" text type="danger" @click="clearFile">移除</el-button>
            </div>
          </div>
        </div>

        <div class="composer-foot">
          <div class="flow">
            <span>抽取</span><el-icon><ArrowRight /></el-icon>
            <span>澄清</span><el-icon><ArrowRight /></el-icon>
            <span>审核</span><el-icon><ArrowRight /></el-icon>
            <span>入账</span>
          </div>
          <el-button type="primary" size="large" :loading="submitting" @click="submit">
            {{ tab === 'text' ? '开始识别' : '上传并识别' }}
          </el-button>
        </div>
      </section>

      <section class="list card">
        <div class="list-head">
          <div class="section-title">
            <el-icon><List /></el-icon>
            原始输入
            <span class="count">{{ inputs.length }}</span>
          </div>
          <el-button size="small" text :loading="loading" @click="load">
            <el-icon><Refresh /></el-icon>刷新
          </el-button>
        </div>

        <div v-if="!inputs.length && !loading" class="empty">
          <el-icon :size="34"><DocumentAdd /></el-icon>
          <p>还没有记录</p>
          <p class="muted">在左侧输入一句话，或上传一张订单截图</p>
        </div>

        <div class="items">
          <button
            v-for="item in inputs"
            :key="item.id"
            class="item"
            @click="router.push(`/inputs/${item.id}`)"
          >
            <div class="thumb" :class="item.kind">
              <img v-if="item.image" :src="item.image.url" :alt="item.image.filename" />
              <el-icon v-else :size="16"><ChatLineSquare /></el-icon>
            </div>
            <div class="item-body">
              <div class="item-top">
                <span class="kind">{{ item.kind === 'image' ? '截图' : '文本' }}</span>
                <StatusTag :status="item.status" />
                <span class="time">{{ ago(item.created_at) }}</span>
              </div>
              <p class="item-text">
                {{ item.raw_text || item.image?.filename || '（无内容）' }}
              </p>
              <div class="item-meta">
                <span>{{ item.draft_count }} 笔草稿</span>
                <span v-if="item.open_clarifications" class="amber">{{ item.open_clarifications }} 个待澄清</span>
                <span v-if="item.failure_reason" class="red">{{ item.failure_reason }}</span>
              </div>
            </div>
            <el-icon class="chev"><ArrowRight /></el-icon>
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.composer,
.list {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  align-self: start;
}

.list {
  max-height: calc(100vh - 190px);
}

.composer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.composer-head h2 {
  font-size: 18px;
}

.composer-head p {
  margin-top: 4px;
  font-size: 12.5px;
}

.pane {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.examples {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  font-size: 12px;
}

.chip {
  border: 1px solid var(--line);
  background: #fafbfc;
  color: var(--ink-soft);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.chip:hover {
  border-color: #c7d2fe;
  color: var(--brand);
  background: var(--brand-soft);
}

.drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 34px 12px;
  border: 1.5px dashed #d0d5dd;
  border-radius: 12px;
  color: var(--ink-muted);
  transition: all 0.15s ease;
}

.drop.over {
  border-color: var(--brand);
  background: var(--brand-soft);
}

.drop-title {
  font-size: 13.5px;
  color: var(--ink);
  font-weight: 550;
}

.preview {
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}

.preview img {
  display: block;
  margin: 0 auto;
  max-width: 100%;
  max-height: 340px;
  height: auto;
  background: #f8fafc;
}

.preview-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  font-size: 12px;
}

.composer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 6px;
  border-top: 1px dashed var(--line);
}

.flow {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
}

.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 46px 10px;
  color: #98a2b3;
  font-size: 13px;
}

.items {
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: auto;
  padding-right: 2px;
}

.item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  text-align: left;
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 12px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: inherit;
}

.item:hover {
  border-color: #c7d2fe;
  background: #fcfcff;
  transform: translateY(-1px);
}

.thumb {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: #f2f4f7;
  color: #667085;
  flex: none;
  overflow: hidden;
}

.thumb.image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.item-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.item-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.kind {
  font-size: 11px;
  color: var(--ink-muted);
}

.time {
  margin-left: auto;
  font-size: 11px;
  color: #98a2b3;
}

.item-text {
  font-size: 13px;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-meta {
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: var(--ink-muted);
}

.amber {
  color: var(--amber);
}

.red {
  color: var(--red);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chev {
  color: #cbd5e1;
}

:deep(.el-upload) {
  width: 100%;
}

:deep(.el-upload-dragger) {
  padding: 0;
  border: none;
  background: transparent;
}
</style>
