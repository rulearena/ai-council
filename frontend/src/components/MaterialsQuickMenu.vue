<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'

// LINE 風格的「＋」：只負責上傳與跳到資料管理，計數顯示在側欄資料頁籤。
// 上傳鎖（disabled）由父層計算（loading || isMeetingRunning）；「資料管理」
// 不受鎖。常駐 DOM 的隱藏 file input 可被 e2e 直接 setInputFiles，不需先開選單。
const props = defineProps<{
  meetingId: string
  disabled?: boolean
  uploadHint?: string
}>()

const emit = defineEmits<{
  'pick-files': [files: File[]]
  'manage-materials': []
}>()

const menuOpen = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

watch(() => props.meetingId, () => {
  menuOpen.value = false
})

function onDocumentClick(event: MouseEvent) {
  if (!(event.target as HTMLElement).closest('.materials-quick-menu')) menuOpen.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') menuOpen.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})

function onUploadClick() {
  menuOpen.value = false
  if (props.disabled) return
  fileInput.value?.click()
}

function onManageClick() {
  menuOpen.value = false
  emit('manage-materials')
}

function onFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (files.length) emit('pick-files', files)
}
</script>

<template>
  <div class="materials-quick-menu" data-testid="materials-quick-menu">
    <button
      type="button"
      class="btn btn-secondary workspace-materials-button"
      data-testid="materials-quick-menu-button"
      aria-label="附件與資料"
      aria-haspopup="menu"
      :aria-expanded="menuOpen"
      @click="menuOpen = !menuOpen"
    >＋</button>
    <div v-if="menuOpen" class="materials-menu" data-testid="materials-menu">
      <button
        type="button"
        class="materials-menu-item"
        data-testid="materials-menu-upload"
        :disabled="disabled"
        @click="onUploadClick"
      >上傳檔案</button>
      <small v-if="disabled" class="materials-menu-hint" data-testid="materials-menu-hint">{{ uploadHint || '會議執行中，暫時無法上傳' }}</small>
      <button
        type="button"
        class="materials-menu-item"
        data-testid="materials-menu-manage"
        @click="onManageClick"
      >資料管理</button>
    </div>
    <input
      ref="fileInput"
      type="file"
      class="visually-hidden"
      data-testid="attachment-upload-input"
      multiple
      :disabled="disabled"
      @change="onFileSelected"
    />
  </div>
</template>

<style scoped>
.materials-quick-menu {
  position: relative;
  flex: none;
}

.materials-menu {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  z-index: 60;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 150px;
  padding: 6px;
  background: var(--bg, #fff);
  border: 1px solid var(--border, #ddd);
  border-radius: 8px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.12);
}

.materials-menu-item {
  text-align: left;
  padding: 8px 10px;
  border: none;
  border-radius: 6px;
  background: none;
  font: inherit;
  cursor: pointer;
}

.materials-menu-item:hover:not(:disabled) {
  background: var(--bg-muted, #f5f5f5);
}

.materials-menu-item:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.materials-menu-hint {
  padding: 0 10px 6px;
  opacity: 0.7;
  font-size: 0.82em;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
