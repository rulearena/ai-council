<script setup lang="ts">
import { computed, inject } from 'vue'
import { councilKey, councilRoles, roleClass, roleIcon, type CouncilRole } from '../composables/useCouncil'
import type { SceneConfig, SeatRole } from '../scenes'

const props = defineProps<{ scene: SceneConfig }>()
defineEmits<{ 'seat-click': [role: CouncilRole | 'Chairman'] }>()

const store = inject(councilKey)!
const { selectedMeeting, pendingRoles, roleSeatStatus, chairmanSpeaking, chairmanEvents } = store

const seatRoles: SeatRole[] = ['Chairman', 'Blue', 'Red', 'Judge']

function seatStyle(role: SeatRole) {
  const seat = props.scene.seats[role]
  return {
    left: `${seat.x}%`,
    top: `${seat.y}%`,
    '--seat-scale': String(seat.scale ?? 1),
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

const sceneStyle = computed(() =>
  props.scene.background
    ? { backgroundImage: `url(${props.scene.background})` }
    : {},
)

const latestChairMessage = computed(() => chairmanEvents.value.at(-1)?.content ?? '')
</script>

<template>
  <section class="council-stage" data-testid="council-stage">
    <div
      class="stage-scene"
      :class="{ 'stage-scene-placeholder': !scene.background }"
      :style="sceneStyle"
      :data-scene="scene.id"
    >
      <div class="stage-table">
        <span class="stage-table-topic">{{ selectedMeeting?.topic ?? '尚未選擇會議' }}</span>
        <span v-if="!selectedMeeting" class="stage-table-hint">從右上角 New Case 建立，或 Past Topics 選擇會議</span>
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
        :data-testid="`role-seat-${role.toLowerCase()}`"
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
            <img :src="portraitSrc(role)" :alt="role === 'Chairman' ? '主席' : role" class="seat-portrait" />
          </template>

          <span class="seat-avatar" :class="{ 'seat-avatar-fallback': hasPortrait(role) }">
            <img v-if="role !== 'Chairman'" :src="roleIcon(role)" :alt="role" class="seat-avatar-img" />
            <svg v-else viewBox="0 0 24 24" width="28" height="28" fill="currentColor" aria-hidden="true">
              <circle cx="12" cy="8" r="4" />
              <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
            </svg>
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
          <span class="seat-nameplate">{{ role === 'Chairman' ? '主席' : role }}</span>
          <span v-if="isQueued(role)" class="seat-queue-label">等待發言</span>
        </span>
      </button>
    </div>
  </section>
</template>
