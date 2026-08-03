<script setup lang="ts">
import { computed, inject, reactive, ref, watch } from 'vue'
import {
  addCaseEvidence,
  addCaseEvidenceVersion,
  addCaseNote,
  addCaseNoteVersion,
  attachmentDownloadUrl,
  deleteAttachment,
  getCaseMaterials,
  setCaseEvidenceActive,
  setCaseNoteActive,
  ApiError,
  type CaseMaterials,
  type MeetingEvent,
  type VersionedCaseMaterial,
} from '../api'
import { activeMode, councilKey } from '../composables/useCouncil'
import { uploadStatusLabel, type UploadEntry } from '../attachmentUpload'
import { type TextDraft } from '../materialUploads'
import { roleDisplayName } from '../presentation'
import {
  formatAttachmentSize,
  hasAiOutput,
  isAttachmentEvent,
  materialImpactConfirmMessage,
  materialImpactGuidance,
  materialVocabulary,
} from '../meetingWorkspace'

// 資料管理內容（原 CaseMaterialsModal 的管理部分），渲染於側欄資料頁。
// 上傳與管理已拆分：＋ 快速選單負責上傳（二進位立即上傳、.txt/.md 預填表單），
// 這裡只負責管理（進度列、evidence/notes CRUD、附件清單）。
// `active` 用於載入時機與 generation guard；tab 之間以 v-show 保留 state，不重載。
// `simple`（聊天室）隱藏表單／備註／版本管理，只保留進度列、附件清單與只讀 evidence。
const props = defineProps<{
  active: boolean
  meetingId: string
  uploads: UploadEntry[]
  textDraft: TextDraft | null
  simple?: boolean
}>()

const emit = defineEmits<{
  'retry-upload': [entry: UploadEntry]
  'dismiss-upload': [entry: UploadEntry]
  'text-draft-consumed': []
}>()

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
let loadedMeetingId: string | null = null
const participants = computed(() => selectedMeeting.value?.participants ?? [])
const displayRole = (role: string) => roleDisplayName(activeMode.value, participants.value, role)

const pendingImpactGuidance = computed(() => materialImpactGuidance(selectedMeeting.value?.mode_id ?? ''))
// 法庭用「證物／案卷」，其他模式用中性的「附件／資料」。
const vocab = computed(() => materialVocabulary(selectedMeeting.value?.mode_id ?? ''))
// AI 已發言後變更案卷會觸發 material_change_impact（AI 暫停並需重開審議），先請使用者確認。
const aiHasSpoken = computed(() => hasAiOutput(selectedMeeting.value?.events ?? []))
// 附件清單：列舉 events 中 attachment-added 事件（binary 下載不受 visible_roles 控管）。
// 已刪除（removed: true）的行不顯示，避免與 feed 的「已刪除」氣泡重複。
const attachments = computed(() =>
  (selectedMeeting.value?.events ?? []).filter(
    (event) => isAttachmentEvent(event) && !event.removed,
  ),
)

function caughtMessage(caught: unknown): string {
  return caught instanceof ApiError && typeof caught.detail === 'string'
    ? caught.detail
    : caught instanceof Error ? caught.message : String(caught)
}

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

function applyTextDraft(draft: NonNullable<TextDraft>) {
  formKind.value = 'evidence'
  editingId.value = null
  form.title = draft.filename
  form.content = draft.content
  form.visibleRoles = participants.value.map((item) => item.role_id)
  emit('text-draft-consumed')
}

// .txt/.md 草稿是 async 讀取後才到達；materials 已載入就直接預填，未載入則等載入成功後套用。
watch(
  () => props.textDraft,
  (draft) => {
    if (draft && materials.value && loadedMeetingId === props.meetingId) applyTextDraft(draft)
  },
)

