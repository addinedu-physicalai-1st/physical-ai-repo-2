<script setup lang="ts">
import Icon from './Icon.vue'

withDefaults(defineProps<{
  modelValue?: string | number
  type?: string
  label?: string
  hint?: string
  error?: string | null
  placeholder?: string
  required?: boolean
  disabled?: boolean
  autocomplete?: string
  iconStart?: string
  minlength?: number
  maxlength?: number
}>(), { type: 'text' })

defineEmits<{ (e: 'update:modelValue', value: string): void }>()
</script>

<template>
  <label class="field" :class="{ 'field--error': !!error, 'field--disabled': disabled }">
    <span v-if="label" class="field__label">
      {{ label }}
      <span v-if="required" class="field__required">*</span>
    </span>
    <span class="field__control">
      <Icon v-if="iconStart" :name="iconStart" :size="16" class="field__icon" />
      <input
        :type="type"
        :value="modelValue"
        :placeholder="placeholder"
        :required="required"
        :disabled="disabled"
        :autocomplete="autocomplete"
        :minlength="minlength"
        :maxlength="maxlength"
        :class="['field__input', { 'field__input--icon': !!iconStart }]"
        @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      />
    </span>
    <span v-if="error" class="field__msg field__msg--error">{{ error }}</span>
    <span v-else-if="hint" class="field__msg">{{ hint }}</span>
  </label>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: var(--space-1); }
.field__label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}
.field__required { color: var(--color-status-danger); margin-left: 2px; }

.field__control { position: relative; display: flex; }
.field__icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
  pointer-events: none;
}
.field__input {
  flex: 1;
  width: 100%;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  padding: 9px 12px;
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  transition: border-color var(--motion-base) var(--motion-ease),
              background var(--motion-base) var(--motion-ease);
}
.field__input--icon { padding-left: 36px; }
.field__input::placeholder { color: var(--color-text-muted); }
.field__input:hover { border-color: var(--color-text-muted); }
.field__input:focus {
  outline: none;
  border-color: var(--color-brand-primary);
  box-shadow: var(--focus-ring);
}
.field__input:disabled {
  background: var(--color-surface-sunken);
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.field--error .field__input { border-color: var(--color-status-danger); }
.field--error .field__input:focus { box-shadow: 0 0 0 3px rgba(217, 83, 79, 0.25); }

.field__msg { font-size: var(--font-size-xs); color: var(--color-text-muted); }
.field__msg--error { color: var(--color-status-danger); }
</style>
