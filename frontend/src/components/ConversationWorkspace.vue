<script setup lang="ts">
import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  activeMode,
  councilKey,
  formatDateTime,
  roleClass,
  roleColorVars,
  roleIcon,
  type CouncilRole,
} from '../composables/useCouncil'
import {
  isAttachmentEvent,
  latestWorkspaceMessageTarget,
  materialCountFor,
  materialVocabulary,
  messageClampPolicy,
  nextWorkspaceRoleFilter,
  projectMeetingWorkspace,
  seatIdToEventRoleId,
  shouldShowChatroomComposer,
  type ConversationWorkspaceProjection,
  type WorkspaceMessage,
  type WorkspaceProjectionMeeting,
  type WorkspaceRoleFilter,
  type ConversationFeedItem,
} from '../meetingWorkspace'
import { uploadAttachment } from '../api'
import { useMaterialUploads } from '../materialUploads'
import type { SceneConfig } from '../scenes'
import { modelDisplayLabel } from '../providers'
import ActionBar from './ActionBar.vue'
import AttachmentBubble from './AttachmentBubble.vue'
import ChatroomComposer from './ChatroomComposer.vue'
import CouncilStage from './CouncilStage.vue'
import MaterialsPanel from './MaterialsPanel.vue'
import Modal from './Modal.vue'
import RecordsDrawer from './RecordsDrawer.vue'
import RoleSilhouette from './RoleSilhouette.vue'

const props = defineProps<{ scene: SceneConfig }>()
const emit = defineEmits<{
  'role-click': [role: CouncilRole | 'Chairman']
}>()

const store = inject(councilKey)!
const {
  selectedMeeting,
  pendingRoles,
  fanoutCaptures,
  operationStatusText,
  currentStepProgress,
  isMeetingRunning,
  selectedModels,
  models,
  chairmanEvents,
  failedRole,
  retrySelectedStep,
  updateSelectedModel,
  assignmentUpdateError,
  loading,
} = store

const roleFilter = ref<WorkspaceRoleFilter | null>(null)
const expandedMessageIds = ref(new Set<string>())
const contextCollapsed = ref(false)
const mobileContextOpen = ref(false)
const quotedMessage = ref<{ eventId: string; preview: string } | null>(null)
const isChatroom = computed(() => shouldShowChatroomComposer(activeMode.value.category))
const materialCount = computed(() => materialCountFor(selectedMeeting.value))
const vocab = computed(() => materialVocabulary(selectedMeeting.value?.mode_id ?? ''))
const {
  uploads: uploadList,
  textDraft: textDraftRef,
  onPickedFiles,
  retryUpload,
  dismissUpload,
} = useMaterialUploads({
  meetingId: () => selectedMeeting.value?.meeting_id,
  uploadAttachment,
  openMeeting: (meetingId) => store.openMeeting(meetingId),
  openMaterialsTab: () => openMaterialsTab(),
  routeTextToCaseFiles: () => !isChatroom,
})
const uploadDisabled = computed(() => loading.value || Boolean(isMeetingRunning.value))
const latestChairMessage = computed(() => chairmanEvents.value.at(-1)?.content ?? '')
const assignmentWarnings = computed(() => {
  const participants = selectedMeeting.value?.participants ?? []
  return participants
    .filter((p) => p.model_assignment_warning)
    .map((p) => {
      const role = workspace.value?.roles.find((r) => r.roleId === p.role_id)
      const roleName = role?.name ?? p.role_id
      const warning = p.model_assignment_warning!
      if (warning.startsWith('No saved model assignment')) {
        const defaultMatch = warning.match(/using default model '([^']+)'/)
        const fallbackName = defaultMatch ? resolveModelName(defaultMatch[1]) : ''
        return fallbackName
          ? `${roleName}：未指派模型，已自動使用「${fallbackName}」。`
          : `${roleName}：未指派模型。`
      }
      const originalMatch = warning.match(/(?:Assigned|Recovered) model '([^']+)'/)
      const defaultMatch = warning.match(/using default model '([^']+)'/)
      const originalName = originalMatch ? resolveModelName(originalMatch[1]) : originalMatch?.[1] ?? ''
      const fallbackName = defaultMatch ? resolveModelName(defaultMatch[1]) : ''
      if (originalName && fallbackName) {
        return `${roleName}：模型「${originalName}」已失效，目前使用「${fallbackName}」。`
      }
      return `${roleName}：${warning}`
    })
})
const sceneLightboxOpen = ref(false)
const openModelSeatId = ref<string | null>(null)
type ContextTab = 'context' | 'records' | 'materials'
const activeContextTab = ref<ContextTab>('context')
const feedRef = ref<HTMLDivElement | null>(null)

