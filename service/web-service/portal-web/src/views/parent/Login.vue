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
    if (auth.role !== 'parent') {
      await auth.logout()
      error.value = '학부모 계정이 아닙니다.'
      return
    }
    router.push('/parent/home')
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
      <h1 class="login__title">학부모 포털</h1>
      <p class="login__lead">자녀의 등하원, 점심 메뉴, 사진첩, 일과 보고서를 한 자리에서 봅니다.</p>
      <ul class="login__features">
        <li><Icon name="bus" :size="16" /><span>등하원 시간</span></li>
        <li><Icon name="utensils" :size="16" /><span>오늘 점심</span></li>
        <li><Icon name="images" :size="16" /><span>사진첩</span></li>
        <li><Icon name="file-text" :size="16" /><span>일과 보고서</span></li>
      </ul>
    </aside>

    <section class="login__panel">
      <form class="login__form" @submit.prevent="submit">
        <h2 class="login__form-title">로그인</h2>
        <p class="login__form-desc">교사가 발급한 학부모 계정으로 로그인합니다.</p>

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
    radial-gradient(900px 500px at 25% 20%, rgba(244, 194, 138, 0.55), transparent 60%),
    radial-gradient(700px 400px at 90% 90%, rgba(224, 120, 86, 0.20), transparent 60%),
    linear-gradient(155deg, #FAF1E5 0%, #F8E6E0 60%, #F2DAE8 100%);
  color: var(--color-text-primary);
  padding: var(--space-9) var(--space-7);
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.login__mark {
  width: 48px; height: 48px;
  border-radius: var(--radius-md);
  background: var(--color-brand-primary);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-5);
}
.login__title { font-size: var(--font-size-3xl); margin-bottom: var(--space-3); }
.login__lead { color: var(--color-text-secondary); max-width: 500px; line-height: var(--line-height-relaxed); }
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
  color: var(--color-text-secondary);
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
