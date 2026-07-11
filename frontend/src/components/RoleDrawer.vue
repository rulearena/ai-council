<script setup lang="ts">
import { computed, inject } from 'vue'
import { councilKey, formatDateTime, isCouncilRole, roleClass, roleIcon, type CouncilRole } from '../composables/useCouncil'
import Drawer from './Drawer.vue'

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
} = store

const isChairman = computed(() => props.role === 'Chairman')
const councilRole = computed<CouncilRole | null>(() => (props.role && isCouncilRole(props.role) ? props.role : null))

const latestEvent = computed(() => (councilRole.value ? latestRoleEvent.value[councilRole.value] : null))
const status = computed(() => {
  if (!latestEvent.value) return 'waiting'
  return latestEvent.value.status === 'failed' ? 'failed' : 'completed'
})
const history = computed(() => (councilRole.value ? roleHistory(councilRole.value) : []))
const pastHistory = computed(() => history.value.slice(0, -1).reverse())

const title = computed(() => (isChairman.value ? '主席' : props.role ?? ''))
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
          <article class="role-output-card" :class="roleClass(councilRole)">
            <header>
              <strong class="role-badge" :class="roleClass(councilRole)" data-testid="role-badge">
                <img v-if="roleIcon(councilRole)" :src="roleIcon(councilRole)" class="role-icon" :alt="councilRole" />
                {{ councilRole }}
              </strong>
              <span>{{ latestEvent.step_id }}</span>
            </header>
            <h3>Role Outputs</h3>
            <p>{{ latestEvent.parsed_output?.summary }}</p>
            <h3>Arguments</h3>
            <ul>
              <li v-for="argument in latestEvent.parsed_output?.arguments" :key="argument.title">
                <strong>{{ argument.title }}</strong>
                <span>{{ argument.detail }}</span>
              </li>
            </ul>
            <h3>Risks</h3>
            <ul>
              <li v-for="risk in latestEvent.parsed_output?.risks" :key="risk.title">
                <strong>{{ risk.title }}</strong>
                <span>{{ risk.detail }}</span>
              </li>
            </ul>
            <h3>Recommendation</h3>
            <p>{{ latestEvent.parsed_output?.recommendation }}</p>
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
          <p>No role output yet</p>
        </div>
      </div>

      <button
        type="button"
        class="btn btn-primary role-drawer-respond-button"
        :data-testid="`request-${councilRole.toLowerCase()}-response-button`"
        @click="requestSelectedRoleResponse(councilRole)"
        :disabled="loading || !canRun"
      >
        請 {{ councilRole }} 回應
      </button>

      <details v-if="pastHistory.length" class="role-history" data-testid="role-history-list">
        <summary data-testid="role-history-toggle">歷史回應（{{ pastHistory.length }}）</summary>
        <article
          v-for="event in pastHistory"
          :key="`${event.event_id}:history`"
          class="role-output-card role-history-card"
          :class="roleClass(councilRole)"
        >
          <header>
            <span>{{ event.step_id }}</span>
            <small>{{ formatDateTime(event.created_at) }}</small>
          </header>
          <p v-if="event.status === 'failed'" class="role-status-error">{{ event.error }}</p>
          <p v-else>{{ event.parsed_output?.summary }}</p>
        </article>
      </details>
    </template>
  </Drawer>
</template>