// 快速選單「資料管理」與 .txt/.md 分流共用：切到資料頁，並依容器展開側欄
// （mobile 的 conversation 版另有 overlay，courtroom 沒有 mobileContextOpen）。
function openMaterialsTab() {
  activeContextTab.value = 'materials'
  contextCollapsed.value = false
  mobileContextOpen.value = true
}

const workspace = computed<ConversationWorkspaceProjection | null>(() => {
  const meeting = selectedMeeting.value
  if (!meeting || meeting.mode_id === 'courtroom') return null
  const projected = projectMeetingWorkspace({
    meeting: meeting as WorkspaceProjectionMeeting,
    mode: activeMode.value,
    thinkingRoleIds: pendingRoles.value,
    fanoutCaptures: fanoutCaptures.value,
  })
  return projected.family === 'conversation' ? projected : null
})
watch(() => selectedMeeting.value?.meeting_id, () => {
  roleFilter.value = null
  expandedMessageIds.value = new Set()
})

const selectedRoleId = computed(() => {
  const filter = roleFilter.value
  return filter && filter.meetingId === workspace.value?.meetingId ? filter.roleId : null
})
const feedItems = computed<ConversationFeedItem[]>(() => {
  const items = workspace.value?.feedItems ?? []
  if (!selectedRoleId.value) return items
  const roleId = seatIdToEventRoleId(selectedRoleId.value)
  return items.flatMap<ConversationFeedItem>((item) => {
    if (item.kind === 'message') return item.message.roleId === roleId ? [item] : []
    if (!item.round.expectedRoleIds.includes(roleId)) return []
    return [{
      kind: 'fanout-round' as const,
      round: {
        ...item.round,
        expectedRoleIds: [roleId],
        members: item.round.members.filter((message) => message.roleId === roleId),
        roleStates: item.round.roleStates.filter((state) => state.roleId === roleId),
        respondedCount: item.round.members.filter((message) => message.roleId === roleId && message.kind !== 'failed').length,
        failedCount: item.round.members.filter((message) => message.roleId === roleId && message.kind === 'failed').length,
      },
    }]
  })
})
const fanoutRounds = computed(() => feedItems.value
  .filter((item): item is Extract<ConversationFeedItem, { kind: 'fanout-round' }> => item.kind === 'fanout-round')
  .map((item) => item.round))
const renderFeedItems = computed(() => feedItems.value.map((item, index) => {
  if (item.kind === 'fanout-round') return item
  const previous = feedItems.value[index - 1]
  const next = feedItems.value[index + 1]
  const previousMessage = previous?.kind === 'message' ? previous.message : undefined
  const nextMessage = next?.kind === 'message' ? next.message : undefined
  const sameSpeaker = (left?: WorkspaceMessage, right?: WorkspaceMessage) =>
    Boolean(left && right && left.kind === right.kind && left.roleId === right.roleId)
  return {
    ...item,
    isOwn: item.message.kind === 'human',
    startsRun: !sameSpeaker(previousMessage, item.message),
    endsRun: !sameSpeaker(item.message, nextMessage),
  }
}))
const messages = computed(() => {
  if (!workspace.value) return []
  const seen = new Set<string>()
  const chronological = workspace.value.messages.filter((message) => {
    if (seen.has(message.id)) return false
    seen.add(message.id)
    return true
  })
  if (!selectedRoleId.value) return chronological
  return chronological.filter((message) => message.roleId === seatIdToEventRoleId(selectedRoleId.value!))
})

