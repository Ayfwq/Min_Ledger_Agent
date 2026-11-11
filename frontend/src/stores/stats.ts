import { defineStore } from 'pinia'
import { http } from '@/api/client'
import type { Stats } from '@/api/types'

export const useStatsStore = defineStore('stats', {
  state: () => ({
    stats: null as Stats | null,
    online: true,
    loading: false,
  }),
  getters: {
    bills: (s) => s.stats?.bills ?? 0,
    totalAmount: (s) => s.stats?.total_amount ?? 0,
    pendingReview: (s) => s.stats?.pending_review ?? 0,
    needsClarification: (s) => s.stats?.needs_clarification ?? 0,
    inputs: (s) => s.stats?.inputs ?? 0,
  },
  actions: {
    async refresh() {
      this.loading = true
      try {
        const { data } = await http.get<Stats>('/stats')
        this.stats = data
        this.online = true
      } catch {
        this.online = false
      } finally {
        this.loading = false
      }
    },
  },
})
