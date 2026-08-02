<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import type { ChairmanParticipant } from '../chairmanActions'
import { parseAndSendChatMessage } from '../composables/useChatroomComposer'
import { councilKey } from '../composables/useCouncil'
import MentionAutocomplete from './MentionAutocomplete.vue'

const props = defineProps<{
  meetingId: string
  participants: ChairmanParticipant[]
  quotedMessage: { eventId: string; preview: string } | null
  disabled?: boolean
  uploadDisabled?: boolean
}>()

const emit = defineEmits<{
  'pick-files': [files: File[]]
  'update:quotedMessage': [value: null]
  'message-sent': []
}>()

const store = inject(councilKey)!
const messageText = ref('')
const sending = ref(false)
// LINE 風格「＋」直接開原生檔案選取器；常駐隱藏 input 可被 e2e 直接
// setInputFiles。上傳鎖（uploadDisabled）由父層計算（loading || running）。
const attachmentInput = ref<HTMLInputElement | null>(null)

function onAttachmentClick() {
  if (props.uploadDisabled) return
  attachmentInput.value?.click()
}

function onAttachmentSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (files.length) emit('pick-files', files)
}
// While an IME is composing, Enter belongs to the input method — it confirms the
// candidate. Sending on it fired before the composed text was committed, so the
// Chinese was lost and only the text typed before it went out. `isComposing` alone
// is not reliable across IMEs, so the composition events are tracked as well. Blur
// clears the flag too: if compositionend ever failed to fire, a stuck flag would leave
// Enter unable to send at all, which is worse than the bug being fixed here.
const composing = ref(false)

const mentionMenu = ref<InstanceType<typeof MentionAutocomplete> | null>(null)
const mentionExpanded = computed(() => Boolean(mentionMenu.value?.isExpanded))
const mentionMenuId = computed(() => (mentionExpanded.value ? mentionMenu.value?.menuId : undefined))
const mentionActiveOptionId = computed(() => mentionMenu.value?.activeOptionId)

function onTextareaKeydown(event: KeyboardEvent) {
  // The input method comes first and gets every key: Enter confirms a candidate, the
  // arrows move through them. Nothing here may act until composition is over.
  if (composing.value || event.isComposing) return

  // The mention menu owns the arrows, Enter, Tab and Escape while it is open, and
  // reports whether it consumed the key so Enter is not also read as send.
  if (mentionMenu.value?.handleKeyDown(event)) return

  if (event.key !== 'Enter') return
  if (event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return
  event.preventDefault()
  void handleSend()
}

const canSend = computed(() => {
  if (props.disabled || sending.value) return false
  return !!messageText.value.trim()
})

async function handleSend() {
  if (!canSend.value) return
  sending.value = true
  try {
    const boundary = {
      sendChatMessage: store.sendChatroomMessage,
      sendChatMention: store.sendChatroomMention,
    }
    const result = await parseAndSendChatMessage({
      content: messageText.value,
      meetingId: props.meetingId,
      participants: props.participants,
      quotedEventId: props.quotedMessage?.eventId ?? null,
      boundary,
    })
    if (result.ok) {
      messageText.value = ''
      if (props.quotedMessage) emit('update:quotedMessage', null)
      emit('message-sent')
    }
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <div class="chatroom-composer" data-testid="chatroom-composer">
    <div v-if="quotedMessage" class="chatroom-composer-quote" data-testid="quote-indicator">
      <span class="chatroom-composer-quote-preview">{{ quotedMessage.preview }}</span>
      <button
        type="button"
        class="chatroom-composer-quote-dismiss"
        data-testid="dismiss-quote-button"
        aria-label="取消引用"
        @click="emit('update:quotedMessage', null)"
      >×</button>
    </div>
    <div class="chatroom-composer-row">
      <div class="chatroom-composer-attachment">
        <button
          type="button"
          class="btn btn-secondary workspace-materials-button"
          data-testid="chatroom-attachment-button"
          aria-label="上傳附件"
          :disabled="uploadDisabled"
          @click="onAttachmentClick"
        >＋</button>
        <input
          ref="attachmentInput"
          type="file"
          class="visually-hidden"
          data-testid="attachment-upload-input"
          multiple
          :disabled="uploadDisabled"
          @change="onAttachmentSelected"
        />
      </div>
      <div class="chatroom-composer-input-wrap">
        <MentionAutocomplete
          ref="mentionMenu"
          v-model="messageText"
          :participants="participants"
          mode-category="chatroom"
          :disabled="disabled"
        />
        <textarea
          v-model="messageText"
          class="chatroom-composer-input"
          data-testid="chat-message-input"
          aria-label="聊天訊息"
          placeholder="輸入訊息…"
          :disabled="disabled"
          rows="1"
          aria-autocomplete="list"
          :aria-expanded="mentionExpanded"
          :aria-controls="mentionMenuId"
          :aria-activedescendant="mentionActiveOptionId"
          @compositionstart="composing = true"
          @compositionend="composing = false"
          @blur="composing = false"
          @keydown="onTextareaKeydown"
        />
      </div>
      <button
        type="button"
        class="btn btn-primary"
        data-testid="send-chat-message-button"
        :disabled="!canSend"
        @click="handleSend"
      >
        送出
      </button>
    </div>
  </div>
</template>

<style scoped>
.chatroom-composer {
  border-top: 1px solid var(--border, #ddd);
  padding: 8px 12px;
}

.chatroom-composer-quote {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  margin-bottom: 6px;
  background: var(--bg-muted, #f5f5f5);
  border-radius: 4px;
  font-size: 0.85em;
}

.chatroom-composer-quote-preview {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.7;
}

.chatroom-composer-quote-dismiss {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1.1em;
  padding: 0 4px;
  opacity: 0.5;
}

.chatroom-composer-quote-dismiss:hover {
  opacity: 1;
}

.chatroom-composer-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.chatroom-composer-attachment {
  flex: none;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.chatroom-composer-input-wrap {
  flex: 1;
  position: relative;
}

.chatroom-composer-input {
  width: 100%;
  min-height: 36px;
  padding: 6px 8px;
  border: 1px solid var(--border, #ccc);
  border-radius: 4px;
  resize: none;
  font-family: inherit;
  font-size: inherit;
}
</style>
