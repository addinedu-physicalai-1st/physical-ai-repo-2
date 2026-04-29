<script setup lang="ts">
import { ref } from 'vue'
import { api, ApiError } from '@/api/client'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseCard from '@/components/common/BaseCard.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import BaseButton from '@/components/common/BaseButton.vue'
import Icon from '@/components/common/Icon.vue'

const current = ref('')
const next = ref('')
const confirm = ref('')
const status = ref<{ kind: 'ok' | 'err'; msg: string } | null>(null)
const saving = ref(false)

async function submit() {
  status.value = null
  if (next.value.length < 8) {
    status.value = { kind: 'err', msg: '새 비밀번호는 8자 이상이어야 합니다.' }
    return
  }
  if (next.value !== confirm.value) {
    status.value = { kind: 'err', msg: '새 비밀번호와 확인이 일치하지 않습니다.' }
    return
  }
  saving.value = true
  try {
    await api.patch('/api/users/me', {
      current_password: current.value,
      password: next.value,
    })
    status.value = { kind: 'ok', msg: '비밀번호가 변경되었습니다.' }
    current.value = next.value = confirm.value = ''
  } catch (e) {
    const msg = e instanceof ApiError && e.status === 400
      ? '현재 비밀번호가 올바르지 않습니다.'
      : '변경 중 오류가 발생했습니다.'
    status.value = { kind: 'err', msg }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section>
    <PageHeader title="설정" description="계정 정보를 관리합니다." />

    <BaseCard class="settings-card" :padded="true">
      <template #header>
        <div class="settings-card__head">
          <Icon name="key-round" :size="16" />
          <span>비밀번호 변경</span>
        </div>
      </template>

      <form class="form" @submit.prevent="submit">
        <BaseInput v-model="current" label="현재 비밀번호" type="password" required icon-start="lock" />
        <BaseInput v-model="next" label="새 비밀번호" type="password" required :minlength="8" icon-start="lock" />
        <BaseInput v-model="confirm" label="새 비밀번호 확인" type="password" required icon-start="lock" />

        <p v-if="status" :class="['form__msg', `form__msg--${status.kind}`]">
          <Icon :name="status.kind === 'ok' ? 'check-circle-2' : 'alert-circle'" :size="14" />
          <span>{{ status.msg }}</span>
        </p>

        <BaseButton type="submit" variant="primary" :loading="saving">변경</BaseButton>
      </form>
    </BaseCard>
  </section>
</template>

<style scoped>
.settings-card { max-width: 480px; }
.settings-card__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
.form { display: flex; flex-direction: column; gap: var(--space-4); align-items: stretch; }
.form__msg {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  margin: 0;
}
.form__msg--ok  { color: var(--color-status-success); }
.form__msg--err { color: var(--color-status-danger); }
</style>
