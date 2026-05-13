<script setup lang="ts">
import { ref, computed } from 'vue'
import type { RegisterChildPayload, RegisterParentPayload } from '@/types'
import Icon from '@/components/common/Icon.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import BaseSelect from '@/components/common/BaseSelect.vue'
import BaseTextarea from '@/components/common/BaseTextarea.vue'
import BaseButton from '@/components/common/BaseButton.vue'

const emit = defineEmits<{
  (e: 'submit', payload: {
    child: RegisterChildPayload
    parent: Omit<RegisterParentPayload, 'child_id'>
  }): void
}>()

defineProps<{ submitting?: boolean }>()

const step = ref<1 | 2>(1)

const CLASS_OPTIONS = ['햇살반', '꽃잎반', '햇님반']

const childName = ref('')
const childGivenName = ref('')
const childBirth = ref('')
const childClass = ref('')
const childNotes = ref('')

const parentName = ref('')
const parentPhone = ref('')
const parentEmail = ref('')

const error = ref<string | null>(null)

const step1Valid = computed(() =>
  childName.value.trim() && childBirth.value && childClass.value.trim()
)

const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function next() {
  error.value = null
  if (step.value === 1) {
    if (!step1Valid.value) {
      error.value = '모든 어린이 정보를 입력해주세요.'
      return
    }
    step.value = 2
  }
}

function submit() {
  error.value = null
  if (!parentName.value.trim() || !parentPhone.value.trim()) {
    error.value = '모든 학부모 정보를 입력해주세요.'
    return
  }
  if (!emailRegex.test(parentEmail.value)) {
    error.value = '이메일 형식이 올바르지 않습니다.'
    return
  }
  emit('submit', {
    child: {
      name: childName.value.trim(),
      birth_date: childBirth.value,
      class_name: childClass.value.trim(),
      notes: childNotes.value.trim() || null,
      given_name: childGivenName.value.trim() || null,
    },
    parent: {
      name: parentName.value.trim(),
      email: parentEmail.value.trim(),
      phone: parentPhone.value.trim(),
    },
  })
}

function back() {
  error.value = null
  if (step.value === 2) step.value = 1
}
</script>

<template>
  <div class="wizard">
    <ol class="stepper">
      <li class="stepper__item" :class="{ 'is-active': step === 1, 'is-done': step > 1 }">
        <span class="stepper__bullet">
          <Icon v-if="step > 1" name="check" :size="14" />
          <span v-else>1</span>
        </span>
        <span class="stepper__label">어린이 정보</span>
      </li>
      <li class="stepper__connector" :class="{ 'is-done': step > 1 }" />
      <li class="stepper__item" :class="{ 'is-active': step === 2 }">
        <span class="stepper__bullet"><span>2</span></span>
        <span class="stepper__label">학부모 정보</span>
      </li>
    </ol>

    <div v-if="step === 1" class="form" data-test="step1">
      <BaseInput v-model="childName" label="이름 (등록명)" required />
      <BaseInput
        v-model="childGivenName"
        label="보고서 호칭 (선택)"
        placeholder="비우면 이름에서 성 한 글자만 뗀 호칭으로 추정"
      />
      <BaseInput v-model="childBirth" label="생년월일" type="date" required />
      <BaseSelect
        v-model="childClass"
        label="반"
        required
        placeholder="반 선택"
        :options="CLASS_OPTIONS.map(c => ({ value: c, label: c }))"
      />
      <BaseTextarea
        v-model="childNotes"
        label="특이사항"
        :rows="3"
        placeholder="알레르기, 건강 상태, 성격 등 (선택)"
      />
    </div>

    <div v-else class="form" data-test="step2">
      <BaseInput v-model="parentName" label="학부모 이름" required />
      <BaseInput v-model="parentPhone" label="연락처" required />
      <BaseInput v-model="parentEmail" label="이메일 (로그인 ID)" type="email" required />
      <p class="hint">
        <Icon name="info" :size="14" />
        <span>초기 비밀번호는 자동 발급되어 다음 화면에 표시됩니다. 얼굴 캡처는 등록 후 어린이 관리 화면에서 진행할 수 있습니다.</span>
      </p>
    </div>

    <p v-if="error" class="error">
      <Icon name="alert-circle" :size="14" />
      <span>{{ error }}</span>
    </p>

    <div class="actions">
      <BaseButton v-if="step > 1" variant="ghost" :disabled="submitting" icon-start="arrow-left" @click="back">
        이전
      </BaseButton>
      <BaseButton v-if="step === 1" variant="primary" icon-end="arrow-right" @click="next">
        다음
      </BaseButton>
      <BaseButton v-else variant="primary" :loading="submitting" icon-end="check" @click="submit">
        등록하기
      </BaseButton>
    </div>
  </div>
</template>

<style scoped>
.wizard {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xs);
  padding: var(--space-7);
  max-width: 640px;
}

.stepper {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  list-style: none;
  margin: 0 0 var(--space-7);
  padding: 0;
}
.stepper__item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.stepper__bullet {
  width: 24px;
  height: 24px;
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border-subtle);
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.stepper__item.is-active .stepper__bullet {
  background: var(--color-brand-primary);
  border-color: var(--color-brand-primary);
  color: #fff;
}
.stepper__item.is-active { color: var(--color-brand-primary); font-weight: var(--font-weight-semibold); }
.stepper__item.is-done .stepper__bullet {
  background: var(--color-status-success);
  border-color: var(--color-status-success);
  color: #fff;
}
.stepper__item.is-done { color: var(--color-status-success); }
.stepper__connector {
  flex: 1;
  height: 2px;
  background: var(--color-border-subtle);
  border-radius: 2px;
  list-style: none;
}
.stepper__connector.is-done { background: var(--color-status-success); }

.form { display: flex; flex-direction: column; gap: var(--space-4); }

.hint {
  display: flex;
  gap: var(--space-2);
  align-items: flex-start;
  background: var(--color-brand-secondary-soft);
  color: var(--color-brand-secondary);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--font-size-xs);
  line-height: var(--line-height-relaxed);
  margin: 0;
}

.error {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  color: var(--color-status-danger);
  font-size: var(--font-size-sm);
  margin: var(--space-4) 0 0;
}

.actions { display: flex; justify-content: flex-end; gap: var(--space-2); margin-top: var(--space-6); }
</style>
