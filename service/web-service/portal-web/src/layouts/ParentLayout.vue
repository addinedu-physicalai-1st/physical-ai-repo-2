<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Icon from '@/components/common/Icon.vue'
import NavItem from '@/components/common/NavItem.vue'
import BaseAvatar from '@/components/common/BaseAvatar.vue'
import ChildSelector from '@/components/parent/ChildSelector.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const items = [
  { to: '/parent/home',       icon: 'home',          label: '홈' },
  { to: '/parent/attendance', icon: 'bus',           label: '등하원' },
  { to: '/parent/menu',       icon: 'utensils',      label: '메뉴' },
  { to: '/parent/photos',     icon: 'images',        label: '사진첩' },
  { to: '/parent/report',     icon: 'file-text',     label: '보고서' },
  { to: '/parent/schedule',   icon: 'calendar',      label: '일과표' },
]

const drawerOpen = ref(false)
const userMenuOpen = ref(false)
const userMenuRef = ref<HTMLElement | null>(null)

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    drawerOpen.value = false
    userMenuOpen.value = false
  }
}
function onDocumentClick(e: MouseEvent) {
  if (!userMenuOpen.value) return
  const root = userMenuRef.value
  if (root && !root.contains(e.target as Node)) {
    userMenuOpen.value = false
  }
}
onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  document.addEventListener('click', onDocumentClick)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('click', onDocumentClick)
  document.body.style.overflow = ''
})

watch(drawerOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})
watch(() => route.fullPath, () => {
  drawerOpen.value = false
  userMenuOpen.value = false
})

function goSettings() {
  userMenuOpen.value = false
  router.push('/parent/settings')
}

async function logout() {
  drawerOpen.value = false
  userMenuOpen.value = false
  await auth.logout()
  router.push('/')
}
</script>

<template>
  <div class="layout">
    <header class="topbar">
      <div class="topbar__inner">
        <RouterLink to="/parent/home" class="brand">
          <span class="brand__mark"><Icon name="graduation-cap" :size="18" /></span>
          <strong>pingdergarten</strong>
        </RouterLink>

        <nav class="topbar__nav">
          <NavItem
            v-for="i in items"
            :key="i.to"
            :to="i.to"
            :icon="i.icon"
            :label="i.label"
            variant="topbar"
          />
        </nav>

        <div ref="userMenuRef" class="topbar__user">
          <button
            class="topbar__user-trigger"
            type="button"
            :aria-expanded="userMenuOpen"
            aria-haspopup="menu"
            @click="userMenuOpen = !userMenuOpen"
          >
            <BaseAvatar :name="auth.user?.name ?? '학부모'" :size="32" />
            <span class="topbar__user-name">{{ auth.user?.name }}</span>
            <Icon name="chevron-down" :size="16" class="topbar__user-caret" />
          </button>

          <div v-if="userMenuOpen" class="user-menu" role="menu">
            <button class="user-menu__item" type="button" role="menuitem" @click="goSettings">
              <Icon name="settings-2" :size="16" />
              <span>설정</span>
            </button>
            <button
              class="user-menu__item user-menu__item--danger"
              type="button"
              role="menuitem"
              @click="logout"
            >
              <Icon name="log-out" :size="16" />
              <span>로그아웃</span>
            </button>
          </div>
        </div>

        <button
          class="topbar__menu-btn"
          type="button"
          :aria-expanded="drawerOpen"
          aria-label="메뉴 열기"
          @click="drawerOpen = true"
        >
          <Icon name="menu" :size="22" />
        </button>
      </div>
    </header>

    <div class="subbar">
      <div class="subbar__inner">
        <ChildSelector />
      </div>
    </div>

    <main class="content">
      <RouterView />
    </main>

    <div
      v-if="drawerOpen"
      class="overlay"
      aria-hidden="true"
      @click="drawerOpen = false"
    />

    <aside class="drawer" :class="{ 'drawer--open': drawerOpen }" role="navigation">
      <div class="drawer__head">
        <BaseAvatar :name="auth.user?.name ?? '학부모'" :size="36" />
        <div class="drawer__head-text">
          <strong>{{ auth.user?.name ?? '학부모' }}</strong>
          <span>학부모</span>
        </div>
        <button
          class="drawer__close"
          type="button"
          aria-label="메뉴 닫기"
          @click="drawerOpen = false"
        >
          <Icon name="x" :size="20" />
        </button>
      </div>

      <nav class="drawer__nav">
        <NavItem
          v-for="i in items"
          :key="i.to"
          :to="i.to"
          :icon="i.icon"
          :label="i.label"
          variant="sidebar"
        />
      </nav>

      <div class="drawer__footer">
        <RouterLink to="/parent/settings" class="drawer__action">
          <Icon name="settings-2" :size="18" />
          <span>설정</span>
        </RouterLink>
        <button class="drawer__action drawer__action--danger" type="button" @click="logout">
          <Icon name="log-out" :size="18" />
          <span>로그아웃</span>
        </button>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.layout { min-height: 100vh; background: var(--color-surface-base); }

