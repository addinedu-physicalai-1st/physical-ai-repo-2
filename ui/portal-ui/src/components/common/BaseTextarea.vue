<script setup lang="ts">
withDefaults(defineProps<{
  modelValue?: string
  label?: string
  hint?: string
  error?: string | null
  placeholder?: string
  required?: boolean
  disabled?: boolean
  rows?: number
}>(), { rows: 4 })

defineEmits<{ (e: 'update:modelValue', value: string): void }>()
</script>

<template>
  <label class="field" :class="{ 'field--error': !!error, 'field--disabled': disabled }">
    <span v-if="label" class="field__label">
      {{ label }}
      <span v-if="required" class="field__required">*</span>
    </span>
    <textarea
      :value="modelValue"
      :placeholder="placeholder"
      :required="required"
      :disabled="disabled"
      :rows="rows"
      class="field__input"
      @input="$emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
    />
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
.field__input {
  width: 100%;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  resize: vertical;
  font-family: inherit;
  line-height: var(--line-height-base);
  transition: border-color var(--motion-base) var(--motion-ease);
}
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
.field__msg { font-size: var(--font-size-xs); color: var(--color-text-muted); }
.field__msg--error { color: var(--color-status-danger); }
</style>
