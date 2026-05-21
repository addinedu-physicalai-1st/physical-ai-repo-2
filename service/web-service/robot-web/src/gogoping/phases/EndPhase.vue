<script setup lang="ts">
/** 게임 종료 — 우승자(아직 안 잡힌 등록 참가자) 발표. */
import { computed } from 'vue';
import type { Participant } from '../useHideAndSeekState';

const props = defineProps<{
  winners: Participant[];
  caught: Participant[];
}>();

const emit = defineEmits<{ restart: []; close: [] }>();

const noWinners = computed(() => props.winners.length === 0);
</script>

<template>
  <section class="end">
    <div class="confetti" aria-hidden="true">🎉</div>
    <h2 class="title">
      <template v-if="noWinners">아쉽다, 다 잡혔어!</template>
      <template v-else>오늘의 숨바꼭질 챔피언!</template>
    </h2>

    <ul v-if="!noWinners" class="winners">
      <li v-for="(w, i) in winners" :key="w.id" class="winner-card" :class="`rank-${i + 1}`">
        <div class="medal">{{ i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : '🏅' }}</div>
        <div class="w-name">{{ w.name }}</div>
        <div class="w-sub">끝까지 숨었어요</div>
      </li>
    </ul>

    <section v-if="caught.length > 0" class="caught-list">
      <div class="ct-title">잡힌 친구들</div>
      <ul>
        <li v-for="p in caught" :key="p.id" class="caught-chip">
          {{ p.name }}
          <span v-if="p.caughtAt" class="where">@ {{ p.caughtAt }}</span>
        </li>
      </ul>
    </section>

    <footer class="actions">
      <button type="button" class="btn ghost" @click="emit('restart')">다시 하기</button>
      <button type="button" class="btn primary" @click="emit('close')">대기로</button>
    </footer>
  </section>
</template>

<style scoped>
.end {
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  padding: 24px 32px;
  gap: 18px;
}
.confetti { font-size: 56px; animation: spin 4s linear infinite; }
@keyframes spin { from { transform: rotate(-8deg); } to { transform: rotate(8deg); } }
.title {
  margin: 0;
  font-size: 30px;
  font-weight: 800;
  color: #166534;
  text-align: center;
}
.winners {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 14px;
  width: 100%;
  max-width: 720px;
}
.winner-card {
  background: linear-gradient(135deg, rgba(254, 249, 195, 0.95) 0%, rgba(253, 224, 71, 0.85) 100%);
  border: 3px solid #fbbf24;
  border-radius: 18px;
  padding: 16px 12px;
  text-align: center;
  box-shadow: 0 10px 24px rgba(251, 191, 36, 0.3);
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: center;
}
.winner-card.rank-1 {
  background: linear-gradient(135deg, #fef3c7 0%, #facc15 100%);
  transform: scale(1.06);
}
.medal { font-size: 44px; }
.w-name { font-size: 20px; font-weight: 800; color: #78350f; }
.w-sub { font-size: 12px; color: #78350f; opacity: 0.75; }

.caught-list {
  width: 100%;
  max-width: 720px;
  border-top: 1px dashed rgba(0, 0, 0, 0.1);
  padding-top: 12px;
}
.ct-title { font-size: 13px; color: #6b7280; margin-bottom: 6px; }
.caught-list ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.caught-chip {
  background: rgba(156, 163, 175, 0.2);
  color: #6b7280;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
}
.caught-chip .where {
  margin-left: 6px;
  font-size: 11px;
  font-weight: 500;
}

.actions {
  margin-top: auto;
  display: flex;
  gap: 12px;
}
.btn {
  padding: 12px 24px;
  border-radius: 999px;
  border: none;
  font-size: 15px;
  font-weight: 800;
  cursor: pointer;
  transition: transform 0.12s ease;
}
.btn:hover { transform: translateY(-1px); }
.btn.primary {
  background: linear-gradient(135deg, #16a34a 0%, #15803d 100%);
  color: white;
  box-shadow: 0 6px 18px rgba(22, 163, 74, 0.3);
}
.btn.ghost {
  background: rgba(0, 0, 0, 0.06);
  color: #166534;
}
</style>
