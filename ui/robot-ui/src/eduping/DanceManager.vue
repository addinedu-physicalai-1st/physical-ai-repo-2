<script setup lang="ts">
/**
 * 율동 등록 — 곡(mp3/wav/m4a) 업로드 + 그 곡에 대한 모션 녹화 + 라이브러리.
 *
 * - GET    /api/eduping/dance              라이브러리 목록
 * - POST   /api/eduping/dance              {slug, display_name, song} 새 항목
 * - DELETE /api/eduping/dance/{slug}       삭제
 * - 녹화/재생은 RecorderControls 가 처리.
 *
 * three.js 뷰어는 leader 출력 (녹화 시 puppeteer 모션이 실시간 보임).
 */
import { computed, onMounted, ref } from 'vue';
import { useModeStore } from '@/stores/mode';
import OpenarmViewer from './OpenarmViewer.vue';
import RecorderControls from './RecorderControls.vue';

interface DanceItem {
  slug: string;
  display_name: string;
  duration_s?: number;
  recorded_at?: string;
  has_song?: boolean;
  has_motion?: boolean;
}

const mode = useModeStore();

const items = ref<DanceItem[]>([]);
const selectedSlug = ref<string>('');
const loading = ref(false);
const error = ref('');

// 새 항목 폼
const showNewForm = ref(false);
const newSlug = ref('');
const newDisplayName = ref('');
const newSong = ref<File | null>(null);
const newError = ref('');
const newSubmitting = ref(false);

const selected = computed(() => items.value.find((i) => i.slug === selectedSlug.value));

