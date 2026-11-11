<script setup lang="ts">
import { computed } from 'vue'
import type { TraceEvent } from '@/api/types'

const props = defineProps<{ events: TraceEvent[] }>()

const LABELS: Record<string, string> = {
  'input.created': '创建输入',
  extract: '信息抽取',
  build_drafts: '生成草稿',
  'draft.created': '草稿条目',
  'pipeline.done': '处理完成',
  'clarification.answered': '用户补充',
  'clarification.unknown': '暂不提供',
  'clarification.cancelled': '取消澄清',
  'clarification.conflict_raised': '发现冲突',
  'clarification.conflict_resolved': '冲突已确认',
  'draft.edited': '人工编辑',
  'draft.confirmed': '确认入账',
  'draft.rejected': '拒绝草稿',
  'input.retry': '手动重试',
  job: '队列任务',
}

function label(step: string) {
  if (LABELS[step]) return LABELS[step]
  if (step.startsWith('datasource.')) {
    return step.includes('duplicate') ? '查重数据源' : '商户目录数据源'
  }
  return step
}

function time(iso: string) {
  const d = new Date(iso)
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

const ordered = computed(() => [...props.events].sort((a, b) => (a.id > b.id ? 1 : -1)))
</script>

<template>
  <div class="timeline">
    <div v-if="!ordered.length" class="empty muted">暂无处理记录</div>
    <div v-for="event in ordered" :key="event.id" class="row" :class="event.status">
      <div class="rail">
        <span class="dot" />
      </div>
      <div class="body">
        <div class="line">
          <span class="step">{{ label(event.step) }}</span>
          <span class="state">{{ event.status }}</span>
          <span class="time mono">{{ time(event.created_at) }}</span>
          <span v-if="event.duration_ms !== null" class="dur mono">{{ event.duration_ms }}ms</span>
        </div>
        <p v-if="event.message" class="msg">{{ event.message }}</p>
        <el-collapse v-if="event.payload" class="payload">
          <el-collapse-item title="查看详情" :name="String(event.id)">
            <pre>{{ JSON.stringify(event.payload, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>
  </div>
</template>

<style scoped>
.timeline {
  display: flex;
  flex-direction: column;
}

.empty {
  font-size: 13px;
  padding: 12px 0;
}

.row {
  display: flex;
  gap: 12px;
}

.rail {
  position: relative;
  width: 12px;
  display: flex;
  justify-content: center;
  padding-top: 6px;
}

.rail::before {
  content: '';
  position: absolute;
  top: 16px;
  bottom: -4px;
  width: 2px;
  background: #eef0f4;
}

.row:last-child .rail::before {
  display: none;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #cbd5e1;
  position: relative;
  z-index: 1;
  box-shadow: 0 0 0 3px #fff;
}

.row.ok .dot {
  background: #12b76a;
}

.row.failed .dot {
  background: #f04438;
}

.row.retried .dot {
  background: #f79009;
}

.body {
  flex: 1;
  padding-bottom: 14px;
  min-width: 0;
}

.line {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.step {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}

.state {
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  background: #f2f4f7;
  padding: 1px 6px;
  border-radius: 4px;
}

.row.failed .state {
  background: var(--red-soft);
  color: var(--red);
}

.time,
.dur {
  font-size: 11px;
  color: #98a2b3;
}

.msg {
  margin-top: 3px;
  font-size: 12.5px;
  color: var(--ink-soft);
  line-height: 1.55;
  word-break: break-word;
}

.payload {
  margin-top: 2px;
  border: none;
}

.payload :deep(.el-collapse-item__header) {
  height: 24px;
  border: none;
  font-size: 11.5px;
  color: var(--ink-muted);
  background: transparent;
}

.payload :deep(.el-collapse-item__wrap) {
  border: none;
  background: transparent;
}

.payload pre {
  margin: 4px 0 0;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 11.5px;
  line-height: 1.5;
  color: #344054;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
