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
  }
  attachmentLabel?: string
}>()

const lightboxOpen = ref(false)

const filename = computed(() => props.event.filename ?? props.event.file_id ?? '附件')
const size = computed(() => formatAttachmentSize(props.event.size ?? 0))
const downloadUrl = computed(() => {
  const fileId = props.event.file_id
  return fileId ? attachmentDownloadUrl(props.meetingId, fileId) : ''
})
const isImage = computed(() => props.event.mime_type?.startsWith('image/') ?? false)
const isPdf = computed(() => props.event.mime_type === 'application/pdf')

function openLightbox() {
  if (downloadUrl.value) lightboxOpen.value = true
}
</script>

<template>
  <div class="attachment-bubble">
    <template v-if="isImage && downloadUrl">
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

.attachment-card:hover {
  border-color: var(--accent, #888);
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
