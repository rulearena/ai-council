<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
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

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: [] }>()
const store = inject(councilKey)!
const { selectedMeeting, models, loading, openMeeting, runAction } = store
const draft = ref<MeetingSettingsDraft | null>(null)
const baselineDraft = ref<MeetingSettingsDraft | null>(null)
const saveError = ref('')

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
const displayRole = (role: string) => roleDisplayName(activeMode.value, selectedMeeting.value?.participants ?? [], role)

function hydrate() {
  draft.value = selectedMeeting.value ? hydrateMeetingSettingsDraft(selectedMeeting.value) : null
  baselineDraft.value = draft.value
    ? { ...draft.value, participantModels: { ...draft.value.participantModels } }
    : null
  saveError.value = ''
}

watch([() => props.show, () => selectedMeeting.value?.meeting_id], ([show], [previousShow, previousMeetingId]) => {
  if (!show) return
  if (previousShow && previousMeetingId && previousMeetingId !== selectedMeeting.value?.meeting_id && dirty.value) {
    window.confirm('切換會議會放棄尚未儲存的會議設定。')
  }
  hydrate()
}, { immediate: true })

function requestClose() {
  if (dirty.value && !window.confirm('尚有未儲存的會議設定，確定放棄並關閉？')) return
  emit('close')
}

async function save() {
  const meeting = selectedMeeting.value
  if (!meeting || !draft.value || invalid.value || loading.value) return
  const goalChanged = draft.value.goal.trim() !== (meeting.goal ?? '')
  const hasAiOutput = (meeting.events ?? []).some((event) => !['Human', 'System'].includes(event.role) && event.status === 'completed')
  if (goalChanged && hasAiOutput && !window.confirm('修改目標只影響後續 AI 回應，既有發言不會重新產生。確定儲存？')) return
  saveError.value = ''
  const payload = buildMeetingSettingsPayload(draft.value)
  const ok = await runAction(async () => {
    await updateMeetingSettings(meeting.meeting_id, payload)
    await openMeeting(meeting.meeting_id)
    hydrate()
    emit('close')
  })
  if (!ok) saveError.value = store.error.value || '會議設定儲存失敗。'
}
</script>

<template>
  <Drawer :show="show" title="會議設定" test-id="meeting-settings-drawer" close-test-id="meeting-settings-close-button" @close="requestClose">
    <form v-if="draft && selectedMeeting" class="meeting-settings-form" @submit.prevent="save">
      <section>
        <h3>基本資料</h3>
        <label>會議名稱<input v-model="draft.title" data-testid="meeting-title-input" :disabled="loading" /></label>
        <small v-if="errors.title" class="field-error">{{ errors.title }}</small>
        <label>AI 最終目標<textarea v-model="draft.goal" data-testid="meeting-goal-input" :readonly="confirmedCourtroom" :disabled="loading" /></label>
        <small v-if="confirmedCourtroom">爭點已確認。重新整理爭點後才可修改 AI 目標。</small>
        <small v-if="errors.goal" class="field-error">{{ errors.goal }}</small>
        <label v-if="selectedMeeting.mode_id === 'courtroom'">案件類型
          <select v-model="draft.caseType" data-testid="meeting-case-type-select" :disabled="loading || confirmedCourtroom">
            <option :value="null" disabled>請選擇</option><option value="civil">民事</option><option value="criminal">刑事</option>
          </select>
        </label>
        <small v-if="confirmedCourtroom">爭點已確認。重新整理爭點後才可變更案件類型。</small>
        <small v-if="errors.caseType" class="field-error">{{ errors.caseType }}</small>
      </section>
      <section>
        <h3>場景</h3>
        <label>會議場景<select v-model="draft.scene" data-testid="scene-select" :disabled="loading"><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.label }}</option></select></label>
      </section>
      <section>
        <h3>角色模型</h3>
        <label v-for="participant in selectedMeeting.participants" :key="participant.role_id">
          {{ displayRole(participant.role_id) }}
          <select v-model="draft.participantModels[participant.role_id]" :data-testid="`${participant.role_id.toLowerCase()}-model-select`" :disabled="loading">
            <option value="" disabled>請選擇模型</option>
            <option v-for="model in models" :key="model.id" :value="model.id">{{ modelDisplayLabel(model) }}</option>
          </select>
        </label>
        <small v-if="errors.participantModels" class="field-error">{{ errors.participantModels }}</small>
      </section>
      <p v-if="saveError" class="error" role="alert">{{ saveError }}</p>
      <footer class="drawer-sticky-actions">
        <button type="submit" class="btn btn-primary" data-testid="save-meeting-settings-button" :disabled="loading || invalid || !dirty">{{ loading ? '儲存中…' : '一次儲存全部設定' }}</button>
        <button type="button" class="btn btn-secondary" :disabled="loading || !dirty" @click="hydrate">放棄變更</button>
      </footer>
    </form>
    <p v-else class="empty-state">請先選擇會議。</p>
  </Drawer>
</template>