async function refresh(): Promise<void> {
  loading.value = true;
  error.value = '';
  try {
    const res = await fetch('/api/eduping/dance');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    items.value = json.items ?? [];
    if (selectedSlug.value && !items.value.some((i) => i.slug === selectedSlug.value)) {
      selectedSlug.value = '';
    }
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

async function submitNew(): Promise<void> {
  newError.value = '';
  if (!newSlug.value.match(/^[a-z0-9][a-z0-9-]{0,63}$/)) {
    newError.value = 'slug 는 영문 소문자/숫자/하이픈만 (첫 글자 영숫자), 1~64자';
    return;
  }
  if (!newDisplayName.value.trim()) {
    newError.value = '곡명을 입력하세요';
    return;
  }
  if (!newSong.value) {
    newError.value = '곡 파일을 선택하세요';
    return;
  }
  const fd = new FormData();
  fd.append('slug', newSlug.value);
  fd.append('display_name', newDisplayName.value.trim());
  fd.append('song', newSong.value);
  newSubmitting.value = true;
  try {
    const res = await fetch('/api/eduping/dance', { method: 'POST', body: fd });
    const txt = await res.text();
    if (!res.ok) throw new Error(txt || `HTTP ${res.status}`);
    showNewForm.value = false;
    newSlug.value = '';
    newDisplayName.value = '';
    newSong.value = null;
    await refresh();
    selectedSlug.value = JSON.parse(txt).slug;
  } catch (e) {
    newError.value = (e as Error).message;
  } finally {
    newSubmitting.value = false;
  }
}

async function remove(slug: string): Promise<void> {
  if (!confirm(`'${slug}' 율동을 삭제할까요? (곡+모션 모두)`)) return;
  try {
    const res = await fetch(`/api/eduping/dance/${encodeURIComponent(slug)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    if (selectedSlug.value === slug) selectedSlug.value = '';
    await refresh();
  } catch (e) {
    error.value = (e as Error).message;
  }
}

function close(): void {
  mode.setMode('대기');
}

onMounted(refresh);
</script>

<template>
  <div class="dance-mgr">
    <header class="bar">
      <h2>🎵 율동 등록</h2>
      <button type="button" class="btn-close" @click="close">닫기</button>
    </header>

    <div class="grid">
      <div class="viewer">
        <OpenarmViewer source="leader" />
      </div>

      <aside class="side">
        <section class="library">
          <div class="library-head">
            <h3>라이브러리 ({{ items.length }})</h3>
            <button
              type="button"
              class="btn-add"
              :disabled="showNewForm"
              @click="showNewForm = true"
            >+ 새 율동</button>
          </div>

          <div v-if="loading" class="muted">로딩…</div>
          <div v-else-if="error" class="err">{{ error }}</div>
          <ul v-else class="list">
            <li
              v-for="item in items"
              :key="item.slug"
              class="item"
              :class="{ selected: item.slug === selectedSlug }"
              @click="selectedSlug = item.slug"
            >
              <div class="item-name">🎵 {{ item.display_name }}</div>
              <div class="item-meta">
                <span class="slug">{{ item.slug }}</span>
                <span v-if="item.duration_s">{{ item.duration_s.toFixed(1) }}s</span>
                <span v-if="item.has_song === false" class="warn">곡없음</span>
                <span v-if="item.has_motion === false" class="warn">모션없음</span>
              </div>
              <button type="button" class="del" @click.stop="remove(item.slug)">🗑</button>
            </li>
            <li v-if="items.length === 0" class="empty">아직 등록된 율동 없음 — 새 율동으로 추가</li>
          </ul>
        </section>

        <section v-if="showNewForm" class="new-form">
          <h3>새 율동</h3>
          <label>
            slug <small>(URL용 영문/숫자/하이픈)</small>
            <input v-model="newSlug" type="text" placeholder="bear-three" />
          </label>
          <label>
            곡명 (표시용)
            <input v-model="newDisplayName" type="text" placeholder="곰 세 마리" />
          </label>
          <label>
            곡 파일 (mp3 / wav / m4a)
            <input
              type="file"
              accept=".mp3,.wav,.m4a,audio/*"
              @change="(e) => newSong = (e.target as HTMLInputElement).files?.[0] ?? null"
            />
          </label>
          <div v-if="newError" class="err">{{ newError }}</div>
          <div class="row">
            <button type="button" class="btn-primary" :disabled="newSubmitting" @click="submitNew">생성</button>
            <button type="button" class="btn-secondary" :disabled="newSubmitting" @click="showNewForm = false">취소</button>
          </div>
        </section>

        <section v-if="selected" class="recorder-section">
          <div class="selected-meta">
            <strong>{{ selected.display_name }}</strong>
            <span v-if="selected.recorded_at" class="muted small">{{ selected.recorded_at }}</span>
          </div>
          <RecorderControls
            kind="dance"
            :name="selected.slug"
            @recorded="refresh"
          />
        </section>
        <section v-else class="recorder-section muted">
          라이브러리에서 율동을 선택하면 녹화·재생 컨트롤이 표시됩니다.
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.dance-mgr {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  background: rgba(255, 247, 251, 0.96);
  z-index: 50;
}
.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  background: rgba(219, 39, 119, 0.08);
}
.bar h2 { margin: 0; font-size: 22px; color: #be185d; }
.btn-close {
  padding: 6px 14px;
  background: white;
  border: 1px solid #e0d0db;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
  color: #475569;
}
.grid {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 420px;
  gap: 14px;
  padding: 14px 24px 24px;
  min-height: 0;
}
.viewer { min-height: 0; }
.side {
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}
.library, .new-form, .recorder-section {
  background: rgba(255,255,255,0.85);
  border-radius: 12px;
  padding: 12px 14px;
}
.library-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.library-head h3 { margin: 0; font-size: 16px; color: #475569; }
.btn-add {
  padding: 6px 12px;
  border: none;
  border-radius: 8px;
  background: #fce7f3;
  color: #be185d;
  font-weight: 600;
  cursor: pointer;
}
.btn-add:disabled { opacity: 0.4; }

.list { list-style: none; padding: 0; margin: 0; }
.item {
  display: flex;
  flex-direction: column;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  position: relative;
  margin-bottom: 4px;
  background: white;
  border: 1px solid transparent;
}
.item:hover { background: #fdf2f8; }
.item.selected { border-color: #ec4899; background: #fce7f3; }
.item-name { font-weight: 600; color: #334155; }
.item-meta {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}
.item-meta .slug { color: #94a3b8; }
.item-meta .warn { color: #b45309; }
.item .del {
  position: absolute;
  right: 8px;
  top: 8px;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 16px;
  opacity: 0.5;
}
.item .del:hover { opacity: 1; }
.empty { color: #94a3b8; padding: 12px; text-align: center; }

.new-form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
  font-size: 13px;
  color: #475569;
}
.new-form input[type="text"], .new-form input[type="file"] {
  padding: 6px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
}
.new-form small { color: #94a3b8; font-weight: normal; }
.row { display: flex; gap: 8px; margin-top: 4px; }
.btn-primary {
  padding: 8px 16px;
  background: #ec4899;
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
}
.btn-primary:disabled { opacity: 0.5; }
.btn-secondary {
  padding: 8px 16px;
  background: #e2e8f0;
  color: #475569;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
}
.selected-meta {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 8px;
}
.selected-meta strong { font-size: 15px; color: #334155; }
.muted { color: #94a3b8; }
.small { font-size: 12px; }
.err {
  color: #c14545;
  background: #fef2f2;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 13px;
  margin-top: 6px;
}
</style>
