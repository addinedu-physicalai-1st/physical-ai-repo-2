<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'
import type { Child, ChildDetail, ParentInfo } from '@/types'
import FaceCapture from '@/components/teacher/FaceCapture.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseCard from '@/components/common/BaseCard.vue'
import BaseButton from '@/components/common/BaseButton.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import BaseTextarea from '@/components/common/BaseTextarea.vue'
import BaseAvatar from '@/components/common/BaseAvatar.vue'
import BaseEmptyState from '@/components/common/BaseEmptyState.vue'
import Icon from '@/components/common/Icon.vue'

const router = useRouter()

const children = ref<Child[]>([])
const selected = ref<ChildDetail | null>(null)
const loading = ref(true)
const listError = ref<string | null>(null)

const notesDraft = ref('')
const editingNotes = ref(false)
const savingNotes = ref(false)

interface ParentDraft { name: string; email: string; phone: string }
const editingParentId = ref<string | null>(null)
const parentDraft = ref<ParentDraft>({ name: '', email: '', phone: '' })
const savingParent = ref(false)
const parentError = ref<string | null>(null)

const capturing = ref(false)
const uploadingFace = ref(false)
const faceError = ref<string | null>(null)

const sorted = computed(() =>
  [...children.value].sort(
    (a, b) => a.class_name.localeCompare(b.class_name) || a.name.localeCompare(b.name)
  )
)

onMounted(async () => {
  listError.value = null
  try {
    children.value = await api.get<Child[]>('/api/children')
  } catch (e) {
    children.value = []
    if (e instanceof ApiError) {
      if (e.status === 401) {
        listError.value =
          '로그인이 필요하거나 세션이 만료되었습니다. 교사 계정으로 다시 로그인해 주세요.'
      } else if (e.status === 502 || e.status === 503) {
        listError.value =
          `연결할 수 없습니다 (HTTP ${e.status}). Control 서버가 떠 있는지, Vite 프록시(CONTROL_URL)를 확인해 주세요.`
      } else {
        listError.value = `목록을 불러오지 못했습니다 (HTTP ${e.status}). DB 마이그레이션(예: alembic upgrade head)과 서버 로그를 확인해 주세요.`
      }
    } else {
      listError.value = '목록을 불러오지 못했습니다. 네트워크와 서버 상태를 확인해 주세요.'
    }
  } finally {
    loading.value = false
  }
})

async function open(c: Child) {
  selected.value = await api.get<ChildDetail>(`/api/children/${c.id}`)
  notesDraft.value = selected.value?.notes ?? ''
  editingNotes.value = false
  editingParentId.value = null
  capturing.value = false
  faceError.value = null
}

function startEditNotes() {
  notesDraft.value = selected.value?.notes ?? ''
  editingNotes.value = true
}

async function saveNotes() {
  if (!selected.value) return
  savingNotes.value = true
  try {
    const trimmed = notesDraft.value.trim()
    const updated = await api.patch<Child>(
      `/api/children/${selected.value.id}`,
      { notes: trimmed || null },
    )
    selected.value.notes = updated.notes
    const inList = children.value.find((c) => c.id === updated.id)
    if (inList) inList.notes = updated.notes
    editingNotes.value = false
  } finally {
    savingNotes.value = false
  }
}

function cancelNotes() {
  editingNotes.value = false
  notesDraft.value = selected.value?.notes ?? ''
}

function startEditParent(p: ParentInfo) {
  editingParentId.value = String(p.id)
  parentDraft.value = { name: p.name, email: p.email, phone: p.phone }
  parentError.value = null
}

function cancelParent() {
  editingParentId.value = null
  parentError.value = null
}

async function saveParent() {
  if (!selected.value || !editingParentId.value) return
  savingParent.value = true
  parentError.value = null
  try {
    const updated = await api.patch<ParentInfo>(
      `/api/parents/${editingParentId.value}`,
      {
        name: parentDraft.value.name.trim(),
        email: parentDraft.value.email.trim(),
        phone: parentDraft.value.phone.trim(),
      },
    )
    const idx = selected.value.parents.findIndex((p) => String(p.id) === String(updated.id))
    if (idx >= 0) selected.value.parents[idx] = updated
    editingParentId.value = null
  } catch (e) {
    parentError.value =
      e instanceof Error && /409/.test(e.message)
        ? '이미 사용 중인 이메일입니다.'
        : '학부모 정보를 저장하지 못했습니다.'
  } finally {
    savingParent.value = false
  }
}

