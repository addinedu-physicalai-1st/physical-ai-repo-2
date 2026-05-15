<template>
  <div class="loader" aria-label="처리 중">
    <span class="dot"></span>
    <span class="dot"></span>
    <span class="dot"></span>
  </div>
</template>

<style scoped>
.loader {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  height: 110px;
  width: 110px;
}
.dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--primary);
  animation: bounce 1.2s ease-in-out infinite;
  box-shadow: 0 0 12px color-mix(in srgb, var(--primary) 45%, transparent);
}
.dot:nth-child(2) { animation-delay: 0.18s; }
.dot:nth-child(3) { animation-delay: 0.36s; }
@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.45); opacity: 0.4; }
  40%            { transform: scale(1);    opacity: 1; }
}
</style>
