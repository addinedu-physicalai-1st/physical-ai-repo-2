<script setup lang="ts">
/**
 * 숨바꼭질 모집 단계.
 * 무궁화 entry 단계의 참가자 strip 패턴 재활용 — 전체 명단을 카드로 띄우고
 * 등록된 친구는 핑크 체크, 미등록은 회색 대기. 카드 탭으로 수동 토글도 가능.
 */
import { computed } from 'vue';
import type { Participant } from '../useHideAndSeekState';

const props = defineProps<{
  participants: Participant[];
  registeredCount: number;
}>();

const emit = defineEmits<{
  toggle: [id: number];
  start: [];
}>();

const canStart = computed(() => props.registeredCount > 0);
</script>

<template>
  <section class="recruit">
    <header class="recruit-head">
      <h2 class="title">숨바꼭질 모집 중</h2>
      <p class="sub">카메라 앞으로 친구들이 모이면 자동으로 등록돼요.</p>
    </header>

    <ul class="roster">
      <li
        v-for="p in participants"
        :key="p.id"
        class="card"
        :class="{ registered: p.registered }"
        :title="p.registered ? '참가 — 탭하면 취소' : '미참가 — 탭하면 참가'"
        @click="emit('toggle', p.id)"
      >
        <div class="avatar">
          <span class="initial">{{ p.name.charAt(0) }}</span>
          <span v-if="p.registered" class="check">✓</span>
        </div>
        <div class="name">{{ p.name }}</div>
        <div class="status">{{ p.registered ? '참가' : '대기' }}</div>
      </li>
    </ul>

    <footer class="actions">
      <div class="count">
        등록 <strong>{{ registeredCount }}</strong> / {{ participants.length }}
      </div>
      <button
        type="button"
        class="start-btn"
        :disabled="!canStart"
        @click="emit('start')"
      >
        모집 마치고 출발
      </button>
    </footer>
  </section>
</template>

<style scoped>
.recruit {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 28px 36px 24px;
  gap: 24px;
}
.recruit-head .title {
  margin: 0;
  font-size: 32px;
  font-weight: 800;
  color: #166534;
  letter-spacing: -0.5px;
}
.recruit-head .sub {
  margin: 6px 0 0;
  color: #4b5563;
  font-size: 15px;
}

.roster {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
  gap: 14px;
  flex: 1;
  align-content: start;
  overflow-y: auto;
}
.card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 18px 12px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.85);
  border: 2px solid rgba(0, 0, 0, 0.08);
  cursor: pointer;
  transition: transform 0.12s ease, border-color 0.18s ease, box-shadow 0.18s ease;
  user-select: none;
}
.card:hover { transform: translateY(-2px); }
.card.registered {
  border-color: #16a34a;
  box-shadow: 0 6px 18px rgba(22, 163, 74, 0.18);
  background: rgba(220, 252, 231, 0.95);
}
.avatar {
  position: relative;
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: linear-gradient(135deg, #d4ec90 0%, #a3e635 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 30px;
  font-weight: 800;
  color: #14532d;
}
.card.registered .avatar {
  background: linear-gradient(135deg, #86efac 0%, #16a34a 100%);
  color: white;
}
.check {
  position: absolute;
  right: -4px;
  bottom: -4px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #16a34a;
  color: white;
  font-size: 16px;
  font-weight: 900;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
}
.name {
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}
.status {
  font-size: 12px;
  color: #6b7280;
}
.card.registered .status { color: #16a34a; font-weight: 700; }

.actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 10px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}
.count { font-size: 16px; color: #374151; }
.count strong { color: #16a34a; font-size: 22px; margin: 0 4px; }

.start-btn {
  padding: 12px 28px;
  border: none;
  border-radius: 999px;
  background: linear-gradient(135deg, #16a34a 0%, #15803d 100%);
  color: white;
  font-size: 16px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 6px 18px rgba(22, 163, 74, 0.3);
  transition: transform 0.12s ease, opacity 0.18s ease;
}
.start-btn:hover { transform: translateY(-1px); }
.start-btn:disabled {
  background: #9ca3af;
  box-shadow: none;
  cursor: not-allowed;
  opacity: 0.7;
}
</style>
