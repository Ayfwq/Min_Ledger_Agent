<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { http, PASSWORD_KEY, setUnauthorizedHandler } from './api/client'
import { useStatsStore } from './stores/stats'

const route = useRoute()

const authOpen = ref(false)
const password = ref('')
const authError = ref('')
const verifying = ref(false)
const statsStore = useStatsStore()

const navs = [
  { path: '/', label: '工作台', icon: 'HomeFilled' },
  { path: '/review', label: '审核台', icon: 'DocumentChecked' },
  { path: '/bills', label: '正式账单', icon: 'Tickets' },
]

const pageTitle = computed(() => (route.meta.title as string) || 'Mini Ledger')
const pageSubtitle = computed(() => (route.meta.subtitle as string) || '')

async function verify() {
  if (!password.value) {
    authError.value = '请输入访问密码'
    return
  }
  verifying.value = true
  authError.value = ''
  try {
    await http.post('/auth/verify', { password: password.value })
    localStorage.setItem(PASSWORD_KEY, password.value)
    authOpen.value = false
    ElMessage.success('验证通过')
    await statsStore.refresh()
    window.location.reload()
  } catch {
    authError.value = '密码不正确'
  } finally {
    verifying.value = false
  }
}

setUnauthorizedHandler(() => {
  authOpen.value = true
})

onMounted(() => {
  statsStore.refresh()
  setInterval(() => statsStore.refresh(), 15000)
})
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">¥</div>
        <div class="brand-text">
          <strong>Mini Ledger</strong>
          <span>Agent</span>
        </div>
      </div>

      <nav class="nav">
        <RouterLink
          v-for="item in navs"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: item.path === '/' ? route.path === '/' : route.path.startsWith(item.path) }"
        >
          <el-icon :size="18"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
          <span v-if="item.path === '/review' && statsStore.pendingReview" class="nav-badge">
            {{ statsStore.pendingReview }}
          </span>
        </RouterLink>
      </nav>

      <div class="side-foot">
        <div class="side-stats">
          <div class="side-stat">
            <strong class="mono">{{ statsStore.pendingReview }}</strong>
            <span>待审核</span>
          </div>
          <div class="side-stat warn">
            <strong class="mono">{{ statsStore.needsClarification }}</strong>
            <span>待澄清</span>
          </div>
        </div>
        <div class="health" :class="{ down: !statsStore.online }">
          <span class="dot" />
          {{ statsStore.online ? '服务正常' : '服务不可用' }}
        </div>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p class="sub">{{ pageSubtitle }}</p>
        </div>
        <div class="top-actions">
          <div class="stat-chip">
            <span class="stat-ico"><el-icon><Wallet /></el-icon></span>
            <div class="stat-body">
              <span>已入账</span>
              <strong class="mono">{{ statsStore.bills }} 笔</strong>
            </div>
          </div>
          <div class="stat-chip accent">
            <span class="stat-ico"><el-icon><TrendCharts /></el-icon></span>
            <div class="stat-body">
              <span>累计金额</span>
              <strong class="mono">¥ {{ statsStore.totalAmount.toFixed(2) }}</strong>
            </div>
          </div>
        </div>
      </header>

      <main class="content">
        <RouterView v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </RouterView>
      </main>
    </div>

    <el-dialog v-model="authOpen" title="需要访问密码" width="360px" :close-on-click-modal="false">
      <p class="muted" style="margin-bottom: 12px; font-size: 13px">该记账服务已开启访问保护，请输入密码。</p>
      <el-input v-model="password" type="password" show-password placeholder="访问密码" @keyup.enter="verify" />
      <p v-if="authError" class="err">{{ authError }}</p>
      <template #footer>
        <el-button type="primary" :loading="verifying" @click="verify">进入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.shell {
  min-height: 100vh;
  display: flex;
}

.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  width: 232px;
  padding: 22px 16px;
  display: flex;
  flex-direction: column;
  gap: 26px;
  background: radial-gradient(1200px 400px at -20% -10%, #1e293b 0%, #0f172a 55%);
  color: #cbd5e1;
  z-index: 20;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 6px;
}

.brand-mark {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 19px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  box-shadow: 0 6px 18px rgba(99, 102, 241, 0.45);
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
  color: #e2e8f0;
  font-size: 15px;
}

.brand-text span {
  font-size: 11px;
  letter-spacing: 0.18em;
  color: #94a3b8;
  text-transform: uppercase;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  color: #cbd5e1;
  font-size: 14px;
  transition: all 0.15s ease;
}

.nav-item:hover {
  background: rgba(148, 163, 184, 0.12);
  color: #fff;
}

.nav-item.active {
  background: rgba(99, 102, 241, 0.22);
  color: #fff;
  box-shadow: inset 0 0 0 1px rgba(129, 140, 248, 0.35);
}

.nav-badge {
  margin-left: auto;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: rgba(251, 191, 36, 0.18);
  color: #fbbf24;
  font-size: 11px;
  font-weight: 650;
  display: grid;
  place-items: center;
}

.stat-chip.accent .stat-ico {
  background: #fff;
  color: var(--brand);
}

.side-foot {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border-radius: 14px;
  background: rgba(148, 163, 184, 0.08);
  border: 1px solid rgba(148, 163, 184, 0.12);
  font-size: 12px;
}

.side-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.side-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(148, 163, 184, 0.1);
}

.side-stat strong {
  font-size: 18px;
  color: #f1f5f9;
  line-height: 1.1;
}

.side-stat span {
  font-size: 11px;
  color: #94a3b8;
}

.side-stat.warn strong {
  color: #fbbf24;
}

.health {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 7px;
  color: #86efac;
}

.health.down {
  color: #fca5a5;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 0 3px rgba(134, 239, 172, 0.16);
}

.main {
  flex: 1;
  margin-left: 232px;
  min-width: 0;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 32px;
  background: rgba(246, 247, 251, 0.86);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(234, 236, 240, 0.9);
}

.topbar h1 {
  font-size: 20px;
}

.topbar .sub {
  margin-top: 3px;
  font-size: 12.5px;
  color: var(--ink-muted);
}

.top-actions {
  display: flex;
  gap: 10px;
}

.stat-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px 8px 10px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid var(--line);
  box-shadow: var(--shadow-card);
  min-width: 128px;
}

.stat-ico {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: #f2f4f7;
  color: #475467;
  flex: none;
}

.stat-body {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.stat-body span {
  font-size: 11px;
  color: var(--ink-muted);
}

.stat-chip strong {
  font-size: 14px;
  color: var(--ink);
}

.stat-chip.accent {
  background: var(--brand-soft);
  border-color: #e0e7ff;
}

.stat-chip.accent strong {
  color: var(--brand);
}

.content {
  padding: 26px 32px 72px;
  max-width: 1320px;
  margin: 0 auto;
}

.err {
  margin-top: 8px;
  color: var(--red);
  font-size: 12.5px;
}

@media (max-width: 960px) {
  .sidebar {
    width: 72px;
    padding: 18px 10px;
    align-items: center;
  }

  .brand-text,
  .nav-item span,
  .side-foot {
    display: none;
  }

  .main {
    margin-left: 72px;
  }

  .content {
    padding: 20px 18px 80px;
  }

  .topbar {
    padding: 14px 18px;
  }

  .top-actions {
    display: none;
  }
}
</style>