async function loadMaterials(id: string) {
  const generation = ++materialsGeneration
  materialsLoadError.value = ''
  materialsLoading.value = true
  try {
    const response = await getCaseMaterials(id)
    if (generation !== materialsGeneration || loadedMeetingId !== id || !props.active) return
    materials.value = response
    // 套用 pending textDraft（預填後清除）；無 pending draft 才 clearForm，避免
    // 載入完成後的 clearForm() 清掉剛預填的內容（現行 :124 的競態）。
    if (props.textDraft) applyTextDraft(props.textDraft)
    else clearForm()
  } catch (caught) {
    if (generation === materialsGeneration && loadedMeetingId === id && props.active) {
      materialsLoadError.value = caughtMessage(caught)
    }
  } finally {
    if (generation === materialsGeneration) materialsLoading.value = false
  }
}

watch(
  [() => props.active, () => props.meetingId],
  ([active, id]) => {
    ++materialsGeneration
    materialsLoadError.value = ''
    if (!active || !id) return
    if (id !== loadedMeetingId) {
      // 切換會議：清掉舊資料再載入（沿用 modal 的行為），stale response 由 generation guard 丟棄。
      loadedMeetingId = id
      materials.value = null
      void loadMaterials(id)
    } else if (!materials.value || materials.value.pending_impact) {
      // pending_impact 是伺服器依「目前 epoch」計算的有效值；快取可能因
      // restart/abandon 已過時。重新啟用同一會議而快取仍帶 pending_impact 時
      // 重載一次，讓案卷影響警告隨新 epoch 消失（其餘情況保留 state 不重載）。
      void loadMaterials(id)
    }
  },
  { immediate: true },
)

function edit(item: VersionedCaseMaterial, kind: 'evidence' | 'note') {
  formKind.value = kind
  editingId.value = item.id
  const version = latest(item)
  form.title = version.title
  form.content = version.content
  form.visibleRoles = [...version.visible_roles]
}

async function saveMaterial() {
  const meetingId = props.meetingId
  if (!meetingId || !materials.value || !form.title.trim() || !form.content.trim() || !form.visibleRoles.length) return
  if (aiHasSpoken.value && !window.confirm(materialImpactConfirmMessage(selectedMeeting.value?.mode_id ?? ''))) return
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
    if (generation !== materialsGeneration || loadedMeetingId !== meetingId || !props.active) return
    materials.value = response
    await openMeeting(meetingId)
    if (generation !== materialsGeneration || loadedMeetingId !== meetingId || !props.active) return
    clearForm()
  })
  if (!ok && generation === materialsGeneration && loadedMeetingId === meetingId) localError.value = store.error.value
}

async function toggle(item: VersionedCaseMaterial, kind: 'evidence' | 'note') {
  const meetingId = props.meetingId
  if (!meetingId || !materials.value) return
  if (aiHasSpoken.value && !window.confirm(materialImpactConfirmMessage(selectedMeeting.value?.mode_id ?? ''))) return
  const active = item.status !== 'active'
  const generation = ++materialsGeneration
  await runAction(async () => {
    const response = kind === 'evidence'
      ? await setCaseEvidenceActive(meetingId, item.id, materials.value!.revision, active)
      : await setCaseNoteActive(meetingId, item.id, materials.value!.revision, active)
    if (generation !== materialsGeneration || loadedMeetingId !== meetingId || !props.active) return
    materials.value = response
    await openMeeting(meetingId)
  })
}

async function confirmDeleteAttachment(event: MeetingEvent) {
  const meetingId = props.meetingId
  const fileId = event.file_id
  if (!meetingId || !fileId) return
  if (!window.confirm('刪除後無法復原。確定刪除？')) return
  localError.value = ''
  const generation = ++materialsGeneration
  const ok = await runAction(async () => {
    await deleteAttachment(meetingId, fileId)
    if (generation !== materialsGeneration || loadedMeetingId !== meetingId || !props.active) return
    await openMeeting(meetingId)
  })
  if (!ok && generation === materialsGeneration && loadedMeetingId === meetingId) {
    localError.value = caughtMessage(store.error.value)
  }
}
</script>

