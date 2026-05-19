import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { Role } from '@/types'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: Role
  }
}

const routes = [
  { path: '/', component: () => import('@/views/RoleLanding.vue') },

  { path: '/teacher/login', component: () => import('@/views/teacher/Login.vue') },
  {
    path: '/teacher',
    component: () => import('@/layouts/TeacherLayout.vue'),
    meta: { requiresAuth: 'teacher' as Role },
    children: [
      { path: '', redirect: '/teacher/dashboard' },
      { path: 'dashboard',     component: () => import('@/views/teacher/Dashboard.vue') },
      { path: 'children',      component: () => import('@/views/teacher/Children.vue') },
      { path: 'children/new',  component: () => import('@/views/teacher/Register.vue') },
      { path: 'menu',      component: () => import('@/views/teacher/Menu.vue') },
      { path: 'reports',   component: () => import('@/views/teacher/Reports.vue') },
    ],
  },

  { path: '/parent/login', component: () => import('@/views/parent/Login.vue') },
  {
    path: '/parent',
    component: () => import('@/layouts/ParentLayout.vue'),
    meta: { requiresAuth: 'parent' as Role },
    children: [
      { path: '', redirect: '/parent/home' },
      { path: 'home',       component: () => import('@/views/parent/Home.vue') },
      { path: 'attendance', component: () => import('@/views/parent/Attendance.vue') },
      { path: 'menu',       component: () => import('@/views/parent/Menu.vue') },
      { path: 'photos',     component: () => import('@/views/parent/Photos.vue') },
      { path: 'report',     component: () => import('@/views/parent/Report.vue') },
      { path: 'settings',   component: () => import('@/views/parent/Settings.vue') },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

let sessionChecked = false

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (!sessionChecked) {
    await auth.fetchMe().catch(() => {})
    sessionChecked = true
  }

  // 이미 로그인 상태로 login 접근 → 각 메인으로
  if (to.path === '/teacher/login' && auth.role === 'teacher') return '/teacher/dashboard'
  if (to.path === '/parent/login'  && auth.role === 'parent')  return '/parent/home'

  const required = to.meta.requiresAuth
  if (!required) return true

  if (auth.role !== required) {
    return `/${required}/login`
  }

  return true
})

export default router
