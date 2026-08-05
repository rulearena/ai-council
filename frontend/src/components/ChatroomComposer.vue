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
// is not reliable across IMEs, so the composition events are tracked as well. Keep the
// flag through blur: clicking Send blurs the textarea before the button click, but
// composition is still active and must block the send.
const composing = ref(false)
// A pointer click can end composition before its click event is delivered. Remember
// the state at pointerdown so that click cannot send or clear that still-visible draft.
const sendClickStartedDuringComposition = ref(false)
const sendPointerId = ref<number | null>(null)

function resetSendPointerGuard() {
  sendClickStartedDuringComposition.value = false
  sendPointerId.value = null
}

function onSendPointerDown(event: PointerEvent) {
  // Every pointerdown starts a new possible click. Reassigning also clears a stale
  // guard when a previous pointer ended without click or the button was disabled.
  sendClickStartedDuringComposition.value = composing.value
  sendPointerId.value = event.pointerId
  if (!composing.value) return
  // Keep the textarea focused where the browser can, avoiding a blur-driven IME
  // transition before the guarded click is handled.
  event.preventDefault()
}

function onSendPointerCancel(event: PointerEvent) {
  // A cancelled pointer has no click event that could consume this one-shot guard.
  if (sendPointerId.value === event.pointerId) resetSendPointerGuard()
}

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
  if (composing.value || !canSend.value) return
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

function onSendClick(event: MouseEvent) {
  const pointerEvent = event as MouseEvent & { pointerId?: number; pointerType?: string }
  const pointerClickId =
    pointerEvent.detail > 0 && pointerEvent.pointerType && pointerEvent.pointerId !== undefined
      ? pointerEvent.pointerId
      : null
  const isGuardedPointerClick =
    sendClickStartedDuringComposition.value && pointerClickId === sendPointerId.value
  resetSendPointerGuard()
  if (isGuardedPointerClick) return
  void handleSend()
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
          @keydown="onTextareaKeydown"
        />
      </div>
      <button
        type="button"
        class="btn btn-primary"
        data-testid="send-chat-message-button"
        :disabled="!canSend"
        @pointerdown="onSendPointerDown"
        @pointercancel="onSendPointerCancel"
        @click="onSendClick"
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
  min-width: 0;
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface-muted);
  color: var(--color-text);
  border-radius: 4px;
  font-size: 0.85em;
}

.chatroom-composer-quote-preview {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chatroom-composer-quote-dismiss {
  background: none;
  border: none;
  color: var(--color-text);
  cursor: pointer;
  font-size: 1.1em;
  padding: 0 4px;
}

.chatroom-composer-quote-dismiss:hover {
  color: var(--color-text-secondary);
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
