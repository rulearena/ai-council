<script setup lang="ts">
// Shared card presentation for a single mode.ts entry - used both by NewCaseModal's
// mode picker (step 1, `showActions` true so a card can actually be chosen) and by
// ModeHelpDrawer (browsing only, `showActions` false). Keeping this in one place means
// the "which mode am I looking at" markup (tagline/when-to-use/SOP/ring preview) only
// exists once instead of drifting between the two surfaces.
import { computed, ref } from 'vue'
import { ringSeatLayout, type ModeDefinition } from '../modes'

const props = withDefaults(
  defineProps<{
    mode: ModeDefinition
    testIdPrefix: string
    showActions?: boolean
  }>(),
  { showActions: true },
)
const emit = defineEmits<{ choose: [] }>()

const sopOpen = ref(false)

function toggleSop() {
  sopOpen.value = !sopOpen.value
}

// Small preview of how N concurrent members are seated in a parallel mode. Member count:
// the fanout's minimum for a prototype+N mode (brainstorm, persona-testing), or the fixed
// member count for a fully-named roster (six-hats).
const previewMemberCount = computed(() =>
  props.mode.fanout ? props.mode.fanout.minInstances : props.mode.roles.filter((role) => role.kind === 'member').length,
)
const previewRingSeats = computed(() => ringSeatLayout(previewMemberCount.value))
</script>

<template>
  <article
    class="mode-card"
    :class="{ 'mode-card-unavailable': !mode.available }"
    :data-testid="`${testIdPrefix}-${mode.id}`"
  >
    <header class="mode-card-header">
      <h3>{{ mode.name }}</h3>
      <span class="mode-category-badge" :data-category="mode.category">
        {{ mode.category === 'relay' ? '回合制' : '平行' }}
      </span>
    </header>
    <p class="mode-tagline">{{ mode.tagline }}</p>
    <p class="mode-when-to-use"><strong>適合情境：</strong>{{ mode.whenToUse }}</p>

    <button
      type="button"
      class="btn btn-ghost btn-sm mode-sop-toggle"
      data-testid="mode-sop-toggle"
      :aria-expanded="sopOpen"
      @click="toggleSop"
    >
      {{ sopOpen ? '收合 SOP ▲' : '展開 SOP ▼' }}
    </button>

    <Transition name="sop-expand">
      <div v-if="sopOpen" class="mode-sop-panel" data-testid="mode-sop-panel">
        <ol class="mode-sop-list">
          <li v-for="(item, index) in mode.sop" :key="index">{{ item }}</li>
        </ol>

        <div v-if="mode.category === 'parallel'" class="mode-ring-preview" data-testid="mode-ring-preview">
          <svg viewBox="0 0 100 100" class="ring-preview-svg" aria-hidden="true">
            <circle
              v-for="(seat, index) in previewRingSeats"
              :key="index"
              :cx="seat.x"
              :cy="seat.y"
              r="4"
              class="ring-preview-seat"
              data-testid="mode-ring-preview-seat"
            />
          </svg>
          <span class="ring-preview-caption">{{ previewMemberCount }} 位成員座位預覽</span>
        </div>
      </div>
    </Transition>

    <button
      v-if="showActions"
      type="button"
      class="btn mode-card-cta"
      :class="mode.available ? 'btn-primary' : 'btn-secondary'"
      :disabled="!mode.available"
      @click="emit('choose')"
    >
      {{ mode.available ? '選擇此模式' : '即將推出' }}
    </button>
  </article>
</template>
