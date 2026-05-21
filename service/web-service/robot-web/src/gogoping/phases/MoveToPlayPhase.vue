<script setup lang="ts">
/** 운동장2 로 이동 중 화면. mock 타이머가 끝나면 자동 다음 페이즈. */
defineProps<{ playArea: string }>();
</script>

<template>
  <section class="move">
    <div class="big-emoji" aria-hidden="true">🏃‍♂️💨</div>
    <h2 class="title">{{ playArea }} 로 가는 중!</h2>
    <p class="sub">기다려줘, 금방 도착할게.</p>
    <div class="track">
      <div class="dot" />
      <div class="line" />
      <div class="goal">📍 {{ playArea }}</div>
    </div>
  </section>
</template>

<style scoped>
.move {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 18px;
  padding: 24px 32px;
}
.big-emoji {
  font-size: 96px;
  animation: bounce 1.4s ease-in-out infinite;
}
@keyframes bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-12px); }
}
.title {
  font-size: 30px;
  font-weight: 800;
  color: #166534;
  margin: 0;
}
.sub { color: #4b5563; font-size: 16px; margin: 0; }
.track {
  margin-top: 28px;
  width: min(90%, 520px);
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  color: #166534;
  font-weight: 700;
}
.dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #16a34a, #15803d);
  box-shadow: 0 0 0 6px rgba(22, 163, 74, 0.2);
  animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { transform: scale(1); box-shadow: 0 0 0 6px rgba(22, 163, 74, 0.2); }
  50% { transform: scale(1.15); box-shadow: 0 0 0 10px rgba(22, 163, 74, 0.1); }
}
.line {
  height: 6px;
  border-radius: 6px;
  background:
    linear-gradient(90deg, #16a34a 0%, transparent 50%),
    repeating-linear-gradient(90deg, rgba(22, 163, 74, 0.4) 0 12px, transparent 12px 24px);
  background-size: 200% 100%, auto;
  animation: scroll 1.4s linear infinite;
}
@keyframes scroll {
  0% { background-position: 0% 0, 0 0; }
  100% { background-position: 100% 0, 24px 0; }
}
.goal {
  padding: 8px 14px;
  border-radius: 999px;
  background: rgba(22, 163, 74, 0.1);
  border: 2px dashed #16a34a;
}
</style>
