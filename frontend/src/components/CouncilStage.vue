<script setup lang="ts">
import { computed, inject } from 'vue'
import {
  activeMode,
  activeModeRoles,
  councilKey,
  councilRoles,
  roleClass,
  roleColor,
  roleColorVars,
  roleIcon,
  type CouncilRole,
} from '../composables/useCouncil'
import RoleSilhouette from './RoleSilhouette.vue'
import { resolveSceneSeats, type SceneConfig, type SeatRole, type SeatRosterEntry } from '../scenes'
import { modelDisplayLabel } from '../providers'
import { roleDisplayName } from '../presentation'

const props = withDefaults(defineProps<{
  scene: SceneConfig
  seatTestIdPrefix?: string
  modelTestIdPrefix?: string
}>(), {
  seatTestIdPrefix: 'role-seat',
  modelTestIdPrefix: 'seat-model-label',
})
defineEmits<{ 'seat-click': [role: CouncilRole | 'Chairman']; 'scene-click': [] }>()

const store = inject(councilKey)!
const { selectedMeeting, pendingRoles, roleSeatStatus, chairmanSpeaking, chairmanEvents, selectedModels, models } = store
const participantPresentation = computed(() => selectedMeeting.value?.participants ?? [])

function displayRole(role: SeatRole): string {
  return role === 'Chairman'
    ? '主席'
    : roleDisplayName(activeMode.value, participantPresentation.value, role)
}

function fullModelLabel(role: SeatRole): string {
  const modelId = selectedModels.value[role]
  if (!modelId) return '未選模型'
  const model = models.value.find((candidate) => candidate.id === modelId)
  return model ? modelDisplayLabel(model) : modelId
}

function modelLabelText(role: SeatRole): string {
  return fullModelLabel(role)
}

function modelLabelTitle(role: SeatRole): string {
  return fullModelLabel(role)
}

// Chairman first (a fixed seat, not a mode role) then every AI role in the active
// mode's roster - replaces the old hardcoded ['Chairman', 'Blue', 'Red', 'Judge']
// literal, so a mode with a different roster renders however many seats it has.
const seatRoles = computed<SeatRole[]>(() => ['Chairman', ...councilRoles.value])

const roster = computed<SeatRosterEntry[]>(() => [
  { id: 'Chairman', kind: 'chair' },
  ...activeModeRoles.value.map((role) => ({ id: role.id, kind: role.kind })),
])

// Resolves the scene's slot groups (adjudicator/chair/podium[]/ring[]) against the
// current roster - e.g. Judge (kind: 'adjudicator') always lands on scene.seats.adjudicator
// regardless of which scene is active, reproducing each scene's original hand-tuned
// coordinates exactly (see scenes.ts's resolveSceneSeats + each SceneConfig's seats).
const seatPositions = computed(() => resolveSceneSeats(props.scene, roster.value))

function seatStyle(role: SeatRole) {
  const seat = seatPositions.value[role]
  return {
    left: `${seat.x}%`,
    top: `${seat.y}%`,
    '--seat-scale': String(seat.scale ?? 1),
    ...(role === 'Chairman' ? {} : roleColorVars(role)),
  }
}

function seatStatus(role: SeatRole): 'waiting' | 'thinking' | 'completed' | 'failed' | 'chairman' {
  if (role === 'Chairman') return 'chairman'
  return roleSeatStatus(role as CouncilRole)
}

function isQueued(role: SeatRole): boolean {
  return role !== 'Chairman' && pendingRoles.value.includes(role as CouncilRole) && seatStatus(role) === 'waiting'
}

// A seat with a scene-specific portrait renders the full-body illustration and is
// bottom-anchored (the (x, y) coordinate is the character's foot position - see
// .seat-anchor-bottom). A seat without one keeps the small circular avatar,
// center-anchored, exactly like the Phase A placeholder scene.
function portraitSrc(role: SeatRole): string | undefined {
  return props.scene.portraits?.[role]
}

function hasPortrait(role: SeatRole): boolean {
  return portraitSrc(role) !== undefined
}

