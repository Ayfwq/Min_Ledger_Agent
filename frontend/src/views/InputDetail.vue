<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiError, http } from '@/api/client'
import type { DataSourceCall, Draft, InputDetail } from '@/api/types'
import StatusTag from '@/components/StatusTag.vue'
import DraftCard from '@/components/DraftCard.vue'
import DraftEditor from '@/components/DraftEditor.vue'
import ClarificationPanel from '@/components/ClarificationPanel.vue'
import TraceTimeline from '@/components/TraceTimeline.vue'
import { useStatsStore } from '@/stores/stats'

const route = useRoute()
const router = useRouter()

const statsStore = useStatsStore()
const detail = ref<InputDetail | null>(null)
const loading = ref(true)
const editorOpen = ref(false)
const editing = ref<Draft | null>(null)
const retrying = ref(false)
const retryingSource = ref<string | null>(null)
let timer: number | undefined

const inputId = computed(() => route.params.id as string)
const busy = computed(() => detail.value?.status === 'pending' || detail.value?.status === 'processing')

const latestCalls = computed(() => {
  const map: Record<string, DataSourceCall> = {}
  for (const call of detail.value?.datasource_calls || []) {
    if (!map[call.source]) map[call.source] = call
  }
  return map
})

const staleHours = computed(() => {
  const open = (detail.value?.clarifications || []).filter((c) => c.status === 'open' && c.blocking)
  if (!open.length) return 0
  const oldest = Math.min(...open.map((c) => new Date(c.created_at).getTime()))
  return Math.floor((Date.now() - oldest) / 3600000)
})

async function load(showLoading = false) {
  if (showLoading) loading.value = true
  try {
    const { data } = await http.get<InputDetail>(`/inputs/${inputId.value}`)
    detail.value = data
  } catch (e) {
    ElMessage.error(apiError(e).message)
  } finally {
    loading.value = false
  }
}

async function confirmDraft(draft: Draft) {
  try {
    await ElMessageBox.confirm(
      `确认将 ¥${Number(draft.amount).toFixed(2)}（${draft.txn_date} · ${draft.merchant || '未填商户'}）入账？`,
      '确认入账',
      { confirmButtonText: '确认入账', cancelButtonText: '再看看', type: 'info' },
    )
  } catch {
    return
  }
  try {
    const { data } = await http.post(`/drafts/${draft.id}/confirm`)
    ElMessage.success(data.idempotent ? '该草稿已入账，返回原有账单' : '已生成正式账单')
    await Promise.all([load(), statsStore.refresh()])
  } catch (e) {
    ElMessage.error(apiError(e).message)
  }
}

