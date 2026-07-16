<script setup lang="ts">
import { computed, inject, reactive, ref, watch } from 'vue'
import {
  addCaseEvidence,
  addCaseEvidenceVersion,
  addCaseNote,
  addCaseNoteVersion,
  getCaseMaterials,
  setCaseEvidenceActive,
  setCaseNoteActive,
  type CaseMaterials,
  type VersionedCaseMaterial,
} from '../api'
import { activeMode, councilKey } from '../composables/useCouncil'
import { roleDisplayName } from '../presentation'
import Drawer from './Drawer.vue'

const props = defineProps<{ show: boolean }>()
defineEmits<{ close: [] }>()
const store = inject(councilKey)!
const { selectedMeeting, loading, runAction, openMeeting } = store
const materials = ref<CaseMaterials | null>(null)
const localError = ref('')
const formKind = ref<'evidence' | 'note'>('evidence')
const editingId = ref<string | null>(null)
const form = reactive({ title: '', content: '', visibleRoles: [] as string[] })
let materialsGeneration = 0
const participants = computed(() => selectedMeeting.value?.participants ?? [])
const displayRole = (role: string) => roleDisplayName(activeMode.value, participants.value, role)

watch([() => props.show, () => selectedMeeting.value?.meeting_id], async ([show, id]) => {
  const generation = ++materialsGeneration
  materials.value = null
  if (!show || !id) return
  const response = await getCaseMaterials(id)
  if (generation !== materialsGeneration || selectedMeeting.value?.meeting_id !== id || !props.show) return
  materials.value = response
  clearForm()
}, { immediate: true })

function latest(item: VersionedCaseMaterial) {
  return item.versions.find((version) => version.version === item.active_version) ?? item.versions.at(-1)!
}

function clearForm() {
  form.title = ''
  form.content = ''
  form.visibleRoles = participants.value.map((item) => item.role_id)
  editingId.value = null
  localError.value = ''
}

function edit(item: VersionedCaseMaterial, kind: 'evidence' | 'note') {
  formKind.value = kind
  editingId.value = item.id
  const version = latest(item)
  form.title = version.title
  form.content = version.content
  form.visibleRoles = [...version.visible_roles]
}

async function saveMaterial() {
  const meetingId = selectedMeeting.value?.meeting_id
  if (!meetingId || !materials.value || !form.title.trim() || !form.content.trim() || !form.visibleRoles.length) return
  const payload = { revision: materials.value.revision, title: form.title.trim(), content: form.content.trim(), visible_roles: [...form.visibleRoles] }
  localError.value = ''
  const generation = ++materialsGeneration
  const ok = await runAction(async () => {
    let response: CaseMaterials
    if (formKind.value === 'evidence') {
      response = editingId.value
        ? await addCaseEvidenceVersion(meetingId, editingId.value, payload)
        : await addCaseEvidence(meetingId, payload)
    } else {
      response = editingId.value
        ? await addCaseNoteVersion(meetingId, editingId.value, payload)
        : await addCaseNote(meetingId, payload)
    }
    if (generation !== materialsGeneration || selectedMeeting.value?.meeting_id !== meetingId || !props.show) return
    materials.value = response
    await openMeeting(meetingId)
    if (generation !== materialsGeneration || selectedMeeting.value?.meeting_id !== meetingId || !props.show) return
    clearForm()
  })
  if (!ok && generation === materialsGeneration && selectedMeeting.value?.meeting_id === meetingId) localError.value = store.error.value
}

async function toggle(item: VersionedCaseMaterial, kind: 'evidence' | 'note') {
  const meetingId = selectedMeeting.value?.meeting_id
  if (!meetingId || !materials.value) return
  const active = item.status !== 'active'
  const generation = ++materialsGeneration
  await runAction(async () => {
    const response = kind === 'evidence'
      ? await setCaseEvidenceActive(meetingId, item.id, materials.value!.revision, active)
      : await setCaseNoteActive(meetingId, item.id, materials.value!.revision, active)
    if (generation !== materialsGeneration || selectedMeeting.value?.meeting_id !== meetingId || !props.show) return
    materials.value = response
    await openMeeting(meetingId)
  })
}
</script>

