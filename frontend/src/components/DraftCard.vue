<script setup lang="ts">
import { computed } from 'vue'
import type { Draft } from '@/api/types'
import StatusTag from './StatusTag.vue'
import SourceBadge from './SourceBadge.vue'

const props = withDefaults(
  defineProps<{
    draft: Draft
    actions?: boolean
    highlight?: boolean
  }>(),
  { actions: true, highlight: false },
)

const emit = defineEmits<{
  edit: [draft: Draft]
  confirm: [draft: Draft]
  reject: [draft: Draft]
  'apply-suggestion': [draft: Draft, name: string, category: string]
}>()

const amountText = computed(() => {
  if (props.draft.amount === null || props.draft.amount === undefined) return '—'
  return Number(props.draft.amount).toFixed(2)
})

const criticalMissing = computed(() => !props.draft.amount || !props.draft.txn_date)
const canConfirm = computed(
  () => props.draft.status !== 'confirmed' && props.draft.status !== 'rejected' && !criticalMissing.value && !props.draft.conflict,
)

const merchantSuggestion = computed(() => {
  const s = props.draft.suggestions?.merchant
  if (!s?.matched || !s.merchant) return null
  if (props.draft.merchant && s.merchant.name === props.draft.merchant) return null
  return s.merchant
})

const warnings = computed(() => props.draft.warnings || [])
const duplicates = computed(() => props.draft.duplicate_candidates || [])

const sourceOf = (field: string) => props.draft.field_sources?.[field]
</script>

<template>
  <article class="draft" :class="{ highlight, done: draft.status === 'confirmed' }">
    <header class="head">
      <div class="left">
        <span class="seq">第 {{ draft.seq + 1 }} 笔</span>
        <StatusTag :status="draft.status" />
        <span v-if="draft.bill_id" class="bill-no">账单已生成</span>
      </div>
      <div class="amount mono">
        <span class="cur">¥</span>{{ amountText }}
      </div>
    </header>

    <div class="fields">
      <div class="field">
        <div class="label">消费日期 <SourceBadge :source="sourceOf('txn_date')" /></div>
        <div class="value mono" :class="{ empty: !draft.txn_date }">{{ draft.txn_date || '待补充' }}</div>
      </div>
      <div class="field">
        <div class="label">商户 <SourceBadge :source="sourceOf('merchant')" /></div>
        <div class="value" :class="{ empty: !draft.merchant }">{{ draft.merchant || '未提供' }}</div>
      </div>
      <div class="field">
        <div class="label">类别 <SourceBadge :source="sourceOf('category')" /></div>
        <div class="value">
          <el-tag v-if="draft.category" size="small" effect="plain" round>{{ draft.category }}</el-tag>
          <span v-else class="empty">未分类</span>
        </div>
      </div>
      <div class="field wide">
        <div class="label">说明</div>
        <div class="value" :class="{ empty: !draft.note }">{{ draft.note || '—' }}</div>
      </div>
    </div>

    <div v-if="merchantSuggestion" class="hint suggestion">
      <el-icon><MagicStick /></el-icon>
      <div class="hint-body">
        商户目录建议：<strong>{{ merchantSuggestion.name }}</strong>
        <span class="muted">（{{ merchantSuggestion.category }}，置信度 {{ (merchantSuggestion.confidence ?? 0).toFixed(2) }}）</span>
      </div>
      <el-button
        size="small"
        text
        type="primary"
        @click="emit('apply-suggestion', draft, merchantSuggestion.name, merchantSuggestion.category)"
      >
        采用
      </el-button>
    </div>

    <div v-if="duplicates.length" class="hint duplicate">
      <el-icon><WarningFilled /></el-icon>
      <div class="hint-body">
        疑似重复 {{ duplicates.length }} 条：
        <span v-for="(d, i) in duplicates.slice(0, 2)" :key="d.id" class="dup-item">
          {{ d.kind === 'bill' ? '账单' : '草稿' }} ¥{{ d.amount.toFixed(2) }} · {{ d.txn_date }} ·
          {{ d.merchant || '未知商户' }}{{ i < Math.min(duplicates.length, 2) - 1 ? '；' : '' }}
        </span>
        <span class="muted">（是否入账由你决定）</span>
      </div>
    </div>

    <div v-if="draft.conflict" class="hint conflict">
      <el-icon><CircleCloseFilled /></el-icon>
      <div class="hint-body">
        存在未确认冲突：
        <span v-for="(v, k) in draft.conflict" :key="k">
          {{ k }} 识别为 {{ v.existing }}，你补充为 {{ v.proposed }}
        </span>
      </div>
    </div>

    <ul v-if="warnings.length" class="warnings">
      <li v-for="(w, idx) in warnings" :key="idx" :class="w.severity">
        <el-icon :size="13">
          <Warning v-if="w.severity === 'warning'" />
          <CircleClose v-else-if="w.severity === 'error'" />
          <InfoFilled v-else />
        </el-icon>
        {{ w.message }}
      </li>
    </ul>

    <footer v-if="actions" class="foot">
      <el-button size="small" :disabled="draft.status === 'confirmed'" @click="emit('edit', draft)">
        <el-icon><EditPen /></el-icon>编辑
      </el-button>
      <div class="spacer" />
      <el-button
        size="small"
        type="primary"
        :disabled="!canConfirm"
        @click="emit('confirm', draft)"
      >
        确认入账
      </el-button>
      <el-button
        size="small"
        :disabled="draft.status === 'confirmed' || draft.status === 'rejected'"
        @click="emit('reject', draft)"
      >
        拒绝
      </el-button>
    </footer>
  </article>
</template>

<style scoped>
.draft {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition: box-shadow 0.18s ease, border-color 0.18s ease;
}

.draft:hover {
  box-shadow: var(--shadow-card);
}

.draft.highlight {
  border-color: #c7d2fe;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.08);
}

.draft.done {
  background: linear-gradient(180deg, #f7fdf9, #fff);
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.seq {
  font-size: 12px;
  font-weight: 650;
  color: var(--ink-muted);
}

.bill-no {
  font-size: 11px;
  color: var(--green);
  background: var(--green-soft);
  padding: 2px 8px;
  border-radius: 999px;
}

.amount {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ink);
}

.cur {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-muted);
  margin-right: 2px;
}

.fields {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px 16px;
  padding: 12px 0 2px;
  border-top: 1px dashed var(--line);
}

.field.wide {
  grid-column: span 3;
}

.label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--ink-muted);
  margin-bottom: 4px;
}

.value {
  font-size: 13.5px;
  color: var(--ink);
  word-break: break-all;
}

.value.empty {
  color: #98a2b3;
}

.hint {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 12px;
  border-radius: 10px;
  font-size: 12.5px;
  line-height: 1.55;
}

.hint.suggestion {
  background: #f5f8ff;
  color: #3538cd;
  border: 1px solid #e0e7ff;
  align-items: center;
}

.hint.duplicate {
  background: var(--amber-soft);
  color: #9a3412;
  border: 1px solid #fed7aa;
}

.hint.conflict {
  background: var(--red-soft);
  color: #b42318;
  border: 1px solid #fecaca;
}

.hint-body {
  flex: 1;
}

.dup-item {
  font-weight: 600;
}

.warnings {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12px;
}

.warnings li {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #b54708;
}

.warnings li.error {
  color: var(--red);
}

.warnings li.info {
  color: var(--ink-muted);
}

.foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
  border-top: 1px dashed var(--line);
  padding-top: 12px;
}

.spacer {
  flex: 1;
}

@media (max-width: 640px) {
  .fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .field.wide {
    grid-column: span 2;
  }
}
</style>