// Messenger-style grouping (the Human Owner asked for LINE's model): the Chairman's
// own messages sit on the right with no avatar or name — you already know who you
// are — and everyone else sits on the left, identified once per run. Repeating the
// avatar, name and timestamp on every bubble is what made speakers hard to tell
// apart in the first place.
const allMessages = computed(() => {
  if (!workspace.value) return []
  const seen = new Set<string>()
  return workspace.value.messages.filter((message) => {
    if (seen.has(message.id)) return false
    seen.add(message.id)
    return true
  })
})

function isNearBottom(el: HTMLDivElement, threshold = 80): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < threshold
}

function scrollToBottom() {
  const el = feedRef.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(
  () => allMessages.value.length,
  (newLen, oldLen) => {
    if (newLen > oldLen && feedRef.value) {
      // Snapshot scroll position *before* the DOM re-renders with the new
      // message.  After nextTick the feed has already grown, so measuring
      // then would see a large gap and isNearBottom would always fail.
      const nearBottom = isNearBottom(feedRef.value)
      if (nearBottom) {
        nextTick(() => { scrollToBottom() })
      }
    }
  },
)

// A chat opens on its newest message, not its oldest. Without this the feed sat at
// scrollTop 0 showing the start of the transcript, and anything the Chairman sent
// landed off-screen below — the composer cleared, nothing visibly happened, and it
// read as "the message didn't send".
onMounted(() => { nextTick(() => { scrollToBottom() }) })
watch(() => selectedMeeting.value?.meeting_id, () => {
  nextTick(() => { scrollToBottom() })
})

// Sending is an explicit act: always jump to your own message, wherever the feed was.
function onOwnMessageSent() {
  quotedMessage.value = null
  nextTick(() => { scrollToBottom() })
}

function roleState(roleId: string) {
  return workspace.value?.roles.find((role) => role.roleId === roleId)?.state ?? 'waiting'
}

function roleStateLabel(state: ReturnType<typeof roleState>): string {
  if (state === 'thinking') return '思考中'
  if (state === 'completed') return '已完成'
  if (state === 'failed') return '失敗'
  return '等待中'
}

function roleModelLabel(roleId: string): string {
  const modelId = selectedModels.value[roleId]
  const model = models.value.find((candidate) => candidate.id === modelId)
  return model ? modelDisplayLabel(model) : modelId || '未選模型'
}

function resolveModelName(modelId: string): string {
  const model = models.value.find((m) => m.id === modelId)
  return model ? modelDisplayLabel(model) : modelId
}

function toggleMessage(messageId: string) {
  const next = new Set(expandedMessageIds.value)
  if (next.has(messageId)) next.delete(messageId)
  else next.add(messageId)
  expandedMessageIds.value = next
}

function isExpanded(message: WorkspaceMessage): boolean {
  return expandedMessageIds.value.has(message.id)
}

async function selectRole(roleId?: string) {
  const currentWorkspace = workspace.value
  if (!currentWorkspace) return
  roleFilter.value = nextWorkspaceRoleFilter(roleFilter.value, currentWorkspace.meetingId, roleId)
  await nextTick()
  const target = roleFilter.value
    ? latestWorkspaceMessageTarget(currentWorkspace, roleFilter.value)
    : allMessages.value.at(-1)?.id ?? null
  if (target) document.getElementById(`workspace-message-${target}`)?.scrollIntoView({ block: 'nearest' })
}

function toggleModelSelect(roleId: string) {
  openModelSeatId.value = openModelSeatId.value === roleId ? null : roleId
}

async function switchSeatModel(roleId: CouncilRole, modelId: string) {
  await updateSelectedModel(roleId, modelId)
  openModelSeatId.value = null
}

function onDocumentClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.workspace-role-model-select') && !target.closest('.workspace-role-model')) {
    openModelSeatId.value = null
  }
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))

