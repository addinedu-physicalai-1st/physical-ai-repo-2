<script setup lang="ts">
defineProps<{ text: string }>();
</script>

<template>
  <Transition name="fade">
    <div v-if="text" class="caption">{{ text }}</div>
  </Transition>
</template>

<style scoped>
.caption {
  max-width: min(640px, calc(100vw - 200px));
  padding: 10px 22px;
  background: rgba(255, 255, 255, 0.92);
  border-radius: 18px;
  font-size: 22px;
  font-weight: 600;
  color: #444;
  text-align: center;
  line-height: 1.35;
  box-shadow: 0 6px 18px color-mix(in srgb, var(--primary) 12%, transparent);
  white-space: pre-wrap;
  word-break: keep-all;
}
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