<template>
  <Drawer :show="show" title="案卷與證據" test-id="case-materials-drawer" close-test-id="case-materials-close-button" @close="$emit('close')">
    <template v-if="selectedMeeting && materials">
      <section v-if="materials.pending_impact" class="materials-impact-warning" data-testid="materials-impact-warning">
        <strong>案卷已在 AI 發言後變更</strong>
        <p>為避免新舊證據混用，目前已暫停 AI 與法官判斷。請到「流程操作」選擇重開目前爭點、重開全部審議或重新整理爭點。</p>
      </section>
      <section class="materials-section">
        <h3>證物（{{ materials.evidence.filter(item => item.status === 'active').length }}）</h3>
        <article v-for="item in materials.evidence" :key="item.id" class="material-card" :data-status="item.status" :data-material-id="item.id" data-testid="case-evidence-card">
          <header><strong>{{ item.citation_anchor }} · {{ latest(item).title }}</strong><span>v{{ item.active_version }} · {{ item.status === 'active' ? '使用中' : '已停用' }}</span></header>
          <p>{{ latest(item).content }}</p>
          <small>可見：{{ latest(item).visible_roles.map(displayRole).join('、') }}</small>
          <div><button type="button" class="btn btn-secondary btn-sm" @click="edit(item, 'evidence')">建立新版本</button><button type="button" class="btn btn-ghost btn-sm" :data-testid="item.status === 'active' ? 'deactivate-evidence-button' : 'reactivate-evidence-button'" @click="toggle(item, 'evidence')">{{ item.status === 'active' ? '停用' : '重新啟用' }}</button></div>
        </article>
      </section>
      <section class="materials-section">
        <h3>案件備註（{{ materials.notes.filter(item => item.status === 'active').length }}）</h3>
        <article v-for="item in materials.notes" :key="item.id" class="material-card" :data-status="item.status" :data-material-id="item.id" data-testid="case-note-card">
          <header><strong>{{ latest(item).title }}</strong><span>v{{ item.active_version }} · {{ item.status === 'active' ? '使用中' : '已停用' }}</span></header>
          <p>{{ latest(item).content }}</p>
          <small>可見：{{ latest(item).visible_roles.map(displayRole).join('、') }}</small>
          <div><button type="button" class="btn btn-secondary btn-sm" @click="edit(item, 'note')">建立新版本</button><button type="button" class="btn btn-ghost btn-sm" :data-testid="item.status === 'active' ? 'deactivate-note-button' : 'reactivate-note-button'" @click="toggle(item, 'note')">{{ item.status === 'active' ? '停用' : '重新啟用' }}</button></div>
        </article>
      </section>
      <form class="material-form" data-testid="case-material-form" @submit.prevent="saveMaterial">
        <h3>{{ editingId ? '建立新版本' : formKind === 'evidence' ? '新增證物' : '新增案件備註' }}</h3>
        <div v-if="!editingId" class="segmented"><button type="button" :class="{ active: formKind === 'evidence' }" @click="formKind = 'evidence'">證物</button><button type="button" :class="{ active: formKind === 'note' }" @click="formKind = 'note'">案件備註</button></div>
        <label>標題<input v-model="form.title" :disabled="loading" /></label>
        <label>內容<textarea v-model="form.content" :disabled="loading" /></label>
        <fieldset><legend>可見角色</legend><label v-for="participant in participants" :key="participant.role_id"><input v-model="form.visibleRoles" type="checkbox" :value="participant.role_id" />{{ displayRole(participant.role_id) }}</label></fieldset>
        <p v-if="localError" class="error">{{ localError }}</p>
        <div><button type="submit" class="btn btn-primary" :disabled="loading || !form.title.trim() || !form.content.trim() || !form.visibleRoles.length">{{ editingId ? '保存新版本' : '新增' }}</button><button v-if="editingId" type="button" class="btn btn-secondary" @click="clearForm">取消</button></div>
      </form>
    </template>
    <p v-else class="empty-state">請先選擇會議。</p>
  </Drawer>
</template>
