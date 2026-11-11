<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiError, http } from '@/api/client'
import type { Draft } from '@/api/types'
import { CATEGORIES } from '@/constants'

const props = defineProps<{ modelValue: boolean; draft: Draft | null }>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean]; saved: [draft: Draft] }>()

const saving = ref(false)
const form = reactive<{
  amount: number | null
  txn_date: string | null
  merchant: string
  category: string
  note: string
}>({ amount: null, txn_date: null, merchant: '', category: '', note: '' })

watch(
  () => props.draft,
  (d) => {
    if (!d) return
    form.amount = d.amount === null ? null : Number(d.amount)
    form.txn_date = d.txn_date
    form.merchant = d.merchant || ''
    form.category = d.category || ''
    form.note = d.note || ''
  },
  { immediate: true },
)

function buildPayload(force = false) {
  return {
    amount: form.amount,
    txn_date: form.txn_date,
    merchant: form.merchant || null,
    category: form.category || null,
    note: form.note || null,
    ...(force ? { force: true } : {}),
  }
}

async function save(force = false) {
  if (!props.draft) return
  saving.value = true
  try {
    const { data } = await http.patch<Draft>(`/drafts/${props.draft.id}`, buildPayload(force))
    ElMessage.success('已保存')
    emit('saved', data)
    emit('update:modelValue', false)
  } catch (e) {
    const err = apiError(e)
    if (err.code === 'value_conflict' && err.conflicts?.length) {
      const detail = err.conflicts
        .map((c) => `「${c.field}」原为 ${c.existing}，改为 ${c.proposed}`)
        .join('\n')
      try {
        await ElMessageBox.confirm(`修改内容与原始识别结果不一致：\n${detail}\n\n确认覆盖吗？`, '请确认修改', {
          confirmButtonText: '确认覆盖',
          cancelButtonText: '返回修改',
          type: 'warning',
        })
      } catch {
        saving.value = false
        return
      }
      await save(true)
      return
    }
    ElMessage.error(err.message)
  } finally {
    saving.value = false
  }
}

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="编辑草稿"
    width="520px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="draft" class="form">
      <div class="row">
        <label>金额</label>
        <el-input-number v-model="form.amount" :precision="2" :min="0" :step="1" controls-position="right" />
        <span class="src">来源：{{ draft.field_sources.amount === 'user' ? '用户' : '识别' }}</span>
      </div>
      <div class="row">
        <label>消费日期</label>
        <el-date-picker v-model="form.txn_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" />
      </div>
      <div class="row">
        <label>商户</label>
        <el-input v-model="form.merchant" placeholder="商户 / 平台名称" clearable />
      </div>
      <div class="row">
        <label>类别</label>
        <el-select v-model="form.category" placeholder="选择类别" clearable>
          <el-option v-for="c in CATEGORIES" :key="c" :label="c" :value="c" />
        </el-select>
      </div>
      <div class="row">
        <label>说明</label>
        <el-input v-model="form.note" type="textarea" :rows="2" placeholder="备注" />
      </div>
      <p class="tip muted">
        关键字段（金额 / 日期）不可为空；若修改识别值需二次确认，避免静默覆盖。
      </p>
    </div>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save(false)">保存修改</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.row {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
}

.row label {
  font-size: 13px;
  color: var(--ink-soft);
}

.row :deep(.el-input-number),
.row :deep(.el-date-editor),
.row :deep(.el-select) {
  width: 100%;
}

.tip {
  font-size: 12px;
  line-height: 1.6;
  background: #f9fafb;
  padding: 10px 12px;
  border-radius: 8px;
}

.src {
  font-size: 11px;
  color: var(--ink-muted);
}
</style>
