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
  materialCount?: number
}>()

const emit = defineEmits<{
  'open-materials': []
  'update:quotedMessage': [value: null]
  'message-sent': []
}>()

const store = inject(councilKey)!
const messageText = ref('')
const sending = ref(false)

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
      <button
        type="button"
        class="btn btn-secondary workspace-materials-button"
        data-testid="workspace-open-materials"
        aria-label="開啟案卷與證據"
        :disabled="disabled"
        @click="emit('open-materials')"
      >＋{{ props.materialCount ? `（${props.materialCount}）` : '' }}</button>
      <div class="chatroom-composer-input-wrap">
        <MentionAutocomplete
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
          @keydown.enter.exact.prevent="handleSend"
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
