<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string; pulse?: boolean }>()

const MAP: Record<string, { label: string; type: 'info' | 'success' | 'warning' | 'danger' | 'primary'; cls: string }> = {
  pending: { label: '排队中', type: 'info', cls: 'pending' },
  processing: { label: '识别中', type: 'warning', cls: 'processing' },
  drafting: { label: '生成中', type: 'warning', cls: 'processing' },
  needs_clarification: { label: '待澄清', type: 'warning', cls: 'clarify' },
  ready_for_review: { label: '待审核', type: 'primary', cls: 'review' },
  confirmed: { label: '已入账', type: 'success', cls: 'ok' },
  rejected: { label: '已拒绝', type: 'info', cls: 'rejected' },
  failed: { label: '失败', type: 'danger', cls: 'failed' },
}

const meta = computed(() => MAP[props.status] || { label: props.status, type: 'info' as const, cls: '' })
const isBusy = computed(() => props.status === 'processing' || props.status === 'pending' || props.status === 'drafting')
</script>

<template>
  <span class="status" :class="[meta.cls, { busy: isBusy && pulse !== false }]">
    <span v-if="isBusy" class="spin" />
    {{ meta.label }}
  </span>
</template>

<style scoped>
.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.6;
  white-space: nowrap;
  border: 1px solid transparent;
}

.pending {
  background: #f2f4f7;
  color: #475467;
}

.processing {
  background: var(--amber-soft);
  color: var(--amber);
  border-color: #fed7aa;
}

.clarify {
  background: #fffbeb;
  color: #b45309;
  border-color: #fde68a;
}

.review {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: #e0e7ff;
}

.ok {
  background: var(--green-soft);
  color: var(--green);
  border-color: #a7f3d0;
}

.rejected {
  background: #f8fafc;
  color: #64748b;
  border-color: #e2e8f0;
}

.failed {
  background: var(--red-soft);
  color: var(--red);
  border-color: #fecaca;
}

.spin {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: 2px solid currentColor;
  border-right-color: transparent;
  animation: rotate 0.8s linear infinite;
}

@keyframes rotate {
  to {
    transform: rotate(360deg);
  }
}
</style>
