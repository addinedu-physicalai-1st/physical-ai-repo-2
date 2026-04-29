import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api, ApiError } from '@/api/client'
import type { AuthUser, Role } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)

  const isAuthenticated = computed(() => user.value !== null)
  const role = computed<Role | null>(() => user.value?.role ?? null)

  async function login(email: string, password: string): Promise<void> {
    await api.postForm('/api/auth/cookie/login', { username: email, password })
    await fetchMe()
  }

  async function logout(): Promise<void> {
    try {
      await api.post('/api/auth/cookie/logout', {})
    } finally {
      user.value = null
    }
  }

  async function fetchMe(): Promise<void> {
    try {
      user.value = await api.get<AuthUser>('/api/users/me')
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        user.value = null
        return
      }
      throw e
    }
  }

  return { user, isAuthenticated, role, login, logout, fetchMe }
})