.topbar {
  background: var(--color-surface-raised);
  border-bottom: 1px solid var(--color-border-subtle);
  position: sticky;
  top: 0;
  z-index: 10;
}
.topbar__inner {
  display: flex;
  align-items: center;
  gap: var(--space-7);
  height: 64px;
  padding: 0 var(--space-6);
  max-width: 1280px;
  margin: 0 auto;
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  text-decoration: none;
  color: var(--color-text-primary);
}
.brand__mark {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: var(--color-brand-primary);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.brand strong { font-weight: var(--font-weight-semibold); font-size: var(--font-size-base); }

.topbar__nav { display: flex; gap: var(--space-6); flex: 1; align-items: center; }

.topbar__user {
  position: relative;
  display: flex;
  align-items: center;
}
.topbar__user-trigger {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 4px 10px 4px 4px;
  background: transparent;
  border: none;
  border-radius: 999px;
  cursor: pointer;
  color: var(--color-text-primary);
  transition: background var(--motion-base) var(--motion-ease);
}
.topbar__user-trigger:hover { background: var(--color-surface-sunken); }
.topbar__user-trigger[aria-expanded="true"] { background: var(--color-surface-sunken); }
.topbar__user-name {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}
.topbar__user-caret {
  color: var(--color-text-secondary);
  transition: transform var(--motion-base) var(--motion-ease);
}
.topbar__user-trigger[aria-expanded="true"] .topbar__user-caret {
  transform: rotate(180deg);
}

.user-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 160px;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  z-index: 30;
}
.user-menu__item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 8px 12px;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  text-align: left;
  cursor: pointer;
  transition: background var(--motion-base) var(--motion-ease);
}
.user-menu__item:hover { background: var(--color-surface-sunken); }
.user-menu__item--danger { color: var(--color-status-danger); }

.topbar__menu-btn {
  display: none;
  width: 40px;
  height: 40px;
  background: transparent;
  border: none;
  color: var(--color-text-primary);
  border-radius: var(--radius-md);
  align-items: center;
  justify-content: center;
  cursor: pointer;
  margin-left: auto;
  transition: background var(--motion-base) var(--motion-ease);
}
.topbar__menu-btn:hover { background: var(--color-surface-sunken); }

.subbar {
  background: var(--color-surface-raised);
  border-bottom: 1px solid var(--color-border-subtle);
}
.subbar__inner {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 var(--space-6);
  min-height: 56px;
  display: flex;
  align-items: center;
}

.content {
  max-width: 1080px;
  margin: 0 auto;
  padding: var(--space-6);
}

.overlay { display: none; }

.drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 280px;
  background: var(--color-surface-inverse);
  color: var(--color-text-on-inverse);
  display: flex;
  flex-direction: column;
  transform: translateX(100%);
  transition: transform var(--motion-slow) var(--motion-ease);
  z-index: 50;
  box-shadow: var(--shadow-lg);
}
.drawer--open { transform: translateX(0); }

.drawer__head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-5);
  border-bottom: 1px solid var(--color-border-on-inverse);
}
.drawer__head-text { display: flex; flex-direction: column; flex: 1; }
.drawer__head-text strong { font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); }
.drawer__head-text span { font-size: var(--font-size-xs); color: var(--color-text-on-inverse-muted); }
.drawer__close {
  background: transparent;
  border: none;
  color: var(--color-text-on-inverse-muted);
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background var(--motion-base) var(--motion-ease);
}
.drawer__close:hover { background: rgba(255, 255, 255, 0.06); color: var(--color-text-on-inverse); }

.drawer__nav {
  display: flex;
  flex-direction: column;
  padding: var(--space-3) 0;
  flex: 1;
  gap: 2px;
}

.drawer__footer {
  border-top: 1px solid var(--color-border-on-inverse);
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.drawer__action {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px 14px;
  background: transparent;
  border: none;
  color: var(--color-text-on-inverse-muted);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  text-decoration: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  text-align: left;
  transition: background var(--motion-base) var(--motion-ease), color var(--motion-base) var(--motion-ease);
}
.drawer__action:hover {
  background: rgba(255, 255, 255, 0.04);
  color: var(--color-text-on-inverse);
}
.drawer__action--danger { color: var(--color-status-danger); }
.drawer__action--danger:hover { color: var(--color-status-danger); }

@media (max-width: 767px) {
  .topbar__inner {
    gap: var(--space-3);
    padding: 0 var(--space-3);
  }
  .topbar__nav { display: none; }
  .topbar__user { display: none; }
  .topbar__menu-btn { display: inline-flex; }

  .subbar__inner {
    padding: 0 var(--space-3);
  }

  .content {
    padding: var(--space-4) var(--space-3);
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
}

@media (min-width: 768px) {
  .drawer { display: none; }
}
</style>
