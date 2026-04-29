<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '@/api/client'
import type { Report } from '@/types'
import BaseTextarea from '@/components/common/BaseTextarea.vue'
import BaseButton from '@/components/common/BaseButton.vue'
import Icon from '@/components/common/Icon.vue'

const props = defineProps<{ report: Report }>()
const emit = defineEmits<{ (e: 'saved', r: Report): void }>()

const content = ref(props.report.content)
const saving = ref(false)
const status = ref<{ kind: 'ok' | 'err'; msg: string } | null>(null)

watch(() => props.report.id, () => {
  content.value = props.report.content
  status.value = null
})

async function save() {
  saving.value = true
  status.value = null
  try {
    const updated = await api.patch<Report>(`/api/reports/${props.report.id}`, {
      content: content.value,
    })
    emit('saved', updated)
    status.value = { kind: 'ok', msg: '저장됨' }
    setTimeout(() => { status.value = null }, 3000)
  } catch {
    status.value = { kind: 'err', msg: '저장 실패' }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="editor">
    <BaseTextarea v-model="content" :rows="10" />
    <div class="editor__actions">
      <span v-if="status" class="editor__status" :class="`editor__status--${status.kind}`">
        <Icon :name="status.kind === 'ok' ? 'check-circle-2' : 'alert-circle'" :size="14" />
        {{ status.msg }}
      </span>
      <BaseButton variant="primary" size="sm" :loading="saving" icon-start="save" @click="save">
        저장
      </BaseButton>
    </div>
  </div>
</template>

<style scoped>
.editor { display: flex; flex-direction: column; gap: var(--space-3); }
.editor__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  align-items: center;
}
.editor__status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--font-size-xs);
}
.editor__status--ok  { color: var(--color-status-success); }
.editor__status--err { color: var(--color-status-danger); }
</style>
