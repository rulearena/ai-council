<script setup lang="ts">
import { computed, inject, onUnmounted, ref, watch } from 'vue'
import { updateMeetingSettings } from '../api'
import { councilKey } from '../composables/useCouncil'
import { roleDisplayName } from '../presentation'
import { activeMode } from '../composables/useCouncil'
import { modelDisplayLabel } from '../providers'
import { scenes } from '../scenes'
import {
  buildMeetingSettingsPayload,
  hydrateMeetingSettingsDraft,
  validateMeetingSettingsDraft,
  type MeetingSettingsDraft,
} from '../meetingWorkspace'
import Drawer from './Drawer.vue'
import { canLeaveMeetingSettings, registerMeetingSettingsNavigationState } from '../meetingSettingsNavigation'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: [] }>()
const store = inject(councilKey)!
const { selectedMeeting, models, loading, isMeetingRunning, openMeeting, runAction } = store
const draft = ref<MeetingSettingsDraft | null>(null)
const baselineDraft = ref<MeetingSettingsDraft | null>(null)
const saveError = ref('')
let saveGeneration = 0
const saving = ref(false)

const dirty = computed(() => Boolean(
  draft.value && baselineDraft.value &&
  JSON.stringify(buildMeetingSettingsPayload(draft.value)) !==
    JSON.stringify(buildMeetingSettingsPayload(baselineDraft.value)),
))
const errors = computed(() => draft.value && selectedMeeting.value
  ? validateMeetingSettingsDraft(draft.value, selectedMeeting.value)
  : { title: '', goal: '', caseType: '', participantModels: '' })
const invalid = computed(() => Object.values(errors.value).some(Boolean))
const confirmedCourtroom = computed(() => selectedMeeting.value?.mode_id === 'courtroom' && selectedMeeting.value.courtroom?.status === 'confirmed')
const caseTypeLocked = computed(() => confirmedCourtroom.value && Boolean(selectedMeeting.value?.case_type))
const assignmentWarnings = computed(() => selectedMeeting.value?.participants
  .filter((participant) => participant.model_assignment_warning)
  .map((participant) => `${displayRole(participant.role_id)}：${participant.model_assignment_warning}`) ?? [])
const displayRole = (role: string) => roleDisplayName(activeMode.value, selectedMeeting.value?.participants ?? [], role)

function hydrate() {
  draft.value = selectedMeeting.value ? hydrateMeetingSettingsDraft(selectedMeeting.value) : null
  baselineDraft.value = draft.value
    ? { ...draft.value, participantModels: { ...draft.value.participantModels } }
    : null
  saveError.value = ''
}

watch([() => props.show, () => selectedMeeting.value?.meeting_id], ([show]) => {
  saveGeneration += 1
  registerMeetingSettingsNavigationState(show ? {
    dirty: () => dirty.value,
    saving: () => saving.value,
    discard: hydrate,
  } : null)
  if (!show) return
  hydrate()
}, { immediate: true })

onUnmounted(() => registerMeetingSettingsNavigationState(null))

function requestClose() {
  if (!canLeaveMeetingSettings()) return
  emit('close')
}

async function save() {
  const meeting = selectedMeeting.value
  if (!meeting || !draft.value || invalid.value || loading.value) return
  const goalChanged = draft.value.goal.trim() !== (meeting.goal ?? '')
  const hasAiOutput = (meeting.events ?? []).some((event) => !['Human', 'System'].includes(event.role) && event.status === 'completed')
  if (goalChanged && hasAiOutput && !window.confirm('修改目標只影響後續 AI 回應，既有發言不會重新產生。確定儲存？')) return
  saveError.value = ''
  const requestGeneration = ++saveGeneration
  const meetingId = meeting.meeting_id
  const payload = buildMeetingSettingsPayload(draft.value)
  saving.value = true
  const ok = await runAction(async () => {
    await updateMeetingSettings(meetingId, payload)
    if (requestGeneration !== saveGeneration || selectedMeeting.value?.meeting_id !== meetingId) return
    await openMeeting(meetingId)
    if (requestGeneration !== saveGeneration || selectedMeeting.value?.meeting_id !== meetingId) return
    hydrate()
    emit('close')
  })
  if (!ok && requestGeneration === saveGeneration && selectedMeeting.value?.meeting_id === meetingId) {
    saveError.value = store.error.value || '會議設定儲存失敗。'
  }
  saving.value = false
}
</script>