const sceneStyle = computed(() => ({
  ...(props.scene.background ? { backgroundImage: `url(${props.scene.background})` } : {}),
  // Set as a custom property, not `aspectRatio` directly - the ≤640px breakpoint resets
  // aspect-ratio to `auto` in the stylesheet (see .stage-scene's media query), and an
  // inline style always wins over that regardless of specificity. Routing it through
  // `var(--scene-aspect-ratio, 4 / 3)` in the desktop rule keeps that override working.
  ...(props.scene.aspectRatio ? { '--scene-aspect-ratio': String(props.scene.aspectRatio) } : {}),
}))

const topicStyle = computed(() => {
  const { x, y } = props.scene.topicCard ?? { x: 50, y: 50 }
  return { left: `${x}%`, top: `${y}%` }
})

const latestChairMessage = computed(() => chairmanEvents.value.at(-1)?.content ?? '')
</script>

<template>
  <section class="council-stage" data-testid="council-stage">
    <div
      class="stage-scene"
      :class="{ 'stage-scene-placeholder': !scene.background }"
      :style="sceneStyle"
      :data-scene="scene.id"
      data-testid="scene-enlarge-trigger"
      @click="$emit('scene-click')"
    >
      <div class="stage-table" :style="topicStyle">
        <span class="stage-table-topic">{{ selectedMeeting?.title ?? '尚未選擇會議' }}</span>
        <span v-if="!selectedMeeting" class="stage-table-hint">從右上角「新增會議」建立，或到「歷史會議」選擇會議</span>
      </div>

      <button
        v-for="role in seatRoles"
        :key="role"
        type="button"
        class="seat"
        :class="[
          role === 'Chairman' ? 'seat-chairman' : roleClass(role),
          `seat-status-${seatStatus(role)}`,
          { 'seat-anchor-bottom': hasPortrait(role) },
        ]"
        :style="seatStyle(role)"
        :data-testid="`${seatTestIdPrefix}-${role.toLowerCase()}`"
        :data-status="seatStatus(role)"
        :disabled="!selectedMeeting"
        @click="$emit('seat-click', role)"
      >
        <span class="seat-visual">
          <span v-if="role === 'Chairman' && chairmanSpeaking" class="speech-bubble chairman-bubble">
            {{ latestChairMessage }}
          </span>
          <span v-else-if="seatStatus(role) === 'thinking'" class="speech-bubble thinking-bubble" aria-hidden="true">
            <span class="thinking-dot"></span><span class="thinking-dot"></span><span class="thinking-dot"></span>
          </span>

          <!-- Scene portrait (desktop/tablet). Hidden below 640px in favor of the
               compact avatar card, which also covers the fallback (no-portrait) scene. -->
          <template v-if="hasPortrait(role)">
            <span class="seat-ground-glow" aria-hidden="true"></span>
            <img :src="portraitSrc(role)" :alt="displayRole(role)" class="seat-portrait" />
          </template>

          <span class="seat-avatar" :class="{ 'seat-avatar-fallback': hasPortrait(role) }">
            <img v-if="role !== 'Chairman' && roleIcon(role)" :src="roleIcon(role)" :alt="displayRole(role)" class="seat-avatar-img" />
            <RoleSilhouette v-else :color="role === 'Chairman' ? 'currentColor' : roleColor(role)" :size="28" />
          </span>

          <span
            v-if="seatStatus(role) === 'failed'"
            class="seat-badge seat-badge-failed"
            :class="{ 'seat-badge-portrait': hasPortrait(role) }"
            aria-hidden="true"
          >!</span>
          <span
            v-else-if="seatStatus(role) === 'completed'"
            class="seat-badge seat-badge-completed"
            :class="{ 'seat-badge-portrait': hasPortrait(role) }"
            aria-hidden="true"
          >
            <svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 6 9 17l-5-5" />
            </svg>
          </span>
        </span>
        <span class="seat-below-anchor">
          <span class="seat-nameplate" :class="{ 'has-model-label': role !== 'Chairman' }">
            <span class="seat-nameplate-role">{{ displayRole(role) }}</span>
            <span
              v-if="role !== 'Chairman'"
              class="seat-model-label"
              :class="{ 'seat-model-label-empty': !selectedModels[role] }"
              :data-testid="`${modelTestIdPrefix}-${role.toLowerCase()}`"
              :title="modelLabelTitle(role)"
            >{{ modelLabelText(role) }}</span>
          </span>
          <span v-if="isQueued(role)" class="seat-queue-label">等待發言</span>
        </span>
      </button>
    </div>
  </section>
</template>
