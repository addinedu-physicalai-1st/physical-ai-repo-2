<script setup lang="ts">
import Icon from './Icon.vue'

interface Option { value: string | number; label: string; disabled?: boolean }

withDefaults(defineProps<{
  modelValue?: string | number
  options: Option[]
  label?: string
  hint?: string
  error?: string | null
  required?: boolean
  disabled?: boolean
  placeholder?: string
}>(), {})

defineEmits<{ (e: 'update:modelValue', value: string): void }>()
</script>

<template>
  <label class="field" :class="{ 'field--error': !!error, 'field--disabled': disabled }">
    <span v-if="label" class="field__label">
      {{ label }}
      <span v-if="required" class="field__required">*</span>
    </span>
    <span class="field__control">
      <select
        :value="modelValue"
        :required="required"
        :disabled="disabled"
        class="field__input"
        @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
      >
        <option v-if="placeholder" value="" disabled>{{ placeholder }}</option>
        <option
          v-for="o in options"
          :key="o.value"
          :value="o.value"
          :disabled="o.disabled"
        >{{ o.label }}</option>
      </select>
      <Icon name="chevron-down" :size="16" class="field__chevron" />
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
.field__chevron {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
  pointer-events: none;
}
.field__input {
  appearance: none;
  width: 100%;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  padding: 9px 36px 9px 12px;
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  transition: border-color var(--motion-base) var(--motion-ease);
}
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
.field__msg { font-size: var(--font-size-xs); color: var(--color-text-muted); }
.field__msg--error { color: var(--color-status-danger); }
</style>
