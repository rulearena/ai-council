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
  uploadAttachment,
  ApiError,
  type CaseMaterials,
  type VersionedCaseMaterial,
} from '../api'
import { activeMode, councilKey } from '../composables/useCouncil'
import {
  createUploadEntry,
  uploadFailed,
  uploadStarted,
  uploadStatusLabel,
  uploadSucceeded,
  type UploadEntry,
} from '../attachmentUpload'
import { roleDisplayName } from '../presentation'
import { materialImpactGuidance, materialVocabulary } from '../meetingWorkspace'
import Modal from './Modal.vue'

const props = defineProps<{ show: boolean }>()
defineEmits<{ close: [] }>()
const store = inject(councilKey)!
const { selectedMeeting, loading, runAction, openMeeting, isMeetingRunning } = store
const materials = ref<CaseMaterials | null>(null)
const localError = ref('')
const materialsLoadError = ref('')
const materialsLoading = ref(false)
const formKind = ref<'evidence' | 'note'>('evidence')
const editingId = ref<string | null>(null)
const form = reactive({ title: '', content: '', visibleRoles: [] as string[] })
let materialsGeneration = 0
const participants = computed(() => selectedMeeting.value?.participants ?? [])
const displayRole = (role: string) => roleDisplayName(activeMode.value, participants.value, role)

const pendingImpactGuidance = computed(() => materialImpactGuidance(selectedMeeting.value?.mode_id ?? ''))
// 法庭用「證物／案卷」，其他模式用中性的「附件」。
const vocab = computed(() => materialVocabulary(selectedMeeting.value?.mode_id ?? ''))

const uploads = ref<UploadEntry[]>([])
const uploadDisabled = computed(() => loading.value || Boolean(isMeetingRunning.value))

function caughtMessage(caught: unknown): string {
  return caught instanceof ApiError && typeof caught.detail === 'string'
    ? caught.detail
    : caught instanceof Error ? caught.message : String(caught)
}

function textExtension(filename: string): boolean {
  return /\.(txt|md)$/i.test(filename)
}

function routeTextFileToCaseForm(file: File) {
  formKind.value = 'evidence'
  editingId.value = null
  form.title = file.name.replace(/\.(txt|md)$/i, '')
  form.visibleRoles = participants.value.map((item) => item.role_id)
  void file.text().then((content) => {
    form.content = content
  })
}

function replaceUpload(entry: UploadEntry, next: UploadEntry) {
  uploads.value = uploads.value.map((item) => (item.key === entry.key ? next : item))
}

async function startUpload(entry: UploadEntry) {
  const file = entry.retryFile
  const meetingId = selectedMeeting.value?.meeting_id
  if (!file || !meetingId) return
  replaceUpload(entry, uploadStarted(entry))
  try {
    await uploadAttachment(meetingId, file)
    replaceUpload(entry, uploadSucceeded(entry))
    // The meeting payload carries attachments_summary + the new attachment event,
    // so the ＋ count and the feed bubble both come from one refresh.
    await openMeeting(meetingId)
  } catch (caught) {
    replaceUpload(entry, uploadFailed(entry, caughtMessage(caught)))
  }
}

function onFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  for (const file of files) {
    if (textExtension(file.name)) {
      routeTextFileToCaseForm(file)
    } else {
      uploads.value = [...uploads.value, createUploadEntry(file)]
      void startUpload(uploads.value.at(-1)!)
    }
  }
}

function retryUpload(entry: UploadEntry) {
  void startUpload(entry)
}

function dismissUpload(entry: UploadEntry) {
  uploads.value = uploads.value.filter((item) => item.key !== entry.key)
}

async function loadMaterials(id: string) {
  const generation = ++materialsGeneration
  materials.value = null
  materialsLoadError.value = ''
  materialsLoading.value = true
  try {
    const response = await getCaseMaterials(id)
    if (generation !== materialsGeneration || selectedMeeting.value?.meeting_id !== id || !props.show) return
    materials.value = response
    clearForm()
  } catch (caught) {
    if (generation === materialsGeneration && selectedMeeting.value?.meeting_id === id && props.show) {
      materialsLoadError.value = caughtMessage(caught)
    }
  } finally {
    if (generation === materialsGeneration) materialsLoading.value = false
  }
}