function messageTime(message: WorkspaceMessage): string {
  return message.createdAt ? formatDateTime(message.createdAt) : ''
}

function failedEventFor(roleId: string) {
  return [...(selectedMeeting.value?.events ?? [])]
    .reverse()
    .find((event) => event.role === roleId && event.status === 'failed')
}

async function retryRole(roleId: string) {
  const event = failedEventFor(roleId)
  if (event) await retrySelectedStep(event)
}
</script>

<template>
  <section
    v-if="workspace && selectedMeeting"
    class="conversation-workspace"
    :class="{ 'context-collapsed': contextCollapsed }"
    data-testid="conversation-workspace"
  >
    <nav class="workspace-role-rail" data-testid="workspace-role-rail" aria-label="與會角色">
      <div class="workspace-role-seats">
      <!-- The seat is a plain container; the primary action is a real <button>, so the
           ℹ control and the model control sit beside it rather than nested inside an
           interactive element. Keyboard activation comes from the button itself. -->
      <div
        class="workspace-role-seat workspace-role-chairman"
        :class="{ active: selectedRoleId === 'Chairman' }"
      >
        <button
          type="button"
          class="workspace-role-button"
          data-testid="role-seat-chairman"
          data-status="chairman"
          aria-label="主席"
          :aria-pressed="selectedRoleId === 'Chairman'"
          @click="selectRole('Chairman')"
        >
          <span class="workspace-role-avatar"><RoleSilhouette color="currentColor" :size="26" /></span>
          <span class="workspace-role-name">主席</span>
          <span v-if="latestChairMessage" class="visually-hidden">{{ latestChairMessage }}</span>
        </button>
        <button
          type="button"
          class="workspace-role-info-btn"
          data-testid="role-seat-chairman-info"
          aria-label="主席詳情"
          @click="$emit('role-click', 'Chairman')"
        >ℹ</button>
      </div>
      <div
        v-for="role in workspace.roles"
        :key="role.roleId"
        class="workspace-role-seat"
        :class="[roleClass(role.roleId), { active: selectedRoleId === role.roleId }]"
        :style="roleColorVars(role.roleId)"
      >
        <button
          type="button"
          class="workspace-role-button"
          :class="roleClass(role.roleId)"
          :data-testid="`role-seat-${role.roleId.toLowerCase()}`"
          :data-status="role.state"
          :aria-label="`${role.name}，${roleStateLabel(role.state)}`"
          :aria-pressed="selectedRoleId === role.roleId"
          @click="selectRole(role.roleId)"
        >
          <span class="workspace-role-avatar">
            <img v-if="roleIcon(role.roleId)" :src="roleIcon(role.roleId)" :alt="role.name" />
            <RoleSilhouette v-else :color="'var(--role-color)'" :size="26" />
            <i v-if="role.state === 'thinking'" class="workspace-thinking-pulse" aria-hidden="true"></i>
          </span>
          <span class="workspace-role-name">{{ role.name }}</span>
          <span class="workspace-role-state">{{ roleStateLabel(role.state) }}</span>
        </button>
        <button v-if="openModelSeatId !== role.roleId" type="button" class="workspace-role-model"
          :title="isMeetingRunning ? '會議執行中無法更換模型' : `目前模型：${roleModelLabel(role.roleId)}（點擊更換）`"
          :aria-label="`更換${role.name}的模型，目前為 ${roleModelLabel(role.roleId)}`"
          :data-testid="`seat-model-label-${role.roleId.toLowerCase()}`"
          @click="toggleModelSelect(role.roleId)"
        >
          <span class="workspace-role-model-text">{{ roleModelLabel(role.roleId) }}</span>
          <svg class="workspace-role-model-caret" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        <select v-else class="workspace-role-model-select"
          :data-testid="`seat-model-select-${role.roleId.toLowerCase()}`"
          :value="selectedModels[role.roleId]"
          :disabled="isMeetingRunning"
          @change="switchSeatModel(role.roleId, ($event.target as HTMLSelectElement).value)"
          @click.stop
        >
          <option v-for="model in models" :key="model.id" :value="model.id">{{ modelDisplayLabel(model) }}</option>
        </select>
        <button
          type="button"
          class="workspace-role-info-btn"
          :data-testid="`role-seat-${role.roleId.toLowerCase()}-info`"
          :aria-label="`${role.name}詳情`"
          @click.stop="$emit('role-click', role.roleId)"
        >ℹ</button>
      </div>
      </div>
      <div v-if="assignmentWarnings.length" class="assignment-fallback-warning" data-testid="assignment-fallback-warning">
        <p v-for="(warning, idx) in assignmentWarnings" :key="idx">{{ warning }}</p>
      </div>
      <div v-if="assignmentUpdateError" class="assignment-update-error" role="alert" data-testid="assignment-update-error">
        {{ assignmentUpdateError }}
      </div>
    </nav>

    <section class="workspace-conversation-column">
      <header class="workspace-conversation-header">
        <div>
          <span class="workspace-eyebrow">{{ activeMode.category === 'chatroom' ? '聊天室' : activeMode.category === 'parallel' ? '平行討論' : '依序討論' }}</span>
          <h2>{{ selectedMeeting.title }}</h2>
        </div>
        <button
          v-if="selectedRoleId"
          type="button"
          class="btn btn-ghost btn-sm"
          data-testid="workspace-clear-role-filter"
          @click="selectRole()"
        >顯示全部發言</button>
        <button
          type="button"
          class="btn btn-secondary btn-sm workspace-mobile-context-button"
          aria-label="開啟會議脈絡"
          @click="mobileContextOpen = true"
        >會議脈絡</button>
      </header>

      <div ref="feedRef" class="workspace-message-feed" data-testid="workspace-message-feed" aria-live="polite">
        <p v-if="!feedItems.length" class="workspace-empty-feed">
          {{ selectedRoleId ? '這個角色還沒有發言。' : '尚未有會議發言；可先記錄主席補充，或啟動第一次審議。' }}
        </p>
        <template v-for="item in renderFeedItems" :key="item.kind === 'message' ? item.message.id : item.round.id">
        <article
          v-if="item.kind === 'message'"
          :id="`workspace-message-${item.message.id}`"
          class="workspace-message"
          :class="[
            `workspace-message-${item.message.kind}`,
            {
              'workspace-message-human': item.isOwn,
              'workspace-message-own': item.isOwn,
              'workspace-message-run-start': item.startsRun,
              'workspace-message-run-end': item.endsRun,
            },
          ]"
          :style="item.message.kind === 'ai' || item.message.kind === 'synthesizer' ? roleColorVars(item.message.roleId) : undefined"
          data-testid="workspace-message"
          :data-role="item.message.roleId"
        >
          <!-- Own messages need no identification; others are labelled once per run. -->
          <span
            v-if="!item.isOwn"
            class="workspace-message-avatar"
            :class="{ 'is-placeholder': !item.startsRun }"
            data-testid="workspace-message-avatar"
            :aria-hidden="!item.startsRun"
          >
            <template v-if="item.startsRun">
              <img v-if="roleIcon(item.message.roleId)" :src="roleIcon(item.message.roleId)" :alt="item.message.roleName" />
              <RoleSilhouette v-else :color="item.message.kind === 'ai' || item.message.kind === 'synthesizer' ? 'var(--role-color)' : 'currentColor'" :size="20" />
            </template>
          </span>
          <header v-if="!item.isOwn && item.startsRun">
            <strong>{{ item.message.roleName }}</strong>
            <span v-if="item.message.kind === 'synthesizer'" class="workspace-message-badge">彙整</span>
          </header>
          <time
            v-if="item.message.createdAt && item.endsRun"
            class="workspace-message-time"
            :datetime="item.message.createdAt"
          >{{ messageTime(item.message) }}</time>
          <AttachmentBubble
            v-if="isAttachmentEvent(item.message.event)"
            :meeting-id="selectedMeeting.meeting_id"
            :event="item.message.event"
          />
          <template v-else>
            <p
              class="workspace-message-content"
              :class="{ collapsed: messageClampPolicy(item.message.content).collapsible && !isExpanded(item.message) }"
            >{{ item.message.content || (item.message.kind === 'failed' ? '本次回應失敗。' : '（沒有文字內容）') }}</p>
            <button
              v-if="messageClampPolicy(item.message.content).collapsible"
              type="button"
              class="workspace-message-toggle"
              :aria-expanded="isExpanded(item.message)"
              :aria-controls="`workspace-message-${item.message.id}`"
              :data-testid="`workspace-message-toggle-${item.message.id}`"
              @click="toggleMessage(item.message.id)"
            >{{ isExpanded(item.message) ? '收合長文' : '展開完整發言' }}</button>
          </template>
          <button
            v-if="isChatroom && item.message.kind !== 'human' && item.message.kind !== 'system'"
            type="button"
            class="btn btn-ghost btn-sm workspace-quote-button"
            data-testid="quote-message-button"
            @click="quotedMessage = { eventId: item.message.id, preview: item.message.content.slice(0, 60) }"
          >引用</button>
        </article>
        <section
          v-else-if="item.kind === 'fanout-round'"
          :id="item.round.id"
          class="fanout-round"
          data-testid="fanout-round"
        >
          <header class="fanout-round-header" data-testid="fanout-round-header">
            <strong>@all 回應 {{ item.round.respondedCount }}/{{ item.round.expectedRoleIds.length }}</strong>
            <span v-if="item.round.terminal === 'pending'">等待回應</span>
            <span v-else-if="item.round.terminal === 'completed'">全部完成</span>
            <span v-else-if="item.round.terminal === 'unknown'">部分完成（未回應角色未知）</span>
            <span v-else>部分完成（含失敗回應）</span>
          </header>
          <article
            v-for="message in item.round.members"
            :id="`workspace-message-${message.id}`"
            :key="message.id"
            class="workspace-message workspace-message-fanout-member"
            :class="`workspace-message-${message.kind}`"
            :style="message.kind === 'ai' || message.kind === 'synthesizer' ? roleColorVars(message.roleId) : undefined"
            data-testid="workspace-message"
            :data-role="message.roleId"
          >
            <span class="workspace-message-avatar" data-testid="workspace-message-avatar">
              <img v-if="roleIcon(message.roleId)" :src="roleIcon(message.roleId)" :alt="message.roleName" />
              <RoleSilhouette v-else :color="message.kind === 'ai' || message.kind === 'synthesizer' ? 'var(--role-color)' : 'currentColor'" :size="20" />
            </span>
            <header><strong>{{ message.roleName }}</strong><span v-if="message.kind === 'synthesizer'" class="workspace-message-badge">彙整</span></header>
            <time v-if="message.createdAt" class="workspace-message-time" :datetime="message.createdAt">{{ messageTime(message) }}</time>
            <AttachmentBubble
              v-if="isAttachmentEvent(message.event)"
              :meeting-id="selectedMeeting.meeting_id"
              :event="message.event"
            />
            <template v-else>
              <p class="workspace-message-content" :class="{ collapsed: messageClampPolicy(message.content).collapsible && !isExpanded(message) }">{{ message.content || (message.kind === 'failed' ? '本次回應失敗。' : '（沒有文字內容）') }}</p>
              <button
                v-if="messageClampPolicy(message.content).collapsible"
                type="button"
                class="workspace-message-toggle"
                :aria-expanded="isExpanded(message)"
                :aria-controls="`workspace-message-${message.id}`"
                :data-testid="`workspace-message-toggle-${message.id}`"
                @click="toggleMessage(message.id)"
              >{{ isExpanded(message) ? '收合完整發言' : '展開完整發言' }}</button>
            </template>
            <button
              v-if="isChatroom && message.kind !== 'human' && message.kind !== 'system'"
              type="button"
              class="btn btn-ghost btn-sm workspace-quote-button"
              data-testid="quote-message-button"
              @click="quotedMessage = { eventId: message.id, preview: message.content.slice(0, 60) }"
            >引用</button>
          </article>
          <article
            v-for="state in item.round.roleStates.filter((candidate) => candidate.state === 'pending')"
            :key="`fanout-thinking-${item.round.id}-${state.roleId}`"
            class="workspace-message workspace-message-thinking"
            :style="roleColorVars(state.roleId)"
            data-testid="fanout-round-placeholder"
          >
            <header><strong>{{ state.name }}</strong><span>正在思考</span></header>
            <div class="workspace-thinking-dots" aria-label="正在思考"><i></i><i></i><i></i></div>
          </article>
        </section>
        </template>
        <article
          v-for="role in workspace.roles.filter((candidate) => candidate.state === 'thinking' && !fanoutRounds.some((round) => round.roleStates.some((state) => state.roleId === candidate.roleId && state.state === 'pending')))"
          :key="`thinking-${role.roleId}`"
          class="workspace-message workspace-message-thinking"
          :style="roleColorVars(role.roleId)"
          data-testid="workspace-thinking-message"
        >
          <header><strong>{{ role.name }}</strong><span>正在思考</span></header>
          <div class="workspace-thinking-dots" aria-label="正在思考"><i></i><i></i><i></i></div>
        </article>
      </div>

      <ChatroomComposer
        v-if="isChatroom"
        :meeting-id="selectedMeeting.meeting_id"
        :participants="selectedMeeting.participants"
        :upload-disabled="uploadDisabled"
        v-model:quoted-message="quotedMessage"
        @pick-files="onPickedFiles"
        @message-sent="onOwnMessageSent"
      />
      <ActionBar
        v-else
        embedded
        @pick-files="onPickedFiles"
        @manage-materials="openMaterialsTab"
      />
    </section>

    <aside
      class="workspace-context-panel"
      :class="{ collapsed: contextCollapsed, 'mobile-open': mobileContextOpen }"
      data-testid="workspace-context-panel"
    >
      <header>
        <div class="workspace-context-tabs">
          <button type="button" class="workspace-context-tab" :class="{ active: activeContextTab === 'context' }" data-testid="context-tab-context" @click="activeContextTab = 'context'">脈絡</button>
          <button type="button" class="workspace-context-tab" :class="{ active: activeContextTab === 'records' }" data-testid="context-tab-records" @click="activeContextTab = 'records'">紀錄</button>
          <button type="button" class="workspace-context-tab" :class="{ active: activeContextTab === 'materials' }" data-testid="context-tab-materials" @click="activeContextTab = 'materials'">{{ vocab.tabLabel }}（{{ materialCount }}）</button>
        </div>
        <button
          type="button"
          class="btn btn-ghost btn-icon"
          :aria-label="contextCollapsed ? '展開會議脈絡' : '收合會議脈絡'"
          :aria-expanded="!contextCollapsed"
          data-testid="workspace-context-toggle"
          @click="mobileContextOpen ? mobileContextOpen = false : contextCollapsed = !contextCollapsed"
        >{{ contextCollapsed ? '‹' : '›' }}</button>
      </header>
      <div v-if="!contextCollapsed" class="workspace-context-body">
        <template v-if="activeContextTab === 'context'">
        <section v-if="isChatroom" class="workspace-mode-badge" data-testid="workspace-mode-badge">
          <span class="badge badge-chatroom">聊天室</span>
        </section>
        <section v-if="selectedMeeting.goal">
          <span>AI 最終目標</span>
          <p>{{ selectedMeeting.goal }}</p>
        </section>
        <section class="workspace-context-status" data-testid="workspace-operation-status">
          <span>目前狀態</span>
          <strong>{{ operationStatusText }}</strong>
          <small v-if="currentStepProgress">第 {{ currentStepProgress.index }}／{{ currentStepProgress.total }} 步 · {{ currentStepProgress.label }}</small>
        </section>
        <section v-if="workspace.parallel" data-testid="workspace-parallel-progress">
          <span>平行回應</span>
          <strong>{{ workspace.parallel.completed }}／{{ workspace.parallel.total }} 位完成</strong>
          <small>彙整：{{ workspace.parallel.synthesis === 'completed' ? '已完成' : workspace.parallel.synthesis === 'running' ? '進行中' : workspace.parallel.synthesis === 'blocked' ? '等待失敗成員處理' : workspace.parallel.synthesis === 'failed' ? '失敗' : '等待全員' }}</small>
        </section>
        <section v-if="failedRole" class="workspace-context-failure" data-testid="workspace-failed-action">
          <span>回應需要處理</span>
          <p>{{ workspace.roles.find((role) => role.roleId === failedRole)?.name || failedRole }}的回應失敗；重試後會從失敗步驟繼續。</p>
          <button
            type="button"
            class="btn btn-primary btn-sm"
            :data-testid="`workspace-retry-role-${failedRole.toLowerCase()}`"
            :disabled="isMeetingRunning || !failedEventFor(failedRole)"
            @click="retryRole(failedRole)"
          >{{ isMeetingRunning ? '重試中…' : '重試失敗步驟' }}</button>
        </section>
        <details class="workspace-scene-details" data-testid="workspace-scene-details">
          <summary>角色場景（次要狀態視圖）</summary>
          <CouncilStage
            :scene="props.scene"
            seat-test-id-prefix="scene-role-seat"
            model-test-id-prefix="scene-seat-model-label"
            @seat-click="$emit('role-click', $event)"
            @scene-click="sceneLightboxOpen = true"
          />
        </details>
        <p v-if="isMeetingRunning" class="workspace-live-note">完成的回應會立即出現在時間序中，不必等待整輪結束。</p>
        </template>
        <div v-else-if="activeContextTab === 'records'" data-testid="context-records-section">
          <RecordsDrawer :show="true" inline />
        </div>
        <MaterialsPanel
          v-show="activeContextTab === 'materials'"
          :active="activeContextTab === 'materials'"
          :meeting-id="selectedMeeting.meeting_id"
          :uploads="uploadList"
          :text-draft="textDraftRef"
          :simple="isChatroom"
          @retry-upload="retryUpload"
          @dismiss-upload="dismissUpload"
          @text-draft-consumed="textDraftRef = null"
        />
      </div>
    </aside>
  </section>

  <section v-else class="workspace-no-meeting" data-testid="workspace-no-meeting">
    <h2>尚未選擇會議</h2>
    <p>從右上角「新增會議」建立，或到「歷史會議」選擇會議。</p>
  </section>

  <Modal :show="sceneLightboxOpen" title="場景全覽" test-id="scene-lightbox-modal" @close="sceneLightboxOpen = false">
    <div class="scene-lightbox">
      <CouncilStage
        :scene="props.scene"
        seat-test-id-prefix="lb-role-seat"
        model-test-id-prefix="lb-seat-model-label"
      />
    </div>
  </Modal>
</template>
