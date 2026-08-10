import { DEFAULT_MODE_ID } from './modes'

export type ModelConfig = {
  id: string
  adapter: string
  base_url: string | null
  model: string | null
  api_key_env: string | null
  supports_json_mode: boolean
  extra_body: Record<string, unknown>
  pricing: ModelPricing | null
  command: string[] | null
  timeout_seconds: number
  status: 'unknown' | 'available' | 'unavailable'
  health_checked_at: string | null
  health_error: string | null
}

export type ModelTestResult = {
  status: 'available' | 'unavailable'
  tested_at: string
  error?: string
}

export type AvailableModelsResponse = {
  models: string[]
}

export type ModelDiscoveryPreviewPayload = {
  adapter: string
  base_url?: string | null
  api_key_env?: string | null
}

export type CaseFileLimits = {
  per_file_chars: number
  total_chars: number
}

export type Meeting = {
  meeting_id: string
  title: string
  goal: string | null
  requires_goal: boolean
  status: 'open' | 'closed' | 'cancelled'
  activity_status: 'idle' | 'running' | 'waiting' | 'completed' | 'failed' | 'closed' | 'cancelled'
  created_at: string
  updated_at: string
  last_step_id: string | null
  token_usage: TokenUsage
  estimated_cost: EstimatedCost | null
  tags: string[]
  pinned: boolean
  mode_id: string
  case_type?: 'civil' | 'criminal' | null
  settings_revision: number
  scene: string
  deliberation: DeliberationSummary
  participants: MeetingParticipant[]
  case_files?: CaseFile[]
  events?: MeetingEvent[]
  courtroom: CourtroomProjection | null
  case_materials?: CaseMaterials
  attachments_summary?: AttachmentSummary
  chatroom_sources?: ChatroomSource[]
}

export type ChatroomSource = {
  source_ref: string
  label: string
  kind: 'attachment' | 'evidence'
  active: boolean
  readable: boolean
  reader_ref: string
  available_segment_refs: string[]
  presentation_discriminator?: string
  visible_roles?: string[]
  size?: number
  created_at?: string | null
}

export type AttachmentSummary = {
  count: number
  total_bytes: number
}

export type DeliberationSummary = {
  active_epoch_id: string
  active_epoch_number: number
  epoch_count: number
}

export type DeliberationEpoch = {
  id: string
  number: number
  reason: string | null
  scope: 'current_issue' | 'all_deliberation' | 'rebuild_issues' | null
  issue_id: string | null
  implicit: boolean
  event_count: number
  materials_revision?: number | null
}

export type Deliberations = {
  active_epoch_id: string
  active_epoch_number: number
  epochs: DeliberationEpoch[]
}

export type CaseMaterialVersion = {
  version: number
  title: string
  content: string
  visible_roles: string[]
  size: number
  created_at: string
  source_event_id: string | null
}

export type VersionedCaseMaterial = {
  id: string
  status: 'active' | 'inactive'
  active_version: number
  versions: CaseMaterialVersion[]
  evidence_index?: number
  citation_anchor?: string
}

export type CaseMaterials = {
  schema_version: number
  revision: number
  pending_impact: { deliberation_epoch_id: string; reason: string } | null
  evidence: VersionedCaseMaterial[]
  notes: VersionedCaseMaterial[]
  revision_history: Array<Record<string, unknown>>
}

export type MeetingSettingsPayload = {
  expected_revision: number
  title: string
  goal: string
  case_type: 'civil' | 'criminal' | null
  scene: string
  participant_models: Record<string, string>
}

export type CaseMaterialPayload = {
  revision: number
  title: string
  content: string
  visible_roles: string[]
}

export type CourtroomIssueProjection = {
  id: string
  title: string
  position: number
  status: 'pending' | 'arguments-in-progress' | 'awaiting-ruling' | 'ruled' | 'failed'
  failed_step_id?: string
  failed_phase?: 'charge' | 'defense' | 'rebuttal' | 'ruling'
  failed_phase_display?: string
  failure_kind?: 'parse_error' | 'timeout' | 'adapter_error' | 'configuration_error' | 'interrupted'
  ruling?: CourtroomRuling
}