async function onFaceCaptured(images: Blob[]) {
  if (!selected.value) return
  const childId = selected.value.id
  uploadingFace.value = true
  faceError.value = null
  // 업로드: InsightFace 임베딩 5장 추출이 CPU 동기 작업이라 수초 걸린다.
  // 무한 대기 방지를 위해 60s 타임아웃을 둔다.
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 60_000)
  try {
    const form = new FormData()
    images.forEach((b, i) => form.append('files', b, `face_${i}.jpg`))
    const res = await fetch(`/api/children/${childId}/face-images`, {
      method: 'POST',
      credentials: 'include',
      body: form,
      signal: controller.signal,
    })
    if (!res.ok) throw new Error(`업로드 실패 (HTTP ${res.status})`)

    const refreshed = await api.get<ChildDetail>(`/api/children/${childId}`)
    selected.value = refreshed
    notesDraft.value = refreshed.notes ?? ''
    const inList = children.value.find((c) => c.id === refreshed.id)
    if (inList) inList.photo_url = refreshed.photo_url
    capturing.value = false
  } catch (e) {
    const msg = (e as Error).name === 'AbortError'
      ? '서버 응답 시간 초과 — 다시 시도해주세요.'
      : (e as Error).message
    faceError.value = msg
  } finally {
    window.clearTimeout(timer)
    uploadingFace.value = false
  }
}

function gotoRegister() {
  router.push('/teacher/children/new')
}
</script>

<template>
  <section>
    <PageHeader title="어린이 관리" description="등록된 어린이 정보와 학부모 연락처를 관리합니다.">
      <template #actions>
        <BaseButton variant="primary" icon-start="plus" @click="gotoRegister">새 어린이 등록</BaseButton>
      </template>
    </PageHeader>

    <div class="layout">
      <BaseCard class="list grid-card--attendance" :padded="false">
        <template #header>
          <div class="list-head"><Icon name="users-round" :size="16" /><span>명단</span></div>
        </template>
        <p v-if="loading" class="muted">불러오는 중...</p>
        <ul v-else-if="!listError && sorted.length" class="ul">
          <li
            v-for="c in sorted"
            :key="c.id"
            :class="{ 'is-active': selected?.id === c.id }"
            @click="open(c)"
          >
            <BaseAvatar :name="c.name" :src="c.photo_url ?? null" :size="36" />
            <div class="meta">
              <strong>{{ c.name }}</strong>
              <span>{{ c.class_name }} · {{ c.birth_date }}</span>
            </div>
            <Icon name="chevron-right" :size="16" class="meta-arrow" />
          </li>
        </ul>
        <BaseEmptyState
          v-if="!loading && listError"
          icon="alert-circle"
          title="명단을 불러오지 못했습니다"
          :description="listError"
        />
        <BaseEmptyState
          v-else-if="!loading && !sorted.length"
          icon="users-round"
          title="등록된 어린이가 없습니다"
          description="DB에 원아 행이 없거나 아직 등록하지 않았습니다. 시드( python -m control_db.seed )를 돌렸는지 확인하거나, 새 어린이 등록으로 추가하세요."
        />
      </BaseCard>

      <BaseCard class="detail" :padded="true">
        <BaseEmptyState
          v-if="!selected"
          icon="user-round"
          title="어린이를 선택하세요"
          description="왼쪽 목록에서 정보를 확인할 어린이를 선택하면 상세가 표시됩니다."
        />
        <div v-else class="detail__body">
          <header class="detail__head">
            <BaseAvatar :name="selected.name" :src="selected.photo_url ?? null" :size="56" />
            <div>
              <h2 class="detail__name">{{ selected.name }}</h2>
              <p class="detail__sub">{{ selected.class_name }} · {{ selected.birth_date }}</p>
            </div>
          </header>

          <section class="block">
            <div class="block__head">
              <h3><Icon name="camera" :size="14" /> 얼굴 캡처</h3>
              <BaseButton v-if="!capturing" variant="ghost" size="sm" @click="capturing = true">
                {{ selected.photo_url ? '재촬영' : '캡처 시작' }}
              </BaseButton>
              <BaseButton v-else variant="ghost" size="sm" :disabled="uploadingFace" @click="capturing = false">
                취소
              </BaseButton>
            </div>
            <div v-if="!capturing" class="face-preview">
              <img v-if="selected.photo_url" :src="selected.photo_url" alt="대표 사진" class="face-img" />
              <p v-else class="muted small">등록된 얼굴 사진이 없습니다.</p>
            </div>
            <div v-else>
              <FaceCapture :uploading="uploadingFace" @complete="onFaceCaptured" />
            </div>
            <p v-if="faceError" class="error small">{{ faceError }}</p>
          </section>

          <section class="block">
            <div class="block__head">
              <h3><Icon name="alert-circle" :size="14" /> 특이사항</h3>
              <BaseButton v-if="!editingNotes" variant="ghost" size="sm" icon-start="pencil" @click="startEditNotes">
                편집
              </BaseButton>
            </div>
            <p v-if="!editingNotes && !selected.notes" class="muted small">기록된 특이사항이 없습니다.</p>
            <p v-else-if="!editingNotes" class="notes-body">{{ selected.notes }}</p>
            <div v-else class="edit-form">
              <BaseTextarea v-model="notesDraft" :rows="4" placeholder="알레르기, 건강 상태, 성격 등" />
              <div class="edit-actions">
                <BaseButton variant="ghost" size="sm" :disabled="savingNotes" @click="cancelNotes">취소</BaseButton>
                <BaseButton variant="primary" size="sm" :loading="savingNotes" @click="saveNotes">저장</BaseButton>
              </div>
            </div>
          </section>

          <section class="block">
            <div class="block__head">
              <h3><Icon name="users" :size="14" /> 학부모</h3>
            </div>
            <ul class="parents">
              <li v-for="p in selected.parents" :key="String(p.id)">
                <template v-if="editingParentId !== String(p.id)">
                  <div class="parent-info">
                    <strong>{{ p.name }}</strong>
                    <span>{{ p.email }}</span>
                    <span>{{ p.phone }}</span>
                  </div>
                  <BaseButton variant="ghost" size="sm" icon-start="pencil" @click="startEditParent(p)">편집</BaseButton>
                </template>
                <div v-else class="edit-form">
                  <BaseInput v-model="parentDraft.name" label="이름" />
                  <BaseInput v-model="parentDraft.email" type="email" label="이메일" />
                  <BaseInput v-model="parentDraft.phone" label="연락처" />
                  <p v-if="parentError" class="error small">{{ parentError }}</p>
                  <div class="edit-actions">
                    <BaseButton variant="ghost" size="sm" :disabled="savingParent" @click="cancelParent">취소</BaseButton>
                    <BaseButton variant="primary" size="sm" :loading="savingParent" @click="saveParent">저장</BaseButton>
                  </div>
                </div>
              </li>
            </ul>
            <p v-if="!selected.parents.length" class="muted small">연결된 학부모가 없습니다.</p>
          </section>
        </div>
      </BaseCard>
    </div>
  </section>
