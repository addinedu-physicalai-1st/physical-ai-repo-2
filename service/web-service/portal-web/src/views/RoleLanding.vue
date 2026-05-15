<script setup lang="ts">
import { useRouter } from 'vue-router'
import Icon from '@/components/common/Icon.vue'

const router = useRouter()

function go(role: 'teacher' | 'parent') {
  router.push(`/${role}/login`)
}
</script>

<template>
  <main class="landing">
    <div class="landing__inner">
      <header class="hero">
        <span class="hero__mark"><Icon name="graduation-cap" :size="22" /></span>
        <strong class="hero__brand">pingdergarten</strong>
        <p class="hero__slogan">사랑의 에듀핑 — 유치원 교육보조 로봇 포털</p>
      </header>

      <div class="roles">
        <button class="role" @click="go('teacher')">
          <span class="role__icon role__icon--brand"><Icon name="user-round" :size="32" /></span>
          <span class="role__title">교사</span>
          <span class="role__desc">반의 출결 현황과 어린이 정보를 한눈에 관리하고, 일과 보고서를 작성합니다.</span>
          <span class="role__chips">
            <span class="chip">출결 보드</span>
            <span class="chip">어린이 등록</span>
            <span class="chip">일과 보고서</span>
          </span>
          <span class="role__cta">
            교사로 시작 <Icon name="arrow-right" :size="16" />
          </span>
        </button>

        <button class="role role--secondary" @click="go('parent')">
          <span class="role__icon role__icon--secondary"><Icon name="users-round" :size="32" /></span>
          <span class="role__title">학부모</span>
          <span class="role__desc">자녀의 등하원 시간, 점심 메뉴, 사진첩, 일과 보고서를 매일 확인합니다.</span>
          <span class="role__chips">
            <span class="chip">등하원 알림</span>
            <span class="chip">사진첩</span>
            <span class="chip">일과 보고서</span>
          </span>
          <span class="role__cta">
            학부모로 시작 <Icon name="arrow-right" :size="16" />
          </span>
        </button>
      </div>

      <footer class="landing__footer">Addinedu · 사랑의 에듀핑</footer>
    </div>
  </main>
</template>

<style scoped>
.landing {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-7);
  background:
    radial-gradient(1200px 600px at 20% 0%, rgba(244, 194, 138, 0.35), transparent 60%),
    radial-gradient(900px 500px at 95% 100%, rgba(224, 120, 86, 0.18), transparent 60%),
    linear-gradient(135deg, #FAF1E5 0%, #F8E6E0 60%, #F2DAE8 100%);
}
.landing__inner {
  width: 100%;
  max-width: 1024px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-9);
}

.hero { display: flex; flex-direction: column; align-items: center; gap: var(--space-3); text-align: center; }
.hero__mark {
  width: 44px; height: 44px;
  border-radius: var(--radius-md);
  background: var(--color-brand-primary);
  color: #fff;
  display: inline-flex; align-items: center; justify-content: center;
  box-shadow: var(--shadow-sm);
}
.hero__brand { font-size: var(--font-size-2xl); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.hero__slogan { color: var(--color-text-secondary); font-size: var(--font-size-base); }

.roles {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-6);
  width: 100%;
}

.role {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-7);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-xl);
  text-align: left;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: transform var(--motion-base) var(--motion-ease),
              box-shadow var(--motion-base) var(--motion-ease),
              border-color var(--motion-base) var(--motion-ease);
}
.role:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
  border-color: var(--color-border-strong);
}

.role__icon {
  width: 56px; height: 56px;
  border-radius: var(--radius-lg);
  display: inline-flex; align-items: center; justify-content: center;
  margin-bottom: var(--space-2);
}
.role__icon--brand { background: var(--color-brand-primary-soft); color: var(--color-brand-primary); }
.role__icon--secondary { background: var(--color-brand-secondary-soft); color: var(--color-brand-secondary); }

.role__title { font-size: var(--font-size-xl); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.role__desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  line-height: var(--line-height-relaxed);
}

.role__chips { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-2); }
.chip {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  padding: 4px 10px;
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
  color: var(--color-text-secondary);
}

.role__cta {
  margin-top: auto;
  padding-top: var(--space-3);
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-brand-primary);
}

.role--secondary .role__cta { color: var(--color-brand-secondary); }

.landing__footer {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}
</style>
