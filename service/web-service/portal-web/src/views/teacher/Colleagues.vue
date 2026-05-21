<script setup lang="ts">
import { ref, onMounted } from 'vue'

interface Colleague {
  id: string
  name: string
  class_name: string | null
  phone: string | null
  emergency_contact: string | null
  photo_url: string | null
  hired_date: string | null
}

const list = ref<Colleague[]>([])
const error = ref<string | null>(null)
const loading = ref(true)

onMounted(async () => {
  try {
    const res = await fetch('/api/teachers/', { credentials: 'include' })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    list.value = (await res.json()) as Colleague[]
  } catch (e) {
    error.value = `교사 목록을 불러오지 못했습니다. (${(e as Error).message})`
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="colleagues">
    <h2>교사 목록</h2>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading">로딩 중…</p>
    <div v-else class="grid">
      <article
        v-for="t in list"
        :key="t.id"
        data-test="teacher-card"
        class="card"
      >
        <div class="avatar">
          <img v-if="t.photo_url" :src="t.photo_url" alt="" />
          <span v-else>📷</span>
        </div>
        <h3>{{ t.name }}</h3>
        <p class="class-name">{{ t.class_name ?? '— 미배정' }}</p>
        <dl>
          <template v-if="t.phone">
            <dt>전화</dt><dd>{{ t.phone }}</dd>
          </template>
          <template v-if="t.emergency_contact">
            <dt>비상</dt><dd>{{ t.emergency_contact }}</dd>
          </template>
          <template v-if="t.hired_date">
            <dt>입사</dt><dd>{{ t.hired_date }}</dd>
          </template>
        </dl>
      </article>
    </div>
  </section>
</template>

<style scoped>
.colleagues { display: flex; flex-direction: column; gap: var(--space-4, 1rem); }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-4, 1rem);
}
.card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: var(--space-4, 1rem);
  background: var(--color-surface-raised, #fff);
  border: 1px solid var(--color-border, #ddd);
  border-radius: var(--radius-md, 8px);
  box-shadow: var(--shadow-sm, 0 1px 2px rgba(0,0,0,0.05));
}
.avatar {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--color-surface-sunken, #f5f5f5);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2rem;
  overflow: hidden;
}
.avatar img { width: 100%; height: 100%; object-fit: cover; }
.class-name { color: var(--color-text-muted, #666); margin: 0; }
dl {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 2px 0.5rem;
  margin: 0;
  font-size: 0.875rem;
}
dt { color: var(--color-text-muted, #666); }
dd { margin: 0; }
.error { color: var(--color-status-danger, #c33); }
h3 { margin: 0; }
</style>
