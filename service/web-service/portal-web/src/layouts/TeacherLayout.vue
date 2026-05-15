<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Icon from '@/components/common/Icon.vue'
import NavItem from '@/components/common/NavItem.vue'
import BaseAvatar from '@/components/common/BaseAvatar.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const items = [
  { to: '/teacher/dashboard', icon: 'layout-dashboard', label: '출결 보드' },
  { to: '/teacher/children',  icon: 'users-round',     label: '어린이 관리' },
  { to: '/teacher/menu',      icon: 'utensils',        label: '점심메뉴' },
  { to: '/teacher/reports',   icon: 'file-text',       label: '일과 보고서' },
]

const userMenuOpen = ref(false)
const userMenuRef = ref<HTMLElement | null>(null)
const drawerOpen = ref(false)

function onClickOutsideUserMenu(e: MouseEvent) {
  if (!userMenuOpen.value) return
  if (userMenuRef.value && !userMenuRef.value.contains(e.target as Node)) userMenuOpen.value = false
}
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    drawerOpen.value = false
    userMenuOpen.value = false
  }
}
onMounted(() => {
  document.addEventListener('click', onClickOutsideUserMenu)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onClickOutsideUserMenu)
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})

watch(drawerOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})
watch(() => route.fullPath, () => { drawerOpen.value = false })

async function handleLogout() {
  userMenuOpen.value = false
  drawerOpen.value = false
  await auth.logout()
  router.push('/')
}
</script>

<template>
  <div class="layout">
    <header class="mobile-bar">
      <button
        class="mobile-bar__btn"
        type="button"
        :aria-expanded="drawerOpen"
        aria-label="메뉴 열기"
        @click="drawerOpen = true"
      >
        <Icon name="menu" :size="22" />
      </button>
      <div class="mobile-bar__brand">
        <span class="mobile-bar__mark"><Icon name="graduation-cap" :size="16" /></span>
        <strong>pingdergarten</strong>
      </div>
    </header>

    <div
      v-if="drawerOpen"
      class="overlay"
      aria-hidden="true"
      @click="drawerOpen = false"
    />

    <aside class="sidebar" :class="{ 'sidebar--open': drawerOpen }" role="navigation">
      <div class="sidebar__brand">
        <span class="sidebar__brand-mark">
          <Icon name="graduation-cap" :size="20" />
        </span>
        <div class="sidebar__brand-text">
          <strong>pingdergarten</strong>
          <span>교사 포털</span>
        </div>
        <button
          class="sidebar__close"
          type="button"
          aria-label="메뉴 닫기"
          @click="drawerOpen = false"
        >
          <Icon name="x" :size="20" />
        </button>
      </div>

      <nav class="sidebar__nav">
        <NavItem v-for="i in items" :key="i.to" :to="i.to" :icon="i.icon" :label="i.label" variant="sidebar" />
      </nav>

      <div ref="userMenuRef" class="sidebar__user" :class="{ 'is-open': userMenuOpen }">
        <button class="user-trigger" @click="userMenuOpen = !userMenuOpen">
          <BaseAvatar :name="auth.user?.name ?? '교사'" :size="32" />
          <div class="user-trigger__text">
            <strong>{{ auth.user?.name ?? '선생님' }}</strong>
            <span>교사</span>
          </div>
          <Icon name="more-vertical" :size="16" />
        </button>
        <div v-if="userMenuOpen" class="user-menu">
          <button class="user-menu__item user-menu__item--danger" @click="handleLogout">
            <Icon name="log-out" :size="16" />
            <span>로그아웃</span>
          </button>
        </div>
      </div>
    </aside>

    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.layout { display: flex; min-height: 100vh; background: var(--color-surface-base); }

.mobile-bar { display: none; }

.sidebar {
  width: 240px;
  background: var(--color-surface-inverse);
  color: var(--color-text-on-inverse);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar__brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-5);
  border-bottom: 1px solid var(--color-border-on-inverse);
}
.sidebar__brand-mark {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--color-brand-primary);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.sidebar__brand-text { display: flex; flex-direction: column; flex: 1; }
.sidebar__brand-text strong { font-weight: var(--font-weight-semibold); font-size: var(--font-size-sm); }
.sidebar__brand-text span { font-size: var(--font-size-xs); color: var(--color-text-on-inverse-muted); }

.sidebar__close {
  display: none;
  background: transparent;
  border: none;
  color: var(--color-text-on-inverse-muted);
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background var(--motion-base) var(--motion-ease);
}
.sidebar__close:hover { background: rgba(255, 255, 255, 0.06); color: var(--color-text-on-inverse); }

.sidebar__nav {
  display: flex;
  flex-direction: column;
  padding: var(--space-3) 0;
  flex: 1;
  gap: 2px;
}

.sidebar__user {
  position: relative;
  border-top: 1px solid var(--color-border-on-inverse);
  padding: var(--space-3);
}
.user-trigger {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  background: transparent;
  border: none;
  padding: var(--space-2);
  border-radius: var(--radius-md);
  color: var(--color-text-on-inverse);
  cursor: pointer;
  transition: background var(--motion-base) var(--motion-ease);
}
.user-trigger:hover { background: rgba(255, 255, 255, 0.04); }
.user-trigger__text { flex: 1; text-align: left; display: flex; flex-direction: column; }
.user-trigger__text strong { font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); }
.user-trigger__text span { font-size: var(--font-size-xs); color: var(--color-text-on-inverse-muted); }

.user-menu {
  position: absolute;
  bottom: calc(100% + 4px);
  left: var(--space-3);
  right: var(--space-3);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  overflow: hidden;
}
.user-menu__item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  background: transparent;
  border: none;
  padding: 10px 14px;
  font-size: var(--font-size-sm);
  text-align: left;
  cursor: pointer;
  transition: background var(--motion-base) var(--motion-ease);
}
.user-menu__item:hover { background: var(--color-surface-sunken); }
.user-menu__item--danger { color: var(--color-status-danger); }

.content {
  flex: 1;
  overflow: auto;
  padding: var(--space-7) var(--space-7);
}

.overlay {
  display: none;
}

@media (max-width: 767px) {
  .layout { display: block; }

  .mobile-bar {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    height: 56px;
    padding: 0 var(--space-3);
    background: var(--color-surface-inverse);
    color: var(--color-text-on-inverse);
    position: sticky;
    top: 0;
    z-index: 30;
    border-bottom: 1px solid var(--color-border-on-inverse);
  }
  .mobile-bar__btn {
    width: 40px;
    height: 40px;
    background: transparent;
    border: none;
    color: var(--color-text-on-inverse);
    border-radius: var(--radius-md);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background var(--motion-base) var(--motion-ease);
  }
  .mobile-bar__btn:hover { background: rgba(255, 255, 255, 0.06); }
  .mobile-bar__brand {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .mobile-bar__mark {
    width: 28px;
    height: 28px;
    border-radius: var(--radius-md);
    background: var(--color-brand-primary);
    color: #fff;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .mobile-bar__brand strong { font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); }

  .sidebar {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 50;
    transform: translateX(-100%);
    transition: transform var(--motion-slow) var(--motion-ease);
    box-shadow: var(--shadow-lg);
  }
  .sidebar--open { transform: translateX(0); }

  .sidebar__close {
    display: inline-flex;
  }

  .overlay {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(15, 18, 22, 0.55);
    backdrop-filter: blur(2px);
    z-index: 40;
    animation: overlay-fade var(--motion-base) var(--motion-ease);
  }
  @keyframes overlay-fade {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  .content {
    padding: var(--space-5) var(--space-4);
  }
}
</style>
