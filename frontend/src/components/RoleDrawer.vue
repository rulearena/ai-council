<script setup lang="ts">
import { computed, inject } from 'vue'
import {
  councilKey,
  activeMode,
  formatDateTime,
  isCouncilRole,
  roleClass,
  roleColor,
  roleColorVars,
  roleIcon,
  type CouncilRole,
} from '../composables/useCouncil'
import Drawer from './Drawer.vue'
import RoleSilhouette from './RoleSilhouette.vue'
import type { LegacyRoleOutput, StructuredVerdict } from '../api'
import {
  decisionDisplayLabel,
  OUTPUT_LABELS,
  roleDisplayName,
  stepDisplayLabel,
} from '../presentation'

const props = defineProps<{
  role: CouncilRole | 'Chairman' | null
}>()
const emit = defineEmits<{ close: [] }>()

const store = inject(councilKey)!
const {
  latestRoleEvent,
  chairmanEvents,
  loading,
  canRun,
  isTerminalMeeting,
  requestSelectedRoleResponse,
  retrySelectedStep,
  correctSelectedMessage,
  roleHistory,
  selectedMeeting,
} = store

const isChairman = computed(() => props.role === 'Chairman')
const councilRole = computed<CouncilRole | null>(() => (props.role && isCouncilRole(props.role) ? props.role : null))

const latestEvent = computed(() => (councilRole.value ? latestRoleEvent.value[councilRole.value] : null))
const richVerdict = computed<StructuredVerdict | null>(() => {
  const event = latestEvent.value
  if (event?.output_schema_id !== 'structured-verdict/v1') return null
  return (event.parsed_output as StructuredVerdict | undefined) ?? null
})
const legacyOutput = computed<LegacyRoleOutput | null>(() => {
  const event = latestEvent.value
  if (!event || event.output_schema_id === 'structured-verdict/v1') return null
  return (event.parsed_output as LegacyRoleOutput | undefined) ?? null
})
const status = computed(() => {
  if (!latestEvent.value) return 'waiting'
  return latestEvent.value.status === 'failed' ? 'failed' : 'completed'
})
const history = computed(() => (councilRole.value ? roleHistory(councilRole.value) : []))
const pastHistory = computed(() => history.value.slice(0, -1).reverse())

const participants = computed(() => selectedMeeting.value?.participants ?? [])
const displayRole = computed(() =>
  isChairman.value || !props.role
    ? isChairman.value ? '主席' : ''
    : roleDisplayName(activeMode.value, participants.value, props.role),
)
const title = computed(() => displayRole.value)
const displayStep = (event: Parameters<typeof stepDisplayLabel>[2]) =>
  stepDisplayLabel(activeMode.value, participants.value, event)
</script>

