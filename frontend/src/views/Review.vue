<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiError, http } from '@/api/client'
import type { Draft } from '@/api/types'
import DraftCard from '@/components/DraftCard.vue'
import DraftEditor from '@/components/DraftEditor.vue'
import { useStatsStore } from '@/stores/stats'

const filters = [
  { value: 'ready_for_review', label: '待审核' },
  { value: 'needs_clarification', label: '待澄清' },
  { value: 'confirmed', label: '已入账' },
  { value: 'rejected', label: '已拒绝' },
  { value: '', label: '全部' },
]

const statsStore = useStatsStore()
const active = ref('ready_for_review')
const drafts = ref<Draft[]>([])
const loading = ref(false)
const editorOpen = ref(false)
const editing = ref<Draft | null>(null)

const counts = computed(() => {
  const map: Record<string, number> = {}
  for (const d of drafts.value) map[d.status] = (map[d.status] || 0) + 1
  return map
})

async function load() {
  loading.value = true
  try {
    const { data } = await http.get<Draft[]>('/drafts', {
      params: { status: active.value || undefined, limit: 200 },
    })
    drafts.value = data
  } catch (e) {
    ElMessage.error(apiError(e).message)
  } finally {
    loading.value = false
  }
}

function openEditor(draft: Draft) {
  editing.value = draft
  editorOpen.value = true
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
    await ElMessageBox.confirm('拒绝后不会生成账单。', '拒绝草稿', {
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
    await http.patch(`/drafts/${draft.id}`, { merchant: name, category, force: true })
    ElMessage.success(`已采用标准商户：${name}`)
    await Promise.all([load(), statsStore.refresh()])
  } catch (e) {
    ElMessage.error(apiError(e).message)
  }
}

async function onSaved() {
  await Promise.all([load(), statsStore.refresh()])
}

watch(active, load)
onMounted(load)
</script>

<template>
  <div class="review">
    <div class="toolbar">
      <div class="filters">
        <button
          v-for="f in filters"
          :key="f.value"
          class="filter"
          :class="{ active: active === f.value }"
          @click="active = f.value"
        >
          {{ f.label }}
          <span v-if="f.value && counts[f.value]" class="n">{{ counts[f.value] }}</span>
        </button>
      </div>
      <el-button size="small" text :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
    </div>

    <div v-if="loading && !drafts.length" class="skeleton">
      <el-skeleton :rows="6" animated />
    </div>

    <div v-else-if="!drafts.length" class="empty card">
      <el-icon :size="34"><CircleCheck /></el-icon>
      <p>{{ active === 'ready_for_review' ? '没有待审核的草稿' : '这里还没有内容' }}</p>
      <p class="muted">新的输入会在识别完成后出现在这里</p>
    </div>

    <div v-else class="list">
      <div v-for="draft in drafts" :key="draft.id" class="review-item">
        <div class="origin">
          <el-icon :size="13"><ChatLineSquare /></el-icon>
          <span class="origin-text">{{ draft.input_text || '截图输入' }}</span>
          <RouterLink :to="`/inputs/${draft.input_id}`" class="link">查看完整轨迹</RouterLink>
        </div>
        <DraftCard
          :draft="draft"
          @edit="openEditor"
          @confirm="confirmDraft"
          @reject="rejectDraft"
          @apply-suggestion="applySuggestion"
        />
      </div>
    </div>

    <DraftEditor v-model="editorOpen" :draft="editing" @saved="onSaved" />
  </div>
</template>

<style scoped>
.review {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.filters {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.filter {
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 13px;
  font-family: inherit;
  color: var(--ink-soft);
  cursor: pointer;
  transition: all 0.15s ease;
}

.filter:hover {
  border-color: #c7d2fe;
  color: var(--brand);
}

.filter.active {
  background: var(--ink);
  border-color: var(--ink);
  color: #fff;
}

.n {
  font-size: 11px;
  margin-left: 4px;
  opacity: 0.75;
}

.list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  align-items: start;
}

.review-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.origin {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink-muted);
  padding: 0 4px;
}

.origin-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.link {
  color: var(--brand);
  font-weight: 550;
  white-space: nowrap;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 60px 20px;
  color: #98a2b3;
  font-size: 13px;
}

.skeleton {
  padding: 20px;
  background: #fff;
  border-radius: var(--radius);
}

@media (max-width: 1100px) {
  .list {
    grid-template-columns: 1fr;
  }
}
</style>
