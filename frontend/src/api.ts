export type ModelConfig = {
  id: string
  adapter: string
  base_url: string | null
  model: string | null
  api_key_env: string | null
  supports_json_mode: boolean
  extra_body: Record<string, unknown>
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
  tags: string[]
  pinned: boolean
  events?: MeetingEvent[]
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

export async function getModels(): Promise<ModelConfig[]> {
  return getJson('/models')
}

export async function testModel(modelId: string): Promise<ModelTestResult> {
  return postJson(`/models/${modelId}/test`, {})
}

export async function getMeetings(query?: string): Promise<Meeting[]> {
  const trimmed = query?.trim()
  return getJson(trimmed ? `/meetings?q=${encodeURIComponent(trimmed)}` : '/meetings')
}

export async function createMeeting(topic: string): Promise<Meeting> {
  return postJson('/meetings', { topic })
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
  if (!response.ok) throw new Error(`GET ${path} failed: ${response.status}`)
  return response.json()
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`POST ${path} failed: ${response.status}`)
  return response.json()
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`PUT ${path} failed: ${response.status}`)
  return response.json()
}

export function transcriptDownloadUrl(meetingId: string): string {
  return `${API_BASE}/meetings/${meetingId}/transcript.md`
}
