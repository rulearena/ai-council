export type ModelConfig = {
  id: string
  adapter: string
  base_url: string | null
  model: string | null
  api_key_env: string | null
  supports_json_mode: boolean
  extra_body: Record<string, unknown>
  status: 'unknown' | 'available' | 'unavailable'
}

export type ModelTestResult = {
  status: 'available' | 'unavailable'
  error?: string
}

export type Meeting = {
  meeting_id: string
  topic: string
  status: 'open' | 'closed' | 'cancelled'
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
  interaction_type?: 'directed-role-response' | 'role-sequence-response'
  directed_sequence?: number
  sequence?: number
  sequence_index?: number
  model_config_id?: string
  prompt_messages?: Array<{ role: string; content: string }>
  raw_output?: string
  parsed_output?: RoleOutput
  error?: string
}

export type RoleOutput = {
  summary: string
  arguments: Array<{ title: string; detail: string }>
  risks: Array<{ title: string; detail: string }>
  recommendation: string
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export async function getModels(): Promise<ModelConfig[]> {
  return getJson('/models')
}

export async function testModel(modelId: string): Promise<ModelTestResult> {
  return postJson(`/models/${modelId}/test`, {})
}

export async function getMeetings(): Promise<Meeting[]> {
  return getJson('/meetings')
}

export async function createMeeting(topic: string): Promise<Meeting> {
  return postJson('/meetings', { topic })
}

export async function getMeeting(meetingId: string): Promise<Meeting> {
  return getJson(`/meetings/${meetingId}`)
}

export async function startMeeting(
  meetingId: string,
  models: Record<'Blue' | 'Red' | 'Judge', string>,
): Promise<void> {
  await postJson(`/meetings/${meetingId}/start`, { models })
}

export async function cancelMeeting(meetingId: string): Promise<void> {
  await postJson(`/meetings/${meetingId}/cancel`, {})
}

export async function closeMeeting(meetingId: string): Promise<void> {
  await postJson(`/meetings/${meetingId}/close`, {})
}

export async function addMeetingMessage(
  meetingId: string,
  content: string,
): Promise<MeetingEvent> {
  return postJson(`/meetings/${meetingId}/messages`, { content })
}

export async function requestRoleResponse(
  meetingId: string,
  role: 'Blue' | 'Red' | 'Judge',
  models: Record<'Blue' | 'Red' | 'Judge', string>,
): Promise<void> {
  await postJson(`/meetings/${meetingId}/roles/${role}/respond`, { models })
}

export async function requestRoleSequence(
  meetingId: string,
  roles: Array<'Blue' | 'Red' | 'Judge'>,
  models: Record<'Blue' | 'Red' | 'Judge', string>,
): Promise<void> {
  await postJson(`/meetings/${meetingId}/sequences`, { roles, models })
}

export async function getTranscript(meetingId: string): Promise<string> {
  const response = await fetch(`${API_BASE}/meetings/${meetingId}/transcript.md`)
  if (!response.ok) throw new Error(`Transcript request failed: ${response.status}`)
  return response.text()
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

export function transcriptDownloadUrl(meetingId: string): string {
  return `${API_BASE}/meetings/${meetingId}/transcript.md`
}
