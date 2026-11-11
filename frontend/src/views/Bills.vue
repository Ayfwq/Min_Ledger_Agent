<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiError, http } from '@/api/client'
import type { Bill } from '@/api/types'
import { CATEGORIES } from '@/constants'

const bills = ref<Bill[]>([])
const loading = ref(false)
const keyword = ref('')
const category = ref('')
const month = ref('')

const filtered = computed(() =>
  bills.value.filter((b) => {
    if (category.value && b.category !== category.value) return false
    if (month.value && !b.txn_date.startsWith(month.value)) return false
    if (keyword.value) {
      const k = keyword.value.trim().toLowerCase()
      const hay = `${b.merchant || ''} ${b.note || ''} ${b.category || ''}`.toLowerCase()
      if (!hay.includes(k)) return false
    }
    return true
  }),
)

const total = computed(() => filtered.value.reduce((sum, b) => sum + Number(b.amount), 0))
const thisMonth = computed(() => {
  const now = new Date()
  const key = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  return bills.value
    .filter((b) => b.txn_date.startsWith(key))
    .reduce((sum, b) => sum + Number(b.amount), 0)
})

async function load() {
  loading.value = true
  try {
    const { data } = await http.get<Bill[]>('/bills', { params: { limit: 500 } })
    bills.value = data
  } catch (e) {
    ElMessage.error(apiError(e).message)
  } finally {
    loading.value = false
  }
}

function money(v: string | number) {
  return Number(v).toFixed(2)
}

onMounted(load)
</script>

<template>
  <div class="bills">
    <div class="summary">
      <div class="stat card">
        <span>累计笔数</span>
        <strong class="mono">{{ bills.length }}</strong>
        <small class="muted">全部正式账单</small>
      </div>
      <div class="stat card">
        <span>本月支出</span>
        <strong class="mono">¥ {{ money(thisMonth) }}</strong>
        <small class="muted">按消费日期统计</small>
      </div>
      <div class="stat card">
        <span>当前筛选合计</span>
        <strong class="mono">¥ {{ money(total) }}</strong>
        <small class="muted">{{ filtered.length }} 笔</small>
      </div>
    </div>

    <section class="card table-card">
      <div class="filters">
        <el-input v-model="keyword" placeholder="搜索商户 / 说明" clearable class="search">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="category" placeholder="全部类别" clearable class="select">
          <el-option v-for="c in CATEGORIES" :key="c" :label="c" :value="c" />
        </el-select>
        <el-date-picker v-model="month" type="month" value-format="YYYY-MM" placeholder="全部月份" class="select" />
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
      </div>

      <el-table :data="filtered" v-loading="loading" style="width: 100%" empty-text="还没有正式账单">
        <el-table-column prop="txn_date" label="消费日期" width="120" />
        <el-table-column label="商户" min-width="150">
          <template #default="{ row }">
            <span :class="{ muted: !row.merchant }">{{ row.merchant || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类别" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.category" size="small" effect="plain" round>{{ row.category }}</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="金额" width="130" align="right">
          <template #default="{ row }">
            <span class="amount mono">¥ {{ money(row.amount) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="180">
          <template #default="{ row }">
            <span class="muted">{{ row.note || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="入账时间" width="170">
          <template #default="{ row }">
            <span class="muted mono">{{ new Date(row.created_at).toLocaleString('zh-CN', { hour12: false }) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.bills {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.stat {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat span {
  font-size: 12px;
  color: var(--ink-muted);
}

.stat strong {
  font-size: 24px;
  letter-spacing: -0.02em;
}

.stat small {
  font-size: 11.5px;
}

.table-card {
  padding: 16px 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.filters {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.search {
  width: 240px;
}

.select {
  width: 160px;
}

.amount {
  font-weight: 650;
}

@media (max-width: 900px) {
  .summary {
    grid-template-columns: 1fr;
  }

  .search,
  .select {
    width: 100%;
  }
}
</style>