<template>
  <div class="materials-panel">
    <!-- 上傳進度列獨立於 materials 載入狀態渲染：載入失敗仍能顯示進度與重試／略過。 -->
    <ul v-if="uploads.length" class="attachment-upload-list" data-testid="attachment-upload-list">
      <li v-for="entry in uploads" :key="entry.key" :data-status="entry.status" :data-testid="`attachment-upload-${entry.key}`">
        <span class="attachment-upload-name">{{ entry.filename }}</span>
        <span class="attachment-upload-state">
          {{ uploadStatusLabel(entry.status) }}
        </span>
        <button v-if="entry.status === 'error'" type="button" class="btn btn-ghost btn-sm" data-testid="attachment-upload-retry" @click="emit('retry-upload', entry)">重試</button>
        <button v-if="entry.status === 'error'" type="button" class="btn btn-ghost btn-sm" data-testid="attachment-upload-dismiss" @click="emit('dismiss-upload', entry)">略過</button>
        <small v-if="entry.error" class="error" data-testid="attachment-upload-error">{{ entry.error }}</small>
      </li>
    </ul>

    <div v-if="materialsLoadError" class="error" data-testid="materials-load-error">
      <p>{{ materialsLoadError }}</p>
      <button type="button" class="btn btn-secondary btn-sm" data-testid="retry-materials-load-button" :disabled="materialsLoading" @click="loadedMeetingId && loadMaterials(loadedMeetingId)">重新載入</button>
    </div>

    <template v-if="selectedMeeting && materials">
      <section v-if="materials.pending_impact" class="materials-impact-warning" data-testid="materials-impact-warning">
        <strong>{{ vocab.changedTitle }}</strong>
        <p>{{ pendingImpactGuidance }}</p>
      </section>

      <section v-if="active && attachments.length" class="materials-section" data-testid="materials-attachment-list">
        <h3>{{ vocab.itemPlural }}檔案（{{ attachments.length }}）</h3>
        <ul class="materials-attachment-list">
          <template v-for="event in attachments" :key="event.event_id">
            <li v-if="event.file_id" class="materials-attachment-row" data-testid="materials-attachment-row">
              <a :href="attachmentDownloadUrl(props.meetingId, event.file_id)" download :data-testid="`materials-attachment-download-${event.file_id}`">
                <strong>{{ event.filename ?? event.file_id }}</strong>
                <small>{{ formatAttachmentSize(event.size ?? 0) }}</small>
              </a>
              <button type="button" class="btn btn-ghost btn-sm" :data-testid="`attachment-delete-${event.file_id}`" :disabled="loading" @click="confirmDeleteAttachment(event)">刪除</button>
            </li>
          </template>
        </ul>
      </section>

      <section class="materials-section">
        <h3>{{ vocab.itemPlural }}（{{ materials.evidence.filter(item => item.status === 'active').length }}）</h3>
        <article v-for="item in materials.evidence" :key="item.id" class="material-card" :data-status="item.status" :data-material-id="item.id" data-testid="case-evidence-card">
          <header><strong>{{ item.citation_anchor }} · {{ latest(item).title }}</strong><span v-if="!simple">v{{ item.active_version }} · {{ item.status === 'active' ? '使用中' : '已停用' }}</span></header>
          <p>{{ latest(item).content }}</p>
          <small>可見：{{ latest(item).visible_roles.map(displayRole).join('、') }}</small>
          <div v-if="!simple"><button type="button" class="btn btn-secondary btn-sm" @click="edit(item, 'evidence')">建立新版本</button><button type="button" class="btn btn-ghost btn-sm" :data-testid="item.status === 'active' ? 'deactivate-evidence-button' : 'reactivate-evidence-button'" @click="toggle(item, 'evidence')">{{ item.status === 'active' ? '停用' : '重新啟用' }}</button></div>
        </article>
      </section>

      <section v-if="!simple" class="materials-section">
        <h3>{{ vocab.notePlural }}（{{ materials.notes.filter(item => item.status === 'active').length }}）</h3>
        <article v-for="item in materials.notes" :key="item.id" class="material-card" :data-status="item.status" :data-material-id="item.id" data-testid="case-note-card">
          <header><strong>{{ latest(item).title }}</strong><span>v{{ item.active_version }} · {{ item.status === 'active' ? '使用中' : '已停用' }}</span></header>
          <p>{{ latest(item).content }}</p>
          <small>可見：{{ latest(item).visible_roles.map(displayRole).join('、') }}</small>
          <div><button type="button" class="btn btn-secondary btn-sm" @click="edit(item, 'note')">建立新版本</button><button type="button" class="btn btn-ghost btn-sm" :data-testid="item.status === 'active' ? 'deactivate-note-button' : 'reactivate-note-button'" @click="toggle(item, 'note')">{{ item.status === 'active' ? '停用' : '重新啟用' }}</button></div>
        </article>
      </section>

      <form v-if="!simple" class="material-form" data-testid="case-material-form" @submit.prevent="saveMaterial">
        <h3>{{ editingId ? '建立新版本' : formKind === 'evidence' ? vocab.addItem : vocab.addNote }}</h3>
        <div v-if="!editingId" class="segmented"><button type="button" :class="{ active: formKind === 'evidence' }" @click="formKind = 'evidence'">{{ vocab.itemPlural }}</button><button type="button" :class="{ active: formKind === 'note' }" @click="formKind = 'note'">{{ vocab.notePlural }}</button></div>
        <label>標題<input v-model="form.title" :disabled="loading" /></label>
        <label>內容<textarea v-model="form.content" :disabled="loading" /></label>
        <fieldset><legend>可見角色</legend><label v-for="participant in participants" :key="participant.role_id"><input v-model="form.visibleRoles" type="checkbox" :value="participant.role_id" />{{ displayRole(participant.role_id) }}</label></fieldset>
        <p v-if="localError" class="error">{{ localError }}</p>
        <div><button type="submit" class="btn btn-primary" :disabled="loading || !form.title.trim() || !form.content.trim() || !form.visibleRoles.length">{{ editingId ? '保存新版本' : '新增' }}</button><button v-if="editingId" type="button" class="btn btn-secondary" @click="clearForm">取消</button></div>
      </form>
    </template>
    <p v-else-if="!materialsLoadError" class="empty-state">{{ vocab.loading }}</p>
  </div>
