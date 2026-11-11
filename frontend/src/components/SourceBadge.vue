<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ source?: string | null }>()

const meta = computed(() => {
  switch (props.source) {
    case 'user':
      return { label: '用户补充', cls: 'user' }
    case 'image':
      return { label: '截图识别', cls: 'image' }
    case 'datasource':
      return { label: '数据源', cls: 'ds' }
    case 'text':
      return { label: '文本提取', cls: 'text' }
    default:
      return null
  }
})
</script>

<template>
  <span v-if="meta" class="badge" :class="meta.cls">{{ meta.label }}</span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 6px;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.01em;
  border: 1px solid transparent;
}

.text {
  background: #eff8ff;
  color: #1570ef;
  border-color: #d1e9ff;
}

.image {
  background: #f4f3ff;
  color: #6941c6;
  border-color: #e9d7fe;
}

.user {
  background: #ecfdf3;
  color: #027a48;
  border-color: #d1fadf;
}

.ds {
  background: #fff6ed;
  color: #c4320a;
  border-color: #fdead7;
}
</style>
