import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useChildStore = defineStore('child', () => {
  const selectedChildId = ref<number | null>(null)

  function select(id: number) {
    selectedChildId.value = id
  }

  function clear() {
    selectedChildId.value = null
  }

  return { selectedChildId, select, clear }
})
