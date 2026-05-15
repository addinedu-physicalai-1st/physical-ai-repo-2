<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'
import type {
  Child, RegisterChildPayload, RegisterParentPayload, RegisterParentResponse,
} from '@/types'
import RegisterWizard from '@/components/teacher/RegisterWizard.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseCard from '@/components/common/BaseCard.vue'
import BaseButton from '@/components/common/BaseButton.vue'
import Icon from '@/components/common/Icon.vue'

interface Submission {
  child: RegisterChildPayload
  parent: Omit<RegisterParentPayload, 'child_id'>
}

const submitting = ref(false)
const result = ref<{ child: Child; email: string; password: string } | null>(null)
const error = ref<string | null>(null)

async function onSubmit({ child: childPayload, parent: parentPayload }: Submission) {
  submitting.value = true
  error.value = null
  try {
    const child = await api.post<Child>('/api/children', childPayload)
    const parentResp = await api.post<RegisterParentResponse>('/api/parents', {
      ...parentPayload,
      child_id: child.id,
    })
    result.value = {
      child,
      email: parentResp.parent.email,
      password: parentResp.initial_password,
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    submitting.value = false
  }
}

function copyPassword() {
  if (result.value) navigator.clipboard.writeText(result.value.password)
}

function reset() {
  result.value = null
  error.value = null
}
</script>

<template>
  <section>
    <PageHeader title="어린이 등록" description="어린이 정보와 학부모 정보를 입력하면 학부모 계정이 자동 생성됩니다." />

    <div v-if="result">
      <BaseCard class="done" :padded="true">
        <template #header>
          <div class="done__head">
            <span class="done__check"><Icon name="check" :size="14" /></span>
            <span>등록 완료</span>
          </div>
        </template>

        <dl class="done__list">
          <dt>어린이</dt><dd>{{ result.child.name }}</dd>
          <dt>학부모 이메일</dt><dd>{{ result.email }}</dd>
          <dt>초기 비밀번호</dt>
          <dd>
            <code class="done__code">{{ result.password }}</code>
            <BaseButton variant="ghost" size="sm" icon-start="copy" @click="copyPassword">복사</BaseButton>
          </dd>
        </dl>

        <p class="done__warn">
          <Icon name="info" :size="14" />
          <span>얼굴 캡처는 어린이 관리 화면에서 진행할 수 있습니다.</span>
        </p>

        <template #footer>
          <div class="done__actions">
            <RouterLink to="/teacher/children" custom v-slot="{ navigate }">
              <BaseButton variant="ghost" icon-start="arrow-left" @click="navigate">어린이 관리로</BaseButton>
            </RouterLink>
            <BaseButton variant="primary" icon-start="plus" @click="reset">새 등록 시작</BaseButton>
          </div>
        </template>
      </BaseCard>
    </div>

    <RegisterWizard v-else :submitting="submitting" @submit="onSubmit" />

    <p v-if="error" class="error">
      <Icon name="alert-circle" :size="14" />
      <span>{{ error }}</span>
    </p>
  </section>
</template>

<style scoped>
.done { max-width: 640px; }
.done__head { display: flex; align-items: center; gap: var(--space-2); color: var(--color-status-success); font-weight: var(--font-weight-semibold); font-size: var(--font-size-sm); }
.done__check {
  width: 22px; height: 22px;
  background: var(--color-status-success);
  color: #fff;
  border-radius: var(--radius-full);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.done__list {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: var(--space-3);
  margin: 0;
}
.done__list dt { color: var(--color-text-muted); font-size: var(--font-size-sm); }
.done__list dd { margin: 0; font-weight: var(--font-weight-semibold); display: flex; align-items: center; gap: var(--space-3); }
.done__code {
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border-subtle);
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  font-family: ui-monospace, Menlo, monospace;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-regular);
  color: var(--color-brand-primary);
}

.done__warn {
  margin-top: var(--space-4);
  display: flex;
  gap: var(--space-2);
  align-items: flex-start;
  background: var(--color-status-warning-soft);
  color: var(--color-status-warning);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--font-size-xs);
  line-height: var(--line-height-relaxed);
}

.done__actions { display: flex; gap: var(--space-2); }

.error {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  color: var(--color-status-danger);
  font-size: var(--font-size-sm);
  margin-top: var(--space-4);
}
</style>