export type CourtroomRuling = {
  outcome: 'proponent-wins' | 'respondent-wins' | 'partially-upheld' | 'insufficient-evidence'
  reasoning: string
  evidence_refs: string[]
  unresolved_questions: string[]
}

export type CourtroomCivilFinal = {
  summary: string
  claims: Array<{
    claim: string
    outcome: string
    reasoning: string
    evidence_refs: string[]
    relief: { obligation: string; monetary_amount: string | null; calculation_basis: string | null }
  }>
  unresolved_questions: string[]
}

export type CourtroomCriminalFinal = {
  summary: string
  charges: Array<{
    charge: string
    decision: string
    reasoning: string
    evidence_refs: string[]
  }>
  sentencing_factors: string[]
  unresolved_questions: string[]
}

export type CourtroomProjection = {
  schema_version: number
  revision: number
  status: 'not-configured' | 'draft' | 'confirmed'
  issues: CourtroomIssueProjection[]
  current_issue_id: string | null
  final_status: 'not-ready' | 'ready' | 'failed' | 'completed'
  failed_step_id?: string
  available_actions: string[]
  case_type: 'civil' | 'criminal' | null
  requires_case_type: boolean
}

export type CaseFile = {
  id: string
  evidence_index: number
  citation_anchor: string
  title: string
  content?: string
  visible_roles: string[]
  size: number
}

export type MeetingParticipant = {
  role_id: string
  name: string
  color: string
  kind: string
  portrait: string | null
  model_config_id: string | null
  display_name: string
  instance_prompt: string | null
  model_assignment_source: 'metadata' | 'latest-event' | 'default' | 'unavailable'
  model_assignment_warning: string | null
  persona_summary?: string
}

export type BackendModeRole = {
  id: string
  name: string
  color: string
  kind: string
  portrait: string | null
  output_schema: string
  persona_summary?: string
}
export type BackendModeStep = { role: string; template: string; label: string }
export type BackendModeInput = { id: string; label: string; kind: string }
export type BackendModeFanout = {
  role: string
  template: string
  label: string
  min_instances: number
  max_instances: number
  instance_prompt: boolean
}
export type BackendModeSynthesis = {
  role: string
  template: string
  label: string
  anonymize_inputs?: boolean
}
export type BackendModeDefinition = {
  id: string
  name: string
  category: string
  tagline: string
  when_to_use: string
  sop: string[]
  default_scene: string
  inputs: BackendModeInput[]
  roles: BackendModeRole[]
  steps?: BackendModeStep[]
  fanout?: BackendModeFanout
  synthesis?: BackendModeSynthesis
  available: boolean
}

export type MeetingEvent = {
  event_id: string
  meeting_id: string
  step_id: string
  role: string
  attempt: number
  status: string
  base_step_id?: string
  round?: number
  content?: string
  created_at?: string
  interaction_type?:
    | 'directed-role-instruction'
    | 'directed-role-response'
    | 'role-sequence-response'
    | 'meeting-goal-changed'
    | 'courtroom-issue-draft'
    | 'courtroom-issue-phase'
    | 'courtroom-final-verdict'
    | 'courtroom-operation-reservation'
  docket_revision?: number
  issue_id?: string
  issue_phase?: 'charge' | 'defense' | 'rebuttal' | 'ruling'
  case_type?: 'civil' | 'criminal'
  role_display?: string
  phase_display?: string
  target_role_id?: string
  in_response_to_event_id?: string
  directed_sequence?: number
  sequence?: number
  sequence_index?: number
  model_config_id?: string
  adapter?: string
  prompt_template_name?: string
  prompt_template_hash?: string
  output_schema_hash?: string
  output_schema_id?: string
  prompt_messages?: Array<{ role: string; content: string }>
  raw_output?: string
  parsed_output?: RoleOutput
  token_usage?: TokenUsage
  started_at?: string
  completed_at?: string
  duration_ms?: number
  failure_kind?: 'parse_error' | 'timeout' | 'adapter_error' | 'configuration_error' | 'interrupted'
  retry_scheduled?: boolean
  result_discarded?: boolean
  adapter_stdout_excerpt?: string
  adapter_stderr_excerpt?: string
  error?: string
  corrects_event_id?: string
  file_id?: string
  filename?: string
  size?: number
  mime_type?: string
  extension?: string
  removed?: boolean
}

