<script setup lang="ts">
import { computed, ref } from 'vue'
import { attachmentDownloadUrl } from '../api'
import { formatAttachmentSize } from '../meetingWorkspace'
import Modal from './Modal.vue'

const props = defineProps<{
  meetingId: string
  event: {
    file_id?: string
    filename?: string
    size?: number
    mime_type?: string
    removed?: boolean
  }
  attachmentLabel?: string
}>()

const lightboxOpen = ref(false)
const readerOpen = ref(false)
const readerContent = ref('')
const readerLoading = ref(false)
const readerError = ref('')

const filename = computed(() => props.event.filename ?? props.event.file_id ?? '附件')
const size = computed(() => formatAttachmentSize(props.event.size ?? 0))
const downloadUrl = computed(() => {
  const fileId = props.event.file_id
  return fileId ? attachmentDownloadUrl(props.meetingId, fileId) : ''
})
const isImage = computed(() => props.event.mime_type?.startsWith('image/') ?? false)
const isPdf = computed(() => props.event.mime_type === 'application/pdf')
const isText = computed(() =>
  props.event.mime_type === 'text/plain' || props.event.mime_type === 'text/markdown',
)

function openLightbox() {
  if (downloadUrl.value) lightboxOpen.value = true
}

async function openReader() {
  if (!downloadUrl.value || readerOpen.value) return
  readerOpen.value = true
  readerLoading.value = true
  readerError.value = ''
  readerContent.value = ''
  try {
    const response = await fetch(downloadUrl.value)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    readerContent.value = await response.text()
  } catch (caught) {
    readerError.value = caught instanceof Error ? caught.message : String(caught)
  } finally {
    readerLoading.value = false
  }
}
</script>

<template>
  <div class="attachment-bubble">
    <div
      v-if="props.event.removed"
      class="attachment-card attachment-card-removed"
      data-testid="attachment-removed"
      :aria-label="`已刪除附件 ${filename}`"
    >
      <span class="attachment-card-icon" aria-hidden="true">刪</span>
      <span class="attachment-card-meta">
        <strong data-testid="attachment-filename">{{ filename }}</strong>
        <small data-testid="attachment-size">已刪除</small>
      </span>
    </div>
    <template v-else-if="isText && downloadUrl">
      <button
        type="button"
        class="attachment-card attachment-card-text"
        data-testid="attachment-text"
        :aria-label="`檢視文字附件 ${filename}`"
        @click="openReader"
      >
        <span class="attachment-card-icon" aria-hidden="true">文</span>
        <span class="attachment-card-meta">
          <strong data-testid="attachment-filename">{{ filename }}</strong>
          <small data-testid="attachment-size">{{ size }}</small>
        </span>
        <span class="attachment-card-download">檢視內容</span>
      </button>
      <Modal :show="readerOpen" :title="filename" test-id="attachment-reader" close-test-id="attachment-reader-close" @close="readerOpen = false">
        <p v-if="readerLoading" class="attachment-reader-status" data-testid="attachment-reader-status">讀取中…</p>
        <p v-else-if="readerError" class="attachment-reader-status attachment-reader-error" data-testid="attachment-reader-error">{{ readerError }}</p>
        <pre v-else class="attachment-reader-content" data-testid="attachment-reader-content">{{ readerContent }}</pre>
        <a class="btn btn-secondary btn-sm" :href="downloadUrl" download :data-testid="`attachment-download-${event.file_id}`">下載檔案</a>
      </Modal>
    </template>
    <template v-else-if="isImage && downloadUrl">
      <button
        type="button"
        class="attachment-thumb"
        data-testid="attachment-image"
        :aria-label="`檢視圖片附件 ${filename}`"
        @click="openLightbox"
      >
        <img :src="downloadUrl" :alt="filename" />
      </button>
      <Modal :show="lightboxOpen" :title="filename" test-id="attachment-lightbox" close-test-id="attachment-lightbox-close" @close="lightboxOpen = false">
        <div class="attachment-lightbox-img">
          <img :src="downloadUrl" :alt="filename" />
        </div>
        <a class="btn btn-secondary btn-sm" :href="downloadUrl" download :data-testid="`attachment-download-${event.file_id}`">下載檔案</a>
      </Modal>
    </template>
    <a
      v-else-if="downloadUrl"
      class="attachment-card"
      :href="downloadUrl"
      download
      :data-testid="`attachment-download-${event.file_id}`"
    >
      <span class="attachment-card-icon" aria-hidden="true">{{ isPdf ? 'PDF' : '檔' }}</span>
      <span class="attachment-card-meta">
        <strong data-testid="attachment-filename">{{ filename }}</strong>
        <small data-testid="attachment-size">{{ size }}</small>
      </span>
      <span class="attachment-card-download">{{ attachmentLabel ?? '附件' }} ↓</span>
    </a>
    <p v-else class="attachment-card attachment-card-missing" data-testid="attachment-missing">附件不可用</p>
  </div>
</template>

<style scoped>
.attachment-bubble {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.attachment-thumb {
  display: block;
  padding: 0;
  border: 1px solid var(--border, #ddd);
  border-radius: 8px;
  overflow: hidden;
  background: none;
  cursor: zoom-in;
  max-width: 240px;
}

.attachment-thumb img {
  display: block;
  max-width: 240px;
  max-height: 240px;
  object-fit: contain;
}

.attachment-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--border, #ddd);
  border-radius: 8px;
  background: var(--bg-muted, #f5f5f5);
  color: inherit;
  text-decoration: none;
  min-width: 0;
  max-width: 260px;
}

button.attachment-card {
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.attachment-card:hover {
  border-color: var(--color-border-strong);
}

.attachment-reader-content {
  max-height: 60vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--color-surface-muted);
  padding: 12px;
  border-radius: 6px;
  font-size: 0.92em;
}

.attachment-reader-status {
  opacity: 0.7;
}

.attachment-reader-error {
  color: var(--color-danger);
}

.attachment-card-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 6px;
  background: var(--accent-muted, #e8e8f0);
  font-size: 0.7em;
  font-weight: 700;
  color: var(--accent, #555);
}

.attachment-card-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.attachment-card-meta strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-card-meta small {
  opacity: 0.6;
}

.attachment-card-download {
  margin-left: auto;
  flex: none;
  font-size: 0.85em;
  opacity: 0.7;
}

.attachment-card-missing {
  color: var(--danger, #c00);
}

.attachment-card-removed {
  cursor: default;
  opacity: 0.7;
}

.attachment-card-removed:hover {
  border-color: var(--border, #ddd);
}

.attachment-lightbox-img {
  display: flex;
  justify-content: center;
  max-height: 70vh;
  overflow: auto;
}

.attachment-lightbox-img img {
  max-width: 100%;
  object-fit: contain;
}
</style>