watch([() => props.show, () => selectedMeeting.value?.meeting_id], ([show, id]) => {
  ++materialsGeneration
  materials.value = null
  materialsLoadError.value = ''
  uploads.value = []
  if (!show || !id) return
  void loadMaterials(id)
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
  <Modal :show="show" :title="vocab.panelTitle" test-id="case-materials-modal" close-test-id="case-materials-close-button" @close="$emit('close')">
    <div v-if="materialsLoadError" class="error" data-testid="materials-load-error">
      <p>{{ materialsLoadError }}</p>
      <button type="button" class="btn btn-secondary btn-sm" data-testid="retry-materials-load-button" :disabled="materialsLoading" @click="selectedMeeting && loadMaterials(selectedMeeting.meeting_id)">重新載入</button>
    </div>
    <template v-if="selectedMeeting && materials">
      <section v-if="materials.pending_impact" class="materials-impact-warning" data-testid="materials-impact-warning">
        <strong>{{ vocab.changedTitle }}</strong>
        <p>{{ pendingImpactGuidance }}</p>
      </section>
      <section class="materials-section">
        <label class="attachment-upload-zone" data-testid="attachment-upload-zone">
          <input
            type="file"
            class="visually-hidden"
            data-testid="attachment-upload-input"
            multiple
            :disabled="uploadDisabled"
            @change="onFileSelected"
          />
          <strong>{{ uploadDisabled ? '會議執行中，暫時無法上傳' : `上傳${vocab.itemPlural}` }}</strong>
          <small>點此選擇檔案；.txt／.md 會進入{{ vocab.itemPlural }}列表，其餘立即上傳為{{ vocab.itemPlural }}</small>
        </label>
        <ul v-if="uploads.length" class="attachment-upload-list" data-testid="attachment-upload-list">
          <li v-for="entry in uploads" :key="entry.key" :data-status="entry.status" :data-testid="`attachment-upload-${entry.key}`">
            <span class="attachment-upload-name">{{ entry.filename }}</span>
            <span class="attachment-upload-state">
              {{ uploadStatusLabel(entry.status) }}
            </span>
            <button v-if="entry.status === 'error'" type="button" class="btn btn-ghost btn-sm" data-testid="attachment-upload-retry" @click="retryUpload(entry)">重試</button>
            <button v-if="entry.status === 'error'" type="button" class="btn btn-ghost btn-sm" data-testid="attachment-upload-dismiss" @click="dismissUpload(entry)">略過</button>
            <small v-if="entry.error" class="error" data-testid="attachment-upload-error">{{ entry.error }}</small>
          </li>
        </ul>
      </section>
      <section class="materials-section">
        <h3>{{ vocab.itemPlural }}（{{ materials.evidence.filter(item => item.status === 'active').length }}）</h3>
        <article v-for="item in materials.evidence" :key="item.id" class="material-card" :data-status="item.status" :data-material-id="item.id" data-testid="case-evidence-card">
          <header><strong>{{ item.citation_anchor }} · {{ latest(item).title }}</strong><span>v{{ item.active_version }} · {{ item.status === 'active' ? '使用中' : '已停用' }}</span></header>
          <p>{{ latest(item).content }}</p>
          <small>可見：{{ latest(item).visible_roles.map(displayRole).join('、') }}</small>
          <div><button type="button" class="btn btn-secondary btn-sm" @click="edit(item, 'evidence')">建立新版本</button><button type="button" class="btn btn-ghost btn-sm" :data-testid="item.status === 'active' ? 'deactivate-evidence-button' : 'reactivate-evidence-button'" @click="toggle(item, 'evidence')">{{ item.status === 'active' ? '停用' : '重新啟用' }}</button></div>
        </article>
      </section>
      <section class="materials-section">
        <h3>{{ vocab.notePlural }}（{{ materials.notes.filter(item => item.status === 'active').length }}）</h3>
        <article v-for="item in materials.notes" :key="item.id" class="material-card" :data-status="item.status" :data-material-id="item.id" data-testid="case-note-card">
          <header><strong>{{ latest(item).title }}</strong><span>v{{ item.active_version }} · {{ item.status === 'active' ? '使用中' : '已停用' }}</span></header>
          <p>{{ latest(item).content }}</p>
          <small>可見：{{ latest(item).visible_roles.map(displayRole).join('、') }}</small>
          <div><button type="button" class="btn btn-secondary btn-sm" @click="edit(item, 'note')">建立新版本</button><button type="button" class="btn btn-ghost btn-sm" :data-testid="item.status === 'active' ? 'deactivate-note-button' : 'reactivate-note-button'" @click="toggle(item, 'note')">{{ item.status === 'active' ? '停用' : '重新啟用' }}</button></div>
        </article>
      </section>
      <form class="material-form" data-testid="case-material-form" @submit.prevent="saveMaterial">
        <h3>{{ editingId ? '建立新版本' : formKind === 'evidence' ? vocab.addItem : vocab.addNote }}</h3>
        <div v-if="!editingId" class="segmented"><button type="button" :class="{ active: formKind === 'evidence' }" @click="formKind = 'evidence'">{{ vocab.itemPlural }}</button><button type="button" :class="{ active: formKind === 'note' }" @click="formKind = 'note'">{{ vocab.notePlural }}</button></div>
        <label>標題<input v-model="form.title" :disabled="loading" /></label>
        <label>內容<textarea v-model="form.content" :disabled="loading" /></label>
        <fieldset><legend>可見角色</legend><label v-for="participant in participants" :key="participant.role_id"><input v-model="form.visibleRoles" type="checkbox" :value="participant.role_id" />{{ displayRole(participant.role_id) }}</label></fieldset>
        <p v-if="localError" class="error">{{ localError }}</p>
        <div><button type="submit" class="btn btn-primary" :disabled="loading || !form.title.trim() || !form.content.trim() || !form.visibleRoles.length">{{ editingId ? '保存新版本' : '新增' }}</button><button v-if="editingId" type="button" class="btn btn-secondary" @click="clearForm">取消</button></div>
      </form>
    </template>
    <p v-else-if="!materialsLoadError" class="empty-state">{{ selectedMeeting ? vocab.loading : '請先選擇會議。' }}</p>
  </Modal>
</template>

<style scoped>
.attachment-upload-zone {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 12px;
  border: 1px dashed var(--border, #ccc);
  border-radius: 8px;
  cursor: pointer;
  text-align: center;
}

.attachment-upload-zone:has(input:disabled) {
  cursor: not-allowed;
  opacity: 0.6;
}

.attachment-upload-zone small {
  opacity: 0.7;
}

.attachment-upload-list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.attachment-upload-list li {
  display: grid;
  grid-template-columns: 1fr auto auto auto;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--border, #eee);
  border-radius: 6px;
  font-size: 0.9em;
}

.attachment-upload-list li[data-status='done'] {
  background: var(--bg-muted, #f6f9f6);
}

.attachment-upload-list li[data-status='error'] {
  background: var(--bg-muted, #fdf5f5);
}

.attachment-upload-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-upload-state {
  opacity: 0.75;
  font-size: 0.85em;
}

.attachment-upload-list li[data-status='error'] small {
  grid-column: 1 / -1;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
