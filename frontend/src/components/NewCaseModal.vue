<script setup lang="ts">
import { inject } from 'vue'
import { councilKey } from '../composables/useCouncil'
import Modal from './Modal.vue'

defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: [] }>()

const store = inject(councilKey)!
const { topic, loading, createNewMeeting } = store

async function submit() {
  await createNewMeeting()
  emit('close')
}
</script>

<template>
  <Modal :show="show" title="New Case" test-id="new-case-modal" close-test-id="new-case-close-button" @close="$emit('close')">
    <div class="create-box">
      <input v-model="topic" aria-label="會議主題" />
      <button
        type="button"
        class="btn btn-primary"
        data-testid="create-meeting-button"
        @click="submit"
        :disabled="loading || !topic.trim()"
      >
        建立
      </button>
    </div>
  </Modal>
</template>
