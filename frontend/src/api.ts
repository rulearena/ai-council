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

export type Meeting = {
  meeting_id: string
  topic: string
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
  participants: MeetingParticipant[]
  case_files?: CaseFile[]
  events?: MeetingEvent[]
}

export type CaseFile = {
  id: string
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
}

export type BackendModeRole = { id: string; name: string; color: string; kind: string; portrait: string | null }
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
  interaction_type?: 'directed-role-response' | 'role-sequence-response'
  directed_sequence?: number
  sequence?: number
  sequence_index?: number
  model_config_id?: string
  prompt_template_name?: string
  prompt_template_hash?: string
  output_schema_hash?: string
  prompt_messages?: Array<{ role: string; content: string }>
  raw_output?: string
  parsed_output?: RoleOutput
  token_usage?: TokenUsage
  error?: string
  corrects_event_id?: string
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

export type RoleOutput = {
  summary: string
  arguments: Array<{ title: string; detail: string }>
  risks: Array<{ title: string; detail: string }>
  recommendation: string
}

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

export async function getModes(): Promise<BackendModeDefinition[]> {
  return getJson('/modes')
}

export async function getMeetings(query?: string): Promise<Meeting[]> {
  const trimmed = query?.trim()
  return getJson(trimmed ? `/meetings?q=${encodeURIComponent(trimmed)}` : '/meetings')
}

export async function createMeeting(
  topic: string,
  options?: {
    modeId?: string
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
    topic,
    mode_id: options?.modeId ?? DEFAULT_MODE_ID,
    inputs: options?.inputs ?? {},
    participants: options?.participants ?? [],
    case_files: options?.caseFiles ?? [],
  })
}

export async function getMeeting(meetingId: string): Promise<Meeting> {
  return getJson(`/meetings/${meetingId}`)
}

export async function startMeeting(
  meetingId: string,
  models: Record<string, string>,
): Promise<void> {
  await postJson(`/meetings/${meetingId}/start`, { models })
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

export async function addMeetingMessage(
  meetingId: string,
  content: string,
): Promise<MeetingEvent> {
  return postJson(`/meetings/${meetingId}/messages`, { content })
}

export async function correctMeetingMessage(
  meetingId: string,
  eventId: string,
  content: string,
): Promise<MeetingEvent> {
  return postJson(`/meetings/${meetingId}/messages/${eventId}/correct`, { content })
}

export async function requestRoleResponse(
  meetingId: string,
  role: string,
  models: Record<string, string>,
): Promise<void> {
  await postJson(`/meetings/${meetingId}/roles/${role}/respond`, { models })
}

export async function requestRoleSequence(
  meetingId: string,
  roles: string[],
  models: Record<string, string>,
): Promise<void> {
  await postJson(`/meetings/${meetingId}/sequences`, { roles, models })
}

export async function retryStep(
  meetingId: string,
  stepId: string,
  models: Record<string, string>,
): Promise<void> {
  await postJson(`/meetings/${meetingId}/steps/${stepId}/retry`, { models })
}

export async function getTranscript(meetingId: string): Promise<string> {
  const response = await fetch(`${API_BASE}/meetings/${meetingId}/transcript.md`)
  if (!response.ok) throw new Error(`Transcript request failed: ${response.status}`)
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

export function transcriptDownloadUrl(meetingId: string): string {
  return `${API_BASE}/meetings/${meetingId}/transcript.md`
}
