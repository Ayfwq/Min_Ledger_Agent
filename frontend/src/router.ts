import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'workbench',
      component: () => import('./views/Workbench.vue'),
      meta: { title: '工作台', subtitle: '记录一笔，剩下的交给它' },
    },
    {
      path: '/review',
      name: 'review',
      component: () => import('./views/Review.vue'),
      meta: { title: '审核台', subtitle: '核对来源，确认后入账' },
    },
    {
      path: '/bills',
      name: 'bills',
      component: () => import('./views/Bills.vue'),
      meta: { title: '正式账单', subtitle: '每一笔都有据可查' },
    },
    {
      path: '/inputs/:id',
      name: 'input-detail',
      component: () => import('./views/InputDetail.vue'),
      meta: { title: '处理详情', subtitle: '澄清、数据源与完整轨迹' },
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})
