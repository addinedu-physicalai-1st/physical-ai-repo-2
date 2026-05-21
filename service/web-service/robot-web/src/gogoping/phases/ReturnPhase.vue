<script setup lang="ts">
/** "못찾겠다 꾀꼬리" 외치며 운동장2 로 복귀. */
defineProps<{ playArea: string }>();
</script>

<template>
  <section class="ret">
    <div class="shout">못 찾겠다, 꾀꼬리! 🐦</div>
    <div class="big-emoji" aria-hidden="true">🚶‍♂️</div>
    <h2 class="title">{{ playArea }} 로 돌아가는 중</h2>
    <p class="sub">다 모이면 우승자를 발표할게!</p>
  </section>
</template>

<style scoped>
.ret {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 16px;
  padding: 32px;
}
.shout {
  font-size: 28px;
  font-weight: 800;
  color: #92400e;
  background: rgba(254, 243, 199, 0.95);
  border: 3px solid #fbbf24;
  border-radius: 18px;
  padding: 12px 24px;
  box-shadow: 0 10px 24px rgba(251, 191, 36, 0.3);
  animation: shout-pulse 1.2s ease-in-out infinite;
}
@keyframes shout-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.04); }
}
.big-emoji {
  font-size: 84px;
  animation: walk 1.2s ease-in-out infinite;
}
@keyframes walk {
  0%, 100% { transform: translateX(-8px) rotate(-2deg); }
  50% { transform: translateX(8px) rotate(2deg); }
}
.title {
  margin: 0;
  font-size: 26px;
  font-weight: 800;
  color: #166534;
}
.sub { margin: 0; color: #4b5563; font-size: 15px; }
</style>
