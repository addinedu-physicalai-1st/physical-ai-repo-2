<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/client'
import Icon from '@/components/common/Icon.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import BaseButton from '@/components/common/BaseButton.vue'

const router = useRouter()
const auth = useAuthStore()

const email = ref('')
const password = ref('')
const error = ref<string | null>(null)
const loading = ref(false)

async function submit() {
  error.value = null
  loading.value = true
  try {
    await auth.login(email.value, password.value)
    if (auth.role !== 'teacher') {
      await auth.logout()
      error.value = '교사 계정이 아닙니다.'
      return
    }
    router.push('/teacher/dashboard')
  } catch (e) {
    error.value = e instanceof ApiError && e.status === 400
      ? '이메일 또는 비밀번호가 올바르지 않습니다.'
      : '로그인 중 오류가 발생했습니다.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login">
    <aside class="login__brand">
      <span class="login__mark"><Icon name="graduation-cap" :size="22" /></span>
      <h1 class="login__title">교사 포털</h1>
      <p class="login__lead">반 출결, 어린이 등록, 일과 보고서를 한곳에서 관리합니다.</p>
      <ul class="login__features">
        <li><Icon name="layout-dashboard" :size="16" /><span>실시간 출결 보드</span></li>
        <li><Icon name="user-plus-2" :size="16" /><span>어린이·학부모 등록</span></li>
        <li><Icon name="file-text" :size="16" /><span>일과 보고서 작성</span></li>
      </ul>
    </aside>

    <section class="login__panel">
      <form class="login__form" @submit.prevent="submit">
        <h2 class="login__form-title">로그인</h2>
        <p class="login__form-desc">발급받은 교사 계정으로 로그인합니다.</p>

        <BaseInput v-model="email" label="이메일" type="email" required autocomplete="username" icon-start="mail" />
        <BaseInput v-model="password" label="비밀번호" type="password" required autocomplete="current-password" icon-start="lock" />

        <p v-if="error" class="login__error">
          <Icon name="alert-circle" :size="14" />
          <span>{{ error }}</span>
        </p>

        <BaseButton type="submit" variant="primary" :loading="loading" block>로그인</BaseButton>
        <RouterLink to="/" class="login__back">
          <Icon name="arrow-left" :size="14" />
          <span>뒤로가기</span>
        </RouterLink>
      </form>
    </section>
  </main>
</template>

<style scoped>
.login {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 1fr 1fr;
}

.login__brand {
  background:
    radial-gradient(800px 500px at 30% 20%, rgba(244, 194, 138, 0.4), transparent 60%),
    linear-gradient(150deg, var(--color-surface-inverse), #2A3744);
  color: var(--color-text-on-inverse);
  padding: var(--space-9) var(--space-7);
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.login__mark {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  background: var(--color-brand-primary);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-5);
}
.login__title { font-size: var(--font-size-3xl); margin-bottom: var(--space-3); }
.login__lead { color: var(--color-text-on-inverse-muted); max-width: 500px; line-height: var(--line-height-relaxed); }
.login__features {
  margin-top: var(--space-7);
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.login__features li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-text-on-inverse-muted);
  font-size: var(--font-size-sm);
}

.login__panel {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface-base);
  padding: var(--space-7);
}
.login__form {
  width: 100%;
  max-width: 380px;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.login__form-title { font-size: var(--font-size-xl); }
.login__form-desc { color: var(--color-text-secondary); font-size: var(--font-size-sm); margin-bottom: var(--space-2); }

.login__error {
  display: flex; gap: var(--space-2); align-items: center;
  color: var(--color-status-danger);
  font-size: var(--font-size-sm);
  margin: 0;
}

.login__back {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
  text-decoration: none;
  text-align: center;
  justify-content: center;
}
.login__back:hover { color: var(--color-text-primary); }
</style>
