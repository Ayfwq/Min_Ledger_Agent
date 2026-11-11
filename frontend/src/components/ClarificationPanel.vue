<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiError, http } from '@/api/client'
import type { Clarification } from '@/api/types'

const props = defineProps<{ clarifications: Clarification[] }>()
const emit = defineEmits<{ changed: [] }>()

const answers = reactive<Record<string, string>>({})
const busy = ref<string | null>(null)

const FIELD_LABELS: Record<string, string> = {
  amount: '金额',
  txn_date: '消费日期',
  merchant: '商户',
  category: '类别',
}

const open = computed(() => props.clarifications.filter((c) => c.status === 'open'))
const history = computed(() =>
  props.clarifications.filter((c) => c.status !== 'open').sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
)

function fieldLabel(field: string) {
  return FIELD_LABELS[field] || field
}

async function submit(c: Clarification, action: 'answer' | 'unknown' | 'choose', choice?: 'new' | 'existing') {
  const value = answers[c.id]?.trim()
  if (action === 'answer' && !value) {
    ElMessage.warning('请先填写补充内容')
    return
  }
  busy.value = c.id
  try {
    await http.post(`/clarifications/${c.id}/answer`, {
      action,
      value: action === 'answer' ? value : undefined,
      choice,
    })
    ElMessage.success(action === 'unknown' ? '已记录为暂不提供' : '已提交')
    answers[c.id] = ''
    emit('changed')
  } catch (e) {
    ElMessage.error(apiError(e).message)
  } finally {
    busy.value = null
  }
}

function confirmAmbiguous(c: Clarification) {
  answers[c.id] = '正确'
  submit(c, 'answer')
}

async function cancel(c: Clarification) {
  try {
    await ElMessageBox.confirm('取消后该问题将关闭，草稿仍可在审核台编辑。', '取消澄清', {
      confirmButtonText: '取消问题',
      cancelButtonText: '继续回答',
      type: 'warning',
    })
  } catch {
    return
  }
  busy.value = c.id
  try {
    await http.post(`/clarifications/${c.id}/cancel`)
    ElMessage.success('已取消')
    emit('changed')
  } catch (e) {
    ElMessage.error(apiError(e).message)
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div class="panel">
    <div class="head">
      <div class="section-title">
        <el-icon><ChatDotRound /></el-icon>
        澄清对话
        <span v-if="open.length" class="count">{{ open.length }} 待回答</span>
      </div>
    </div>

    <div v-if="!clarifications.length" class="empty muted">
      暂无需澄清的信息。系统只在关键字段缺失或出现冲突时提问。
    </div>

    <div class="thread">
      <div v-for="c in history" :key="c.id" class="turn">
        <div class="bubble system">
          <span class="tag">{{ fieldLabel(c.field) }}{{ c.kind === 'conflict' ? ' · 冲突' : c.kind === 'ambiguous' ? ' · 待确认' : '' }}</span>
          {{ c.question }}
        </div>
        <div class="bubble user" :class="c.status">
          <template v-if="c.status === 'answered'">
            {{ c.answer?.value ?? '已补充' }}
          </template>
          <template v-else-if="c.status === 'resolved'">
            已确认使用：{{ c.answer?.value }}
          </template>
          <template v-else-if="c.status === 'unknown'">不知道 / 暂不提供</template>
          <template v-else-if="c.status === 'cancelled'">已取消</template>
        </div>
      </div>

      <div v-for="c in open" :key="c.id" class="open-card">
        <div class="open-head">
          <span class="field">{{ fieldLabel(c.field) }}</span>
          <el-tag v-if="c.blocking" size="small" type="warning" effect="plain" round>阻塞入账</el-tag>
          <el-tag v-else size="small" type="info" effect="plain" round>可选补充</el-tag>
          <span v-if="c.kind === 'conflict'" class="conflict-tag">需要确认</span>
        </div>
        <p class="question">{{ c.question }}</p>
        <p v-if="c.reason" class="reason">{{ c.reason }}</p>

        <template v-if="c.kind === 'conflict'">
          <div class="options">
            <el-button size="small" type="primary" plain :loading="busy === c.id" @click="submit(c, 'choose', 'existing')">
              {{ c.options?.existing_label || `使用识别值 ${c.options?.existing}` }}
            </el-button>
            <el-button size="small" type="warning" plain :loading="busy === c.id" @click="submit(c, 'choose', 'new')">
              {{ c.options?.new_label || `使用我补充的 ${c.options?.new}` }}
            </el-button>
          </div>
        </template>
        <template v-else>
          <div v-if="c.kind === 'ambiguous'" class="options">
            <el-button size="small" type="success" plain :loading="busy === c.id" @click="confirmAmbiguous(c)">
              识别正确
            </el-button>
            <span class="hint-inline">或直接输入正确的名称</span>
          </div>
          <div class="input-row">
            <el-input
              v-model="answers[c.id]"
              :placeholder="c.field === 'txn_date' ? '例如：2026-11-10 或“昨天”' : c.field === 'amount' ? '例如：35.5' : '请补充'"
              @keyup.enter="submit(c, 'answer')"
            />
            <el-button type="primary" :loading="busy === c.id" @click="submit(c, 'answer')">提交</el-button>
          </div>
          <div class="actions">
            <el-button link size="small" @click="submit(c, 'unknown')">不知道 / 暂不提供</el-button>
            <el-button link size="small" type="info" @click="cancel(c)">取消澄清</el-button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.empty {
  font-size: 13px;
  line-height: 1.6;
  padding: 14px;
  background: #f9fafb;
  border-radius: 10px;
}

.thread {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.turn {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.bubble {
  padding: 9px 12px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.6;
  max-width: 92%;
}

.bubble.system {
  background: #f4f6fb;
  color: #344054;
  border-top-left-radius: 4px;
}

.bubble.user {
  align-self: flex-end;
  background: var(--brand);
  color: #fff;
  border-top-right-radius: 4px;
}

.bubble.user.unknown,
.bubble.user.cancelled {
  background: #eef1f6;
  color: #667085;
}

.bubble.user.resolved {
  background: var(--green);
}

.tag {
  display: inline-block;
  font-size: 11px;
  color: var(--brand);
  margin-right: 6px;
  font-weight: 650;
}

.open-card {
  margin-top: 6px;
  border: 1px solid #e4e7ec;
  background: #fff;
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: 0 6px 20px rgba(16, 24, 40, 0.05);
}

.open-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.field {
  font-size: 12px;
  font-weight: 700;
  color: var(--ink);
}

.conflict-tag {
  margin-left: auto;
  font-size: 11px;
  color: var(--red);
  background: var(--red-soft);
  padding: 2px 8px;
  border-radius: 999px;
}

.question {
  font-size: 13.5px;
  color: var(--ink);
  line-height: 1.6;
}

.reason {
  font-size: 12px;
  color: var(--ink-muted);
}

.input-row {
  display: flex;
  gap: 8px;
}

.input-row :deep(.el-input) {
  flex: 1;
}

.actions {
  display: flex;
  gap: 14px;
}

.options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.options :deep(.el-button + .el-button) {
  margin-left: 0;
}
.hint-inline {
  font-size: 12px;
  color: var(--ink-muted);
}
</style>
