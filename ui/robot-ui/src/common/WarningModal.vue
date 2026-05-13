<script setup lang="ts">
/**
 * WarningModal — 경고/확인 다이얼로그.
 * cancelText 가 주어지면 confirm/cancel 두-버튼 모드 (backdrop = cancel).
 * 그 외에는 단일 OK 알림 모드 (backdrop = ok).
 */
const props = defineProps<{
  open: boolean;
  title?: string;
  message: string;
  okText?: string;
  cancelText?: string;
}>();

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void;
  (e: 'ok'): void;
  (e: 'cancel'): void;
}>();

function confirm(): void {
  emit('update:open', false);
  emit('ok');
}

function cancel(): void {
  emit('update:open', false);
  emit('cancel');
}

function onBackdrop(): void {
  if (props.cancelText) cancel();
  else confirm();
}
</script>

<template>
  <Transition name="fade">
    <div v-if="open" class="warn-overlay" @click.self="onBackdrop">
      <Transition name="pop" appear>
        <div v-if="open" class="warn-card" role="dialog" aria-modal="true">
          <div class="warn-icon-wrap">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>
          <h3 v-if="title" class="warn-title">{{ title }}</h3>
          <pre class="warn-msg">{{ message }}</pre>
          <div class="warn-actions" :class="{ single: !cancelText }">
            <button
              v-if="cancelText"
              type="button"
              class="warn-btn warn-btn-cancel"
              @click="cancel"
            >{{ cancelText }}</button>
            <button type="button" class="warn-btn" @click="confirm">
              {{ okText ?? '확인' }}
            </button>
          </div>
        </div>
      </Transition>
    </div>
  </Transition>
</template>

<style scoped>
.warn-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.48);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  backdrop-filter: blur(4px);
}
.warn-card {
  background: white;
  border-radius: 20px;
  padding: 32px 32px 24px;
  min-width: 380px;
  max-width: 460px;
  box-shadow: 0 24px 64px -12px rgba(15, 23, 42, 0.35),
              0 0 0 1px rgba(15, 23, 42, 0.04);
  display: flex;
  flex-direction: column;
  align-items: center;
}
.warn-icon-wrap {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background: #fef3c7;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #d97706;
  box-shadow: 0 0 0 8px rgba(245, 158, 11, 0.10);
}
.warn-icon-wrap svg {
  width: 30px;
  height: 30px;
}
.warn-title {
  margin: 18px 0 0;
  font-size: 19px;
  font-weight: 700;
  color: #0f172a;
  text-align: center;
  letter-spacing: -0.01em;
}
.warn-msg {
  margin: 22px 0 0;
  font-size: 14.5px;
  color: #475569;
  text-align: center;
  white-space: pre-wrap;
  font-family: inherit;
  line-height: 1.5;
  width: 100%;
  box-sizing: border-box;
}
.warn-actions {
  display: flex;
  gap: 10px;
  margin-top: 24px;
  width: 100%;
}
.warn-actions.single {
  justify-content: center;
}
.warn-btn {
  padding: 12px 24px;
  border: none;
  border-radius: 12px;
  background: #f59e0b;
  color: white;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.12s, transform 0.05s, box-shadow 0.12s;
  box-shadow: 0 4px 12px -4px rgba(245, 158, 11, 0.55);
}
.warn-actions:not(.single) .warn-btn {
  flex: 1;
}
.warn-actions.single .warn-btn {
  min-width: 140px;
}
.warn-btn:hover { background: #d97706; }
.warn-btn:active { transform: translateY(1px); }
.warn-btn-cancel {
  background: #f1f5f9;
  color: #475569;
  box-shadow: none;
}
.warn-btn-cancel:hover { background: #e2e8f0; }

.fade-enter-active, .fade-leave-active { transition: opacity 0.18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.pop-enter-active { transition: opacity 0.22s ease, transform 0.22s cubic-bezier(.16,1,.3,1); }
.pop-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.pop-enter-from { opacity: 0; transform: scale(0.92) translateY(8px); }
.pop-leave-to { opacity: 0; transform: scale(0.96); }
</style>