async function rejectDraft(draft: Draft) {
  try {
    await ElMessageBox.confirm('拒绝后不会生成账单，可稍后重新提交。', '拒绝草稿', {
      confirmButtonText: '拒绝',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await http.post(`/drafts/${draft.id}/reject`)
    ElMessage.success('已拒绝')
    await Promise.all([load(), statsStore.refresh()])
  } catch (e) {
    ElMessage.error(apiError(e).message)
  }
}

async function applySuggestion(draft: Draft, name: string, category: string) {
  try {
    const { data } = await http.patch<Draft>(`/drafts/${draft.id}`, {
      merchant: name,
      category,
      force: true,
    })
    ElMessage.success(`已采用标准商户：${data.merchant}`)
    await Promise.all([load(), statsStore.refresh()])
  } catch (e) {
    ElMessage.error(apiError(e).message)
  }
}

async function retryInput() {
  retrying.value = true
  try {
    await http.post(`/inputs/${inputId.value}/retry`)
    ElMessage.success('已重新排队处理')
    await Promise.all([load(), statsStore.refresh()])
  } catch (e) {
    ElMessage.error(apiError(e).message)
  } finally {
    retrying.value = false
  }
}

async function retrySource(call: DataSourceCall) {
  if (!call.draft_id) return
  retryingSource.value = call.source
  try {
    await http.post(`/drafts/${call.draft_id}/datasources/${call.source}/retry`)
    ElMessage.success('数据源已重试')
    await Promise.all([load(), statsStore.refresh()])
  } catch (e) {
    ElMessage.error(apiError(e).message)
  } finally {
    retryingSource.value = null
  }
}

async function onChanged() {
  await Promise.all([load(), statsStore.refresh()])
}

function openEditor(draft: Draft) {
  editing.value = draft
  editorOpen.value = true
}

function sourceSummary(call: DataSourceCall): string {
  if (call.status === 'failed') return call.error || '调用失败'
  if (call.source === 'duplicate_check') {
    const count = (call.result?.candidates as unknown[] | undefined)?.length ?? 0
    return count ? `发现 ${count} 条疑似重复` : `未发现重复（窗口 ±${call.result?.checked_window_days ?? 3} 天）`
  }
  const merchant = call.result?.merchant as { name?: string; category?: string; confidence?: number } | null
  if (merchant) return `匹配「${merchant.name}」· ${merchant.category} · 置信度 ${merchant.confidence}`
  return '目录中未找到匹配商户'
}

function time(iso: string) {
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

onMounted(async () => {
  await load(true)
  timer = window.setInterval(() => {
    if (busy.value) load()
  }, 2500)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div class="detail">
    <div class="crumb">
      <el-button link @click="router.push('/')">
        <el-icon><ArrowLeft /></el-icon> 返回工作台
      </el-button>
    </div>

    <div v-if="loading && !detail" class="loading card">
      <el-skeleton :rows="4" animated />
    </div>

    <template v-else-if="detail">
      <section class="head card">
        <div class="head-main">
          <div class="head-top">
            <span class="kind">{{ detail.kind === 'image' ? '截图输入' : '文本输入' }}</span>
            <StatusTag :status="detail.status" />
            <span class="time muted">{{ time(detail.created_at) }}</span>
          </div>
          <p v-if="detail.raw_text" class="raw">{{ detail.raw_text }}</p>
          <div v-else-if="detail.image" class="image-line">
            <el-image
              :src="detail.image.url"
              :preview-src-list="[detail.image.url]"
              fit="cover"
              class="thumb"
              preview-teleported
            />
            <div class="meta">
              <span>{{ detail.image.filename }}</span>
              <span class="muted">{{ detail.image.width }} × {{ detail.image.height }} · {{ (detail.image.size_bytes / 1024).toFixed(0) }} KB</span>
            </div>
          </div>

          <el-alert
            v-if="detail.status === 'failed'"
            type="error"
            show-icon
            :closable="false"
            class="alert"
            :title="`处理失败${detail.failure_step ? '（' + detail.failure_step + '）' : ''}`"
            :description="detail.failure_reason || '未知原因'"
          >
            <template #default>
              <div class="fail-body">
                <span>{{ detail.failure_reason || '未知原因' }}</span>
                <el-button size="small" type="danger" plain :loading="retrying" @click="retryInput">
                  从失败步骤重试
                </el-button>
              </div>
            </template>
          </el-alert>
        </div>

        <div class="head-side">
          <div class="metric">
            <span>草稿</span>
            <strong class="mono">{{ detail.draft_count }}</strong>
          </div>
          <div class="metric">
            <span>待澄清</span>
            <strong class="mono">{{ detail.open_clarifications }}</strong>
          </div>
          <el-button size="small" @click="router.push('/review')">去审核台</el-button>
        </div>
      </section>

      <div class="layout">
        <div class="main-col">
          <section class="card block">
            <div class="block-head">
              <div class="section-title">
                <el-icon><Document /></el-icon>
                草稿
                <span class="count">{{ detail.drafts.length }}</span>
              </div>
              <span class="muted tiny">金额与日期齐全、冲突解决后才能入账</span>
            </div>
            <div v-if="!detail.drafts.length" class="empty muted">
              {{ busy ? '正在识别中，请稍候…' : '没有生成草稿' }}
            </div>
            <div class="draft-list">
              <DraftCard
                v-for="draft in detail.drafts"
                :key="draft.id"
                :draft="draft"
                @edit="openEditor"
                @confirm="confirmDraft"
                @reject="rejectDraft"
                @apply-suggestion="applySuggestion"
              />
            </div>
          </section>

          <section class="card block">
            <el-alert
              v-if="staleHours >= 24"
              type="warning"
              show-icon
              :closable="false"
              class="stale"
              :title="`有澄清问题已等待 ${staleHours} 小时`"
              description="可以继续补充、回复“暂不提供”，或取消该问题后在审核台直接编辑草稿。"
            />
            <ClarificationPanel :clarifications="detail.clarifications" @changed="onChanged" />
          </section>
        </div>

        <aside class="side-col">
          <section class="card block">
            <div class="section-title">
              <el-icon><Connection /></el-icon>
              业务数据源
            </div>
            <div class="ds">
              <div class="ds-item">
                <div class="ds-head">
                  <span class="ds-name">历史账单查重</span>
                  <el-tag
                    v-if="latestCalls.duplicate_check"
                    size="small"
                    :type="latestCalls.duplicate_check.status === 'ok' ? 'success' : 'danger'"
                    effect="plain"
                    round
                  >
                    {{ latestCalls.duplicate_check.status === 'ok' ? '成功' : '失败' }}
                  </el-tag>
                  <el-tag v-else size="small" type="info" effect="plain" round>未执行</el-tag>
                </div>
                <p v-if="latestCalls.duplicate_check" class="ds-result">
                  {{ sourceSummary(latestCalls.duplicate_check) }}
                  <span v-if="latestCalls.duplicate_check.latency_ms !== null" class="muted">
                    · {{ latestCalls.duplicate_check.latency_ms }}ms
                  </span>
                </p>
                <p v-else class="ds-result muted">需要金额与日期齐全后自动查询</p>
                <el-button
                  v-if="latestCalls.duplicate_check"
                  size="small"
                  text
                  type="primary"
                  :loading="retryingSource === 'duplicate_check'"
                  @click="retrySource(latestCalls.duplicate_check)"
                >
                  重试
                </el-button>
              </div>

              <div class="ds-item">
                <div class="ds-head">
                  <span class="ds-name">商户目录标准化</span>
                  <el-tag
                    v-if="latestCalls.merchant_catalog"
                    size="small"
                    :type="latestCalls.merchant_catalog.status === 'ok' ? 'success' : 'danger'"
                    effect="plain"
                    round
                  >
                    {{ latestCalls.merchant_catalog.status === 'ok' ? '成功' : '失败' }}
                  </el-tag>
                  <el-tag v-else size="small" type="info" effect="plain" round>未执行</el-tag>
                </div>
                <p v-if="latestCalls.merchant_catalog" class="ds-result">
                  {{ sourceSummary(latestCalls.merchant_catalog) }}
                  <span v-if="latestCalls.merchant_catalog.latency_ms !== null" class="muted">
                    · {{ latestCalls.merchant_catalog.latency_ms }}ms
                  </span>
                </p>
                <p v-else class="ds-result muted">识别到商户后自动查询</p>
                <el-button
                  v-if="latestCalls.merchant_catalog"
                  size="small"
                  text
                  type="primary"
                  :loading="retryingSource === 'merchant_catalog'"
                  @click="retrySource(latestCalls.merchant_catalog)"
                >
                  重试
                </el-button>
              </div>
            </div>
          </section>

          <section class="card block">
            <div class="section-title">
              <el-icon><Timer /></el-icon>
              处理轨迹
              <span class="count">{{ detail.trace_events.length }}</span>
            </div>
            <TraceTimeline :events="detail.trace_events" />
          </section>
        </aside>
      </div>
    </template>

    <DraftEditor v-model="editorOpen" :draft="editing" @saved="onChanged" />
  </div>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.crumb {
  margin-bottom: -4px;
}

.loading {
  padding: 24px;
}

.head {
  padding: 20px;
  display: flex;
  gap: 20px;
  justify-content: space-between;
}

.head-main {
  min-width: 0;
  flex: 1;
}

.head-top {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.kind {
  font-size: 11.5px;
  font-weight: 650;
  color: var(--brand);
  background: var(--brand-soft);
  padding: 2px 9px;
  border-radius: 999px;
}

.time {
  font-size: 11.5px;
}

.raw {
  font-size: 16px;
  line-height: 1.65;
  color: var(--ink);
  white-space: pre-wrap;
}

.image-line {
  display: flex;
  align-items: center;
  gap: 12px;
}

.thumb {
  width: 88px;
  height: 88px;
  border-radius: 10px;
  border: 1px solid var(--line);
}

.meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 12.5px;
}

.alert {
  margin-top: 12px;
}

.fail-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 4px;
  font-size: 13px;
}

.head-side {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: stretch;
  min-width: 120px;
}

.metric {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 10px;
  background: #f9fafb;
  font-size: 12px;
  color: var(--ink-muted);
}

.metric strong {
  font-size: 16px;
  color: var(--ink);
}

.layout {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(300px, 0.9fr);
  gap: 16px;
  align-items: start;
}

.main-col,
.side-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.block {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.stale {
  margin-bottom: 2px;
}

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.tiny {
  font-size: 11.5px;
}

.draft-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.empty {
  font-size: 13px;
  padding: 20px;
  text-align: center;
  background: #f9fafb;
  border-radius: 10px;
}

.ds {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ds-item {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
}

.ds-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.ds-name {
  font-size: 12.5px;
  font-weight: 600;
}

.ds-result {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-soft);
  word-break: break-word;
}

@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .head {
    flex-direction: column;
  }

  .head-side {
    flex-direction: row;
  }

  .head-side .metric {
    flex: 1;
  }
}

@media (max-width: 640px) {
  .kind,
  .metric span {
    white-space: nowrap;
  }

  .block-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }

  .head-side {
    flex-wrap: wrap;
  }
}
</style>