</template>

<style scoped>
.layout { display: grid; grid-template-columns: 320px 1fr; gap: var(--space-4); align-items: start; }

.list-head { padding: 1rem; display: flex; align-items: center; gap: var(--space-2); color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.ul { list-style: none; padding: var(--space-2); margin: 0; }
.ul li {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--motion-base) var(--motion-ease);
}
.ul li:hover { background: var(--color-surface-sunken); }
.ul li.is-active { background: var(--color-brand-primary-soft); }
.meta { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.meta strong { font-size: var(--font-size-sm); }
.meta span { font-size: var(--font-size-xs); color: var(--color-text-secondary); }
.meta-arrow { color: var(--color-text-muted); }

.detail__head { display: flex; align-items: center; gap: var(--space-4); margin-bottom: var(--space-5); padding-bottom: var(--space-4); border-bottom: 1px solid var(--color-border-subtle); }
.detail__name { font-size: var(--font-size-xl); }
.detail__sub { font-size: var(--font-size-sm); color: var(--color-text-secondary); margin-top: 2px; }

.block { margin-top: var(--space-5); }
.block__head { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-3); }
.block__head h3 { font-size: var(--font-size-sm); color: var(--color-text-secondary); display: inline-flex; align-items: center; gap: var(--space-2); }
.notes-body { white-space: pre-wrap; font-size: var(--font-size-sm); color: var(--color-text-primary); }

.face-preview { display: flex; align-items: center; gap: var(--space-3); }
.face-img { width: 120px; height: 120px; object-fit: cover; border-radius: var(--radius-lg); border: 1px solid var(--color-border-subtle); }

.edit-form { display: flex; flex-direction: column; gap: var(--space-3); }
.edit-actions { display: flex; justify-content: flex-end; gap: var(--space-2); }

.parents { list-style: none; margin: 0; padding: 0; }
.parents li {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--color-border-subtle);
}
.parents li:last-child { border-bottom: none; }
.parent-info { display: flex; flex-direction: column; gap: 2px; }
.parent-info strong { font-size: var(--font-size-sm); }
.parent-info span { font-size: var(--font-size-xs); color: var(--color-text-secondary); }

.muted { color: var(--color-text-muted); padding: var(--space-4); text-align: center; }
.muted.small { padding: var(--space-2) 0; font-size: var(--font-size-sm); text-align: left; }
.error.small { color: var(--color-status-danger); font-size: var(--font-size-xs); }
.grid-card--attendance {
  position: relative;
  overflow: hidden;
}
.grid-card--attendance::after {
  content: '🎒';
  position: absolute;
  bottom: -20px;
  right: -20px;
  font-size: 140px;
  opacity: 0.12;
  transform: rotate(-15deg);
  pointer-events: none;
}
</style>
