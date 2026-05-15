<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import { api } from '@/api/client'
import { useChildStore } from '@/stores/child'
import type { Photo } from '@/types'
import PhotoGrid from '@/components/parent/PhotoGrid.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseEmptyState from '@/components/common/BaseEmptyState.vue'

const child = useChildStore()
const photos = ref<Photo[]>([])

watchEffect(async () => {
  if (child.selectedChildId === null) return
  photos.value = await api.get<Photo[]>(
    `/api/children/${child.selectedChildId}/photos`
  )
})
</script>

<template>
  <section>
    <PageHeader title="사진첩" :description="`최근 ${photos.length}장`" />
    <PhotoGrid v-if="photos.length" :photos="photos" />
    <BaseEmptyState
      v-else
      icon="images"
      title="아직 사진이 없습니다"
      description="로봇이 촬영한 사진이 누적되면 여기에 표시됩니다."
    />
  </section>
</template>