<template>
  <Drawer :show="role !== null" :title="`${title} 詳情`" test-id="role-drawer" close-test-id="role-drawer-close-button" @close="emit('close')">
    <template v-if="isChairman">
      <div v-if="chairmanEvents.length === 0" class="empty-state">
        <p>主席尚未發言</p>
      </div>
      <ul class="chairman-history" data-testid="chairman-history-list">
        <li v-for="event in [...chairmanEvents].reverse()" :key="event.event_id" class="chairman-history-item">
          <p>{{ event.content }}</p>
          <div class="chairman-history-meta">
            <small>{{ formatDateTime(event.created_at) }}</small>
            <em v-if="event.corrects_event_id">（訂正）</em>
          </div>
          <button
            v-if="event.step_id === 'human-message' && !event.corrects_event_id"
            type="button"
            class="btn btn-secondary btn-sm edit-message-button"
            data-testid="edit-message-button"
            @click="correctSelectedMessage(event)"
            :disabled="loading || isTerminalMeeting"
          >
            編輯
          </button>
        </li>
      </ul>
    </template>

    <template v-else-if="councilRole">
      <div class="role-output-panel" data-testid="role-output-panel">
        <template v-if="status === 'completed' && latestEvent">
          <article class="role-output-card" :class="roleClass(councilRole)" :style="roleColorVars(councilRole)">
            <header>
              <strong class="role-badge" :class="roleClass(councilRole)" :style="roleColorVars(councilRole)" data-testid="role-badge">
                <img v-if="roleIcon(councilRole)" :src="roleIcon(councilRole)" class="role-icon" :alt="displayRole" />
                <RoleSilhouette v-else :color="roleColor(councilRole)" :size="16" />
                {{ displayRole }}
              </strong>
              <span>{{ displayStep(latestEvent) }}</span>
            </header>
            <h3>{{ OUTPUT_LABELS.roleOutputs }}</h3>
            <p>{{ latestEvent.parsed_output?.summary }}</p>
            <template v-if="richVerdict">
              <section data-testid="rich-verdict-decision">
                <h3>{{ OUTPUT_LABELS.decision }}</h3>
                <p>{{ decisionDisplayLabel(richVerdict.decision) }}</p>
              </section>
              <section data-testid="rich-verdict-findings">
                <h3>{{ OUTPUT_LABELS.findings }}</h3>
                <ul>
                  <li v-for="finding in richVerdict.findings" :key="finding.title">
                    <strong>{{ finding.title }}</strong>
                    <span>{{ finding.detail }}</span>
                    <small v-for="evidenceRef in finding.evidence_refs" :key="evidenceRef">{{ evidenceRef }}</small>
                  </li>
                </ul>
              </section>
              <section data-testid="rich-verdict-risks">
                <h3>{{ OUTPUT_LABELS.risks }}</h3>
                <ul>
                  <li v-for="risk in richVerdict.risks" :key="risk.title">
                    <strong>{{ risk.title }}</strong>
                    <span>{{ risk.detail }}</span>
                    <small v-for="evidenceRef in risk.evidence_refs" :key="evidenceRef">{{ evidenceRef }}</small>
                  </li>
                </ul>
              </section>
            </template>
            <template v-else-if="legacyOutput">
              <h3>{{ OUTPUT_LABELS.arguments }}</h3>
              <ul>
                <li v-for="argument in legacyOutput.arguments" :key="argument.title">
                  <strong>{{ argument.title }}</strong>
                  <span>{{ argument.detail }}</span>
                </li>
              </ul>
              <h3>{{ OUTPUT_LABELS.risks }}</h3>
              <ul>
                <li v-for="risk in legacyOutput.risks" :key="risk.title">
                  <strong>{{ risk.title }}</strong>
                  <span>{{ risk.detail }}</span>
                </li>
              </ul>
            </template>
            <h3>{{ OUTPUT_LABELS.recommendation }}</h3>
            <p>{{ latestEvent.parsed_output?.recommendation }}</p>
            <template v-if="richVerdict">
              <section data-testid="rich-verdict-conditions">
                <h3>{{ OUTPUT_LABELS.conditions }}</h3>
                <ul>
                  <li v-for="condition in richVerdict.conditions" :key="condition">{{ condition }}</li>
                </ul>
              </section>
              <section data-testid="rich-verdict-unresolved">
                <h3>{{ OUTPUT_LABELS.unresolvedQuestions }}</h3>
                <ul>
                  <li v-for="question in richVerdict.unresolved_questions" :key="question">{{ question }}</li>
                </ul>
              </section>
            </template>
          </article>
        </template>
        <template v-else-if="status === 'failed' && latestEvent">
          <p class="role-status-error">{{ latestEvent.error || '執行失敗，請重試' }}</p>
          <button
            type="button"
            class="btn btn-danger btn-sm"
            data-testid="role-status-retry-button"
            :disabled="loading || !canRun"
            @click="retrySelectedStep(latestEvent)"
          >
            重試
          </button>
        </template>
        <div v-else class="empty-state">
          <p>尚無角色回應</p>
        </div>
      </div>

      <button
        type="button"
        class="btn btn-primary role-drawer-respond-button"
        :data-testid="`request-${councilRole.toLowerCase()}-response-button`"
        @click="requestSelectedRoleResponse(councilRole)"
        :disabled="loading || !canRun"
      >
        請 {{ displayRole }} 回應
      </button>

      <details v-if="pastHistory.length" class="role-history" data-testid="role-history-list">
        <summary data-testid="role-history-toggle">歷史回應（{{ pastHistory.length }}）</summary>
        <article
          v-for="event in pastHistory"
          :key="`${event.event_id}:history`"
          class="role-output-card role-history-card"
          :class="roleClass(councilRole)"
          :style="roleColorVars(councilRole)"
        >
          <header>
            <span>{{ displayStep(event) }}</span>
            <small>{{ formatDateTime(event.created_at) }}</small>
          </header>
          <p v-if="event.status === 'failed'" class="role-status-error">{{ event.error }}</p>
          <p v-else>{{ event.parsed_output?.summary }}</p>
        </article>
      </details>
    </template>
  </Drawer>
</template>