export type MeetingStreamEvent = {
  type: 'token_delta'
  meeting_id: string
  step_id: string
  role: string
  attempt: number
  content: string
  base_step_id?: string
  round?: number
}

export type TokenUsage = {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export type ModelPricing = {
  currency: string
  input_per_1m_tokens: number
  output_per_1m_tokens: number
}

export type EstimatedCost = {
  currency: string
  amount: number
}

export type LegacyRoleOutput = {
  summary: string
  arguments: Array<{ title: string; detail: string }>
  risks: Array<{ title: string; detail: string }>
  recommendation: string
}

export type StructuredVerdict = {
  summary: string
  decision: 'approve' | 'approve-with-conditions' | 'reject' | 'insufficient-evidence'
  findings: Array<{ title: string; detail: string; evidence_refs: string[] }>
  risks: Array<{ title: string; detail: string; evidence_refs: string[] }>
  recommendation: string
  conditions: string[]
  unresolved_questions: string[]
}

export type RoleOutput = LegacyRoleOutput | StructuredVerdict

export type MeetingEventStreamMessage = {
  type: 'snapshot' | 'update'
  events: MeetingEvent[]
  stream_events: MeetingStreamEvent[]
  activity_status: Meeting['activity_status']
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:5009'

// Thrown by every *Json helper below on a non-2xx response. `detail` preserves the
// response body's `detail` field verbatim - for /models write endpoints that's a 422
// per-field array (`[{field, message}]`, see backend/ai_council/api.py's
// RequestValidationError handler and save_model_or_422), which ModelManagerPanel
// needs to show inline per-field errors rather than a single flattened message.
export class ApiError extends Error {
  readonly status: number
  readonly detail?: unknown

  constructor(message: string, status: number, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function readErrorDetail(response: Response): Promise<unknown> {
  try {
    const body = await response.json()
    return body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : undefined
  } catch {
    return undefined
  }
}

export type ModelConfigPayload = {
  adapter: string
  base_url?: string | null
  model?: string | null
  api_key_env?: string | null
  supports_json_mode?: boolean
  extra_body?: Record<string, unknown>
  pricing?: ModelPricing | null
  command?: string[] | null
  timeout_seconds?: number
}

export async function getModels(): Promise<ModelConfig[]> {
  return getJson('/models')
}

export async function createModel(id: string, payload: ModelConfigPayload): Promise<ModelConfig> {
  return postJson('/models', { id, ...payload })
}

export async function updateModel(id: string, payload: ModelConfigPayload): Promise<ModelConfig> {
  return putJson(`/models/${id}`, payload)
}

export async function deleteModel(id: string): Promise<{ id: string; warning: string | null }> {
  return deleteJson(`/models/${id}`)
}

export async function testModel(modelId: string): Promise<ModelTestResult> {
  return postJson(`/models/${modelId}/test`, {})
}

export async function getAvailableModels(modelId: string): Promise<AvailableModelsResponse> {
  return getJson(`/models/${encodeURIComponent(modelId)}/available-models`)
}

export async function previewAvailableModels(
  payload: ModelDiscoveryPreviewPayload,
): Promise<AvailableModelsResponse> {
  return postJson('/models/available-models', payload)
}

export async function getModes(): Promise<BackendModeDefinition[]> {
  return getJson('/modes')
}

export async function getCaseFileLimits(): Promise<CaseFileLimits> {
  return getJson('/case-file-limits')
}

export async function getMeetings(query?: string): Promise<Meeting[]> {
  const trimmed = query?.trim()
  return getJson(trimmed ? `/meetings?q=${encodeURIComponent(trimmed)}` : '/meetings')
}

export async function createMeeting(
  title: string,
  goal: string,
  options?: {
    modeId?: string
    caseType?: 'civil' | 'criminal'
    inputs?: Record<string, string>
    participants?: Array<{
      role_id: string
      model_config_id?: string | null
      display_name?: string | null
      instance_prompt?: string | null
    }>
    caseFiles?: Array<{
      title: string
      content: string
      visible_roles: string[]
    }>
  },
): Promise<Meeting> {
  return postJson('/meetings', {
    title,
    goal,
    mode_id: options?.modeId ?? DEFAULT_MODE_ID,
    case_type: options?.caseType,
    inputs: options?.inputs ?? {},
    participants: options?.participants ?? [],
    case_files: options?.caseFiles ?? [],
  })
}

export async function updateMeetingDetails(
  meetingId: string,
  title: string,
  goal: string,
): Promise<Meeting> {
  return putJson(`/meetings/${meetingId}/details`, { title, goal })
}

export async function updateMeetingSettings(
  meetingId: string,
  payload: MeetingSettingsPayload,
): Promise<Meeting> {
  return putJson(`/meetings/${meetingId}/settings`, payload)
}

export async function getMeeting(meetingId: string): Promise<Meeting> {
  return getJson(`/meetings/${meetingId}`)
}

export async function getDeliberations(meetingId: string): Promise<Deliberations> {
  return getJson(`/meetings/${meetingId}/deliberations`)
}

export async function restartDeliberation(
  meetingId: string,
  scope: 'current_issue' | 'all_deliberation' | 'rebuild_issues',
  reason: string,
  issueId?: string,
): Promise<Meeting> {
  return postJson(`/meetings/${meetingId}/deliberations/restart`, {
    scope,
    reason,
    issue_id: issueId,
  })
}

export async function getCaseMaterials(meetingId: string, revision?: number): Promise<CaseMaterials> {
  const query = revision === undefined ? '' : `?revision=${encodeURIComponent(revision)}`
  return getJson(`/meetings/${meetingId}/materials${query}`)
}

export async function addCaseEvidence(meetingId: string, payload: CaseMaterialPayload): Promise<CaseMaterials> {
  return postJson(`/meetings/${meetingId}/materials/evidence`, payload)
}

export async function addCaseEvidenceVersion(meetingId: string, evidenceId: string, payload: CaseMaterialPayload): Promise<CaseMaterials> {
  return postJson(`/meetings/${meetingId}/materials/evidence/${encodeURIComponent(evidenceId)}/versions`, payload)
}

export async function setCaseEvidenceActive(meetingId: string, evidenceId: string, revision: number, active: boolean): Promise<CaseMaterials> {
  return postJson(`/meetings/${meetingId}/materials/evidence/${encodeURIComponent(evidenceId)}/${active ? 'reactivate' : 'deactivate'}`, { revision })
}

export async function addCaseNote(meetingId: string, payload: CaseMaterialPayload): Promise<CaseMaterials> {
  return postJson(`/meetings/${meetingId}/materials/notes`, payload)
}

export async function addCaseNoteVersion(meetingId: string, noteId: string, payload: CaseMaterialPayload): Promise<CaseMaterials> {
  return postJson(`/meetings/${meetingId}/materials/notes/${encodeURIComponent(noteId)}/versions`, payload)
}

export async function setCaseNoteActive(meetingId: string, noteId: string, revision: number, active: boolean): Promise<CaseMaterials> {
  return postJson(`/meetings/${meetingId}/materials/notes/${encodeURIComponent(noteId)}/${active ? 'reactivate' : 'deactivate'}`, { revision })
}

export async function promoteMessageToCaseNote(
  meetingId: string,
  eventId: string,
  revision: number,
  title: string,
  visibleRoles: string[],
): Promise<CaseMaterials> {
  return postJson(`/meetings/${meetingId}/messages/${encodeURIComponent(eventId)}/promote-to-note`, {
    revision,
    title,
    visible_roles: visibleRoles,
  })
}

export async function startMeeting(meetingId: string): Promise<void> {
  await postJson(`/meetings/${meetingId}/start`, {})
}

export async function draftCourtroomIssues(meetingId: string, revision: number): Promise<void> {
  await postJson(`/meetings/${meetingId}/courtroom/issues/draft`, { revision })
}

export async function updateCourtroomCaseType(
  meetingId: string,
  caseType: 'civil' | 'criminal',
): Promise<Meeting> {
  return putJson(`/meetings/${meetingId}/courtroom/case-type`, { case_type: caseType })
}

export async function replaceCourtroomIssues(
  meetingId: string,
  revision: number,
  issues: Array<{ id?: string; title: string }>,
): Promise<Meeting> {
  return putJson(`/meetings/${meetingId}/courtroom/issues`, { revision, issues })
}

export async function confirmCourtroomIssues(meetingId: string, revision: number): Promise<Meeting> {
  return postJson(`/meetings/${meetingId}/courtroom/issues/confirm`, { revision })
}

export async function runCourtroomIssueArguments(meetingId: string, issueId: string): Promise<void> {
  await postJson(`/meetings/${meetingId}/courtroom/issues/${encodeURIComponent(issueId)}/arguments`, {})
}

export async function runCourtroomIssueRuling(meetingId: string, issueId: string): Promise<void> {
  await postJson(`/meetings/${meetingId}/courtroom/issues/${encodeURIComponent(issueId)}/ruling`, {})
}

export async function runCourtroomFinalVerdict(meetingId: string): Promise<void> {
  await postJson(`/meetings/${meetingId}/courtroom/final-verdict`, {})
}

export async function cancelMeeting(meetingId: string): Promise<void> {
  await postJson(`/meetings/${meetingId}/cancel`, {})
}

export async function closeMeeting(meetingId: string): Promise<void> {
  await postJson(`/meetings/${meetingId}/close`, {})
}

export async function reopenMeeting(meetingId: string): Promise<void> {
  await postJson(`/meetings/${meetingId}/reopen`, {})
}

export async function deleteMeeting(meetingId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/meetings/${meetingId}`, { method: 'DELETE' })
  if (!response.ok) throw new Error(`DELETE /meetings/${meetingId} failed: ${response.status}`)
}

export async function updateMeetingTags(meetingId: string, tags: string[]): Promise<Meeting> {
  return putJson(`/meetings/${meetingId}/tags`, { tags })
}

export async function updateMeetingPinned(meetingId: string, pinned: boolean): Promise<Meeting> {
  return putJson(`/meetings/${meetingId}/pinned`, { pinned })
}

export async function updateMeetingParticipantModels(
  meetingId: string,
  models: Record<string, string>,
): Promise<Meeting> {
  return putJson(`/meetings/${meetingId}/participant-models`, { models })
}

export async function addMeetingMessage(
  meetingId: string,
  content: string,
): Promise<MeetingEvent> {
  return postJson(`/meetings/${meetingId}/messages`, { content })
}

export type ChatMention = {
  token_id: string
  role_id: string
  display_text: string
  start: number
  end: number
}

export type ChatSourceToken = {
  token_id: string
  source_ref: string
  display_text: string
  start: number
  end: number
}

export type ChatMentionWarning = {
  code: 'IGNORED_INVALID_MENTION'
  display_text: string
}

export type ChatroomAcceptedResponse = {
  status: 'accepted'
  meeting_id: string
  target_role_ids: string[]
  source_refs: string[]
  warnings: ChatMentionWarning[]
}

export async function sendChatMessage(
  meetingId: string,
  content: string,
  quotedEventId?: string,
): Promise<MeetingEvent> {
  return postJson(`/meetings/${meetingId}/messages`, {
    content,
    ...(quotedEventId ? { quoted_event_id: quotedEventId } : {}),
  })
}

export async function sendChatMention(
  meetingId: string,
  content: string,
  mentions: ChatMention[],
  sourceTokens: ChatSourceToken[],
  sourceRefs: string[],
  quotedEventId?: string,
): Promise<ChatroomAcceptedResponse> {
  return postJson(`/meetings/${meetingId}/chat/mention`, {
    content,
    mentions,
    source_tokens: sourceTokens,
    source_refs: sourceRefs,
    quoted_event_id: quotedEventId ?? null,
  })
}

export async function correctMeetingMessage(
  meetingId: string,
  eventId: string,
  content: string,
): Promise<MeetingEvent> {
  return postJson(`/meetings/${meetingId}/messages/${eventId}/correct`, { content })
}

/**
 * Upload a chat attachment. Multipart form-data with a single `file` part.
 * Resolves to the appended `attachment-added` metadata event. In chatroom mode
 * .txt/.md files are accepted here too and are mirrored into case-files by the
 * backend; in other modes they are rejected with a 400 (they keep going through
 * the case-files form instead).
 */
export async function uploadAttachment(meetingId: string, file: File): Promise<MeetingEvent> {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(`${API_BASE}/meetings/${meetingId}/attachments`, {
    method: 'POST',
    body: formData,
  })
  if (!response.ok) {
    throw new ApiError(`POST /meetings/${meetingId}/attachments failed: ${response.status}`, response.status, await readErrorDetail(response))
  }
  return response.json()
}

export function attachmentDownloadUrl(meetingId: string, fileId: string): string {
  return `${API_BASE}/meetings/${meetingId}/attachments/${encodeURIComponent(fileId)}`
}

export async function deleteAttachment(meetingId: string, fileId: string): Promise<MeetingEvent> {
  const response = await fetch(`${API_BASE}/meetings/${meetingId}/attachments/${encodeURIComponent(fileId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new ApiError(
      `DELETE /meetings/${meetingId}/attachments/${fileId} failed: ${response.status}`,
      response.status,
      await readErrorDetail(response),
    )
  }
  return response.json()
}

export async function requestRoleResponse(
  meetingId: string,
  role: string,
  instruction: string,
): Promise<void> {
  await postJson(`/meetings/${meetingId}/roles/${role}/respond`, { instruction })
}

export async function requestRoleSequence(
  meetingId: string,
  roles: string[],
): Promise<void> {
  await postJson(`/meetings/${meetingId}/sequences`, { roles })
}

export async function retryStep(
  meetingId: string,
  stepId: string,
): Promise<void> {
  await postJson(`/meetings/${meetingId}/steps/${stepId}/retry`, {})
}

export async function getTranscript(meetingId: string, epoch = 'current'): Promise<string> {
  const response = await fetch(`${API_BASE}/meetings/${meetingId}/transcript.md?epoch=${encodeURIComponent(epoch)}`)
  if (!response.ok) throw new ApiError(`Transcript request failed: ${response.status}`, response.status, await readErrorDetail(response))
  return response.text()
}

export function subscribeMeetingEvents(
  meetingId: string,
  onMessage: (message: MeetingEventStreamMessage) => void,
  onError: () => void,
): () => void {
  const base = new URL(API_BASE)
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:'
  base.pathname = `/meetings/${meetingId}/events`
  base.search = ''
  const socket = new WebSocket(base)
  socket.addEventListener('message', (event) => {
    onMessage(JSON.parse(event.data) as MeetingEventStreamMessage)
  })
  socket.addEventListener('error', onError)
  return () => socket.close()
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    throw new ApiError(`GET ${path} failed: ${response.status}`, response.status, await readErrorDetail(response))
  }
  return response.json()
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new ApiError(`POST ${path} failed: ${response.status}`, response.status, await readErrorDetail(response))
  }
  return response.json()
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new ApiError(`PUT ${path} failed: ${response.status}`, response.status, await readErrorDetail(response))
  }
  return response.json()
}

async function deleteJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method: 'DELETE' })
  if (!response.ok) {
    throw new ApiError(`DELETE ${path} failed: ${response.status}`, response.status, await readErrorDetail(response))
  }
  return response.json()
}

export function transcriptDownloadUrl(meetingId: string, epoch = 'current'): string {
  return `${API_BASE}/meetings/${meetingId}/transcript.md?epoch=${encodeURIComponent(epoch)}`
}