<template>
  <Drawer :show="show" title="會議設定" test-id="meeting-settings-drawer" close-test-id="meeting-settings-close-button" @close="requestClose">
    <form v-if="draft && selectedMeeting" class="meeting-settings-form" @submit.prevent="save">
      <p v-if="isMeetingRunning" class="materials-impact-warning" data-testid="meeting-settings-running-notice">會議正在執行 AI 步驟。為避免本次執行混用新舊設定，完成前無法編輯或儲存。</p>
      <section>
        <h3>基本資料</h3>
        <label>會議名稱<input v-model="draft.title" data-testid="meeting-title-input" :disabled="loading || isMeetingRunning" /></label>
        <small v-if="errors.title" class="field-error">{{ errors.title }}</small>
        <label>AI 最終目標<textarea v-model="draft.goal" data-testid="meeting-goal-input" :readonly="confirmedCourtroom" :disabled="loading || isMeetingRunning" /></label>
        <small v-if="confirmedCourtroom">爭點已確認。重新整理爭點後才可修改 AI 目標。</small>
        <small v-if="errors.goal" class="field-error">{{ errors.goal }}</small>
        <label v-if="selectedMeeting.mode_id === 'courtroom'">案件類型
          <select v-model="draft.caseType" data-testid="meeting-case-type-select" :disabled="loading || isMeetingRunning || caseTypeLocked">
            <option :value="null" disabled>請選擇</option><option value="civil">民事</option><option value="criminal">刑事</option>
          </select>
        </label>
        <small v-if="caseTypeLocked">爭點已確認。重新整理爭點後才可變更案件類型。</small>
        <small v-else-if="confirmedCourtroom">這是缺少案件類型的舊法院會議；請在此選擇後一次儲存全部設定。</small>
        <small v-if="errors.caseType" class="field-error">{{ errors.caseType }}</small>
      </section>
      <section>
        <h3>場景</h3>
        <label>會議場景<select v-model="draft.scene" data-testid="scene-select" :disabled="loading || isMeetingRunning"><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.label }}</option></select></label>
      </section>
      <section>
        <h3>角色模型</h3>
        <div v-if="assignmentWarnings.length" class="materials-impact-warning" data-testid="assignment-fallback-warning">
          <strong>部分原指派模型已無法使用，系統目前使用替代模型</strong>
          <p v-for="warning in assignmentWarnings" :key="warning">{{ warning }}</p>
        </div>
        <label v-for="participant in selectedMeeting.participants" :key="participant.role_id">
          {{ displayRole(participant.role_id) }}
          <select v-model="draft.participantModels[participant.role_id]" :data-testid="`${participant.role_id.toLowerCase()}-model-select`" :disabled="loading || isMeetingRunning">
            <option value="" disabled>請選擇模型</option>
            <option v-for="model in models" :key="model.id" :value="model.id">{{ modelDisplayLabel(model) }}</option>
          </select>
        </label>
        <small v-if="errors.participantModels" class="field-error">{{ errors.participantModels }}</small>
      </section>
      <p v-if="saveError" class="error" role="alert">{{ saveError }}</p>
      <footer class="drawer-sticky-actions">
        <button type="submit" class="btn btn-primary" data-testid="save-meeting-settings-button" :disabled="loading || isMeetingRunning || invalid || !dirty">{{ saving ? '儲存中…' : '一次儲存全部設定' }}</button>
        <button type="button" class="btn btn-secondary" :disabled="loading || !dirty" @click="hydrate">放棄變更</button>
      </footer>
    </form>
    <p v-else class="empty-state">請先選擇會議。</p>
  </Drawer>
</template>
