<script setup lang="ts">
import { computed } from 'vue'
import * as icons from 'lucide-vue-next'
import type { LucideIcon } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  name: string
  size?: number
  strokeWidth?: number
}>(), {
  size: 20,
  strokeWidth: 1.75,
})

function toPascal(name: string): string {
  return name
    .split('-')
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join('')
}

const component = computed<LucideIcon>(() => {
  const key = toPascal(props.name) as keyof typeof icons
  const found = icons[key] as LucideIcon | undefined
  if (!found) {
    console.warn(`[Icon] not found: ${props.name}`)
    return icons.HelpCircle as LucideIcon
  }
  return found
})
</script>

<template>
  <component
    :is="component"
    :size="size"
    :stroke-width="strokeWidth"
    aria-hidden="true"
    focusable="false"
  />
</template>