</template>

<style scoped>
.materials-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.attachment-upload-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.attachment-upload-list li {
  display: grid;
  grid-template-columns: 1fr auto auto auto;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  font-size: 0.9em;
  min-width: 0;
}

.attachment-upload-list li[data-status='done'] {
  background: var(--color-completed-tint);
}

.attachment-upload-list li[data-status='error'] {
  background: var(--color-failed-tint);
}

.attachment-upload-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-upload-state {
  color: var(--color-text-muted);
  font-size: 0.85em;
}

.attachment-upload-list li[data-status='error'] small {
  grid-column: 1 / -1;
}

.materials-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.materials-section h3 {
  margin: 0;
  font-size: 0.95em;
}

.materials-attachment-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.materials-attachment-row {
  min-width: 0;
}

.materials-attachment-row a {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  text-decoration: none;
  color: inherit;
}

.materials-attachment-row a:hover {
  border-color: var(--color-border-strong);
}

.materials-attachment-row strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.materials-attachment-row small {
  flex: none;
  color: var(--color-text-muted);
}

.materials-impact-warning {
  padding: 10px 12px;
  border: 1px solid rgba(245, 178, 66, 0.5);
  border-radius: 8px;
  background: rgba(245, 178, 66, 0.1);
}

.materials-impact-warning p {
  margin: 4px 0 0;
}

.material-card {
  padding: 8px 10px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.material-card header {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.material-card p {
  margin: 0;
  white-space: pre-wrap;
}

.material-card small {
  opacity: 0.7;
}

.material-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.material-form h3 {
  margin: 0;
}

.material-form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.9em;
}

.material-form fieldset {
  border: none;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.material-form legend {
  font-size: 0.9em;
}

.segmented {
  display: flex;
  gap: 4px;
}

.segmented button {
  padding: 4px 10px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: none;
  cursor: pointer;
}

.segmented button.active {
  background: var(--color-surface-muted);
}

.error {
  color: var(--color-danger);
  font-size: 0.9em;
}

.empty-state {
  color: var(--color-text-muted);
}
</style>
