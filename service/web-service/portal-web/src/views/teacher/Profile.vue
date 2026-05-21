<script setup lang="ts">
import { ref, onMounted } from 'vue'
import FaceCapture from '@/components/teacher/FaceCapture.vue'

interface Profile {
  id: string
  email: string
  name: string
  phone: string | null
  birth_date: string | null
  address: string | null
  class_name: string | null
  hired_date: string | null
  emergency_contact: string | null
  photo_url: string | null
  face_registered: boolean
  face_image_count: number
}

const me = ref<Profile | null>(null)
const saving = ref(false)
const error = ref<string | null>(null)
const successMessage = ref<string | null>(null)

const capturing = ref(false)
const uploading = ref(false)
// 같은 URL 이어도 새 얼굴 등록 후 브라우저 캐시를 우회하기 위한 cache-bust 토큰
const photoCacheBust = ref(Date.now())

async function load() {
  error.value = null
  const res = await fetch('/api/teachers/me', { credentials: 'include' })
  if (!res.ok) {
    error.value = '프로필을 불러오지 못했습니다.'
    return
  }
  me.value = (await res.json()) as Profile
}

async function save() {
  if (!me.value) return
  saving.value = true
  error.value = null
  successMessage.value = null
  try {
    const payload = {
      name: me.value.name,
      phone: me.value.phone,
      birth_date: me.value.birth_date,
      address: me.value.address,
      class_name: me.value.class_name,
      hired_date: me.value.hired_date,
      emergency_contact: me.value.emergency_contact,
    }
    const res = await fetch('/api/teachers/me', {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) throw new Error(`저장 실패 (HTTP ${res.status})`)
    me.value = (await res.json()) as Profile
    successMessage.value = '저장되었습니다.'
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

function startCapture() {
  capturing.value = true
  error.value = null
}

async function onFaceComplete(images: Blob[]) {
  if (!me.value) return
  uploading.value = true
  error.value = null
  try {
    const form = new FormData()
    images.forEach((b, i) => form.append('files', b, `face_${i}.jpg`))
    const res = await fetch('/api/teachers/me/face-images', {
      method: 'POST',
      credentials: 'include',
      body: form,
    })
    if (!res.ok) throw new Error(`업로드 실패 (HTTP ${res.status})`)
    const status = (await res.json()) as { registered: boolean; image_count: number }
    me.value.face_registered = status.registered
    me.value.face_image_count = status.image_count
    // 정면 사진(idx=0) 이 photo_url 로 자동 갱신되었으니 서버에서 다시 받아온다 + 캐시 우회
    await load()
    photoCacheBust.value = Date.now()
    capturing.value = false
    successMessage.value = '얼굴이 등록되었습니다. 정면 사진이 프로필 사진으로 설정되었습니다.'
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    uploading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section v-if="me" class="profile">
    <h2>내 정보</h2>

    <div class="profile-photo" data-test="profile-photo">
      <div class="avatar">
        <img
          v-if="me.photo_url"
          :key="me.photo_url + ':' + photoCacheBust"
          :src="me.photo_url + '?v=' + photoCacheBust"
          alt="프로필 사진"
        />
        <span v-else class="placeholder">📷</span>
      </div>
      <div class="profile-photo__hint">
        <p v-if="me.photo_url">정면 얼굴 사진이 프로필 사진으로 사용됩니다.</p>
        <p v-else>얼굴을 등록하면 정면 사진이 프로필 사진으로 자동 설정됩니다.</p>
      </div>
    </div>

    <div class="grid">
      <label>이메일 <span class="hint">(변경 불가)</span>
        <input type="email" :value="me.email" readonly />
      </label>

      <label>이름
        <input data-test="name" v-model="me.name" />
      </label>

      <label>생년월일
        <input data-test="birth-date" type="date" v-model="me.birth_date" />
      </label>

      <label>전화번호
        <input data-test="phone" v-model="me.phone" />
      </label>

      <label>주소
        <input data-test="address" v-model="me.address" />
      </label>

      <label>담당 반
        <input data-test="class-name" v-model="me.class_name" />
      </label>

      <label>입사일
        <input data-test="hired-date" type="date" v-model="me.hired_date" />
      </label>

      <label>비상연락처
        <input data-test="emergency-contact" v-model="me.emergency_contact" />
      </label>
    </div>

    <div class="actions">
      <button data-test="save" :disabled="saving" @click="save">
        {{ saving ? '저장 중…' : '저장' }}
      </button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="successMessage" class="success">{{ successMessage }}</p>

    <hr />

    <h3>GogoPing 추종용 얼굴 등록</h3>

    <div v-if="!capturing">
      <p v-if="!me.face_registered">
        아직 등록되지 않았습니다.
        <button data-test="start-face-capture" @click="startCapture">얼굴 캡처 시작</button>
      </p>
      <p v-else>
        등록됨 — {{ me.face_image_count }}장
        <button data-test="start-face-capture" @click="startCapture">재캡처</button>
      </p>
    </div>

    <div v-else data-test="face-capture" class="face-capture">
      <FaceCapture :uploading="uploading" @complete="onFaceComplete" />
      <button class="cancel" :disabled="uploading" @click="capturing = false">취소</button>
    </div>
  </section>

  <p v-else-if="error" class="error">{{ error }}</p>
  <p v-else>로딩 중…</p>
</template>

<style scoped>
.profile {
  display: flex;
  flex-direction: column;
  gap: var(--space-4, 1rem);
  max-width: 720px;
}
.profile-photo {
  display: flex;
  align-items: center;
  gap: var(--space-4, 1rem);
  padding: var(--space-3, 0.75rem) 0;
}
.avatar {
  width: 96px;
  height: 96px;
  border-radius: 50%;
  background: var(--color-surface-sunken, #f5f5f5);
  border: 1px solid var(--color-border, #ddd);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.avatar img { width: 100%; height: 100%; object-fit: cover; }
.avatar .placeholder { font-size: 2.5rem; color: var(--color-text-muted, #888); }
.profile-photo__hint { color: var(--color-text-muted, #777); font-size: 0.875rem; }
.profile-photo__hint p { margin: 0; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--space-3, 0.75rem);
}
.profile label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: var(--font-size-sm, 0.875rem);
}
.profile input {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--color-border, #ddd);
  border-radius: var(--radius-md, 6px);
  background: var(--color-surface-raised, #fff);
}
.profile input[readonly] {
  background: var(--color-surface-sunken, #f5f5f5);
  color: var(--color-text-muted, #777);
}
.hint { color: var(--color-text-muted, #888); font-size: 0.75rem; margin-left: 0.25rem; }
.actions { display: flex; gap: 0.5rem; }
.actions button {
  padding: 0.6rem 1.2rem;
  border-radius: var(--radius-md, 6px);
  background: var(--color-brand-primary, #f59f4d);
  color: #fff;
  border: none;
  cursor: pointer;
}
.actions button:disabled { opacity: 0.6; cursor: progress; }
.error { color: var(--color-status-danger, #c33); }
.success { color: var(--color-status-success, #2a7); }
.face-capture { display: flex; flex-direction: column; gap: 0.5rem; }
.face-capture .cancel {
  align-self: flex-start;
  padding: 0.4rem 1rem;
  background: var(--color-surface-sunken, #eee);
  border: 1px solid var(--color-border, #ddd);
  border-radius: var(--radius-md, 6px);
  cursor: pointer;
}
</style>
