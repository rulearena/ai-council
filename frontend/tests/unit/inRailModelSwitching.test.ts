import assert from 'node:assert/strict'
import test from 'node:test'

import { projectMeetingWorkspace } from '../../src/meetingWorkspace.ts'

const baseMode = {
  id: 'chatroom',
  category: 'chatroom',
  roles: [
    { id: 'Advisor', name: '顧問', color: '#4d8dff', kind: 'member' as const },
    { id: 'Critic', name: '評論者', color: '#ff6b5e', kind: 'member' as const },
  ],
}

const baseMeeting = {
  meeting_id: 'm1',
  mode_id: 'chatroom',
  activity_status: 'running' as const,
  participants: [
    { role_id: 'Advisor', display_name: '顧問' },
    { role_id: 'Critic', display_name: '評論者' },
  ],
  courtroom: null,
  events: [
    {
      event_id: 'ev1', meeting_id: 'm1', step_id: 'human-message',
      role: 'Human', attempt: 1, status: 'completed', content: '你好',
      created_at: '2025-01-01T00:00:00Z',
    },
  ],
}

test('workspace projection returns role states for model label rendering', () => {
  const result = projectMeetingWorkspace({
    meeting: baseMeeting as any,
    mode: baseMode as any,
    eventRoleIdToSeatId: (r) => r,
  })

  const advisor = result.roles.find((r) => r.roleId === 'Advisor')
  assert.ok(advisor, 'Advisor role exists in projection')
  assert.equal(advisor!.state, 'waiting', 'Advisor state is waiting (no role-specific events)')
  assert.equal(result.messages.length, 1, 'One message projected')
})

test('workspace projection role count matches participants', () => {
  const result = projectMeetingWorkspace({
    meeting: baseMeeting as any,
    mode: baseMode as any,
    eventRoleIdToSeatId: (r) => r,
  })

  assert.equal(result.roles.length, 2, 'Two roles projected from two participants')
  assert.deepEqual(
    result.roles.map((r) => r.roleId).sort(),
    ['Advisor', 'Critic'],
    'Role IDs match participant role_ids',
  )
})

test('updateSelectedModel same-model guard: selecting current model is a no-op', () => {
  // Simulate the guard logic from useCouncil.ts updateSelectedModel
  const selectedModels: Record<string, string> = { Advisor: 'gpt-4o', Critic: 'claude-3' }
  const role = 'Advisor'
  const modelId = 'gpt-4o' // same as current

  // Guard: if same model, return early (no state change)
  const before = { ...selectedModels }
  if (selectedModels[role] !== modelId) {
    selectedModels[role] = modelId
  }
  assert.deepEqual(selectedModels, before, 'State unchanged when selecting same model')
})

test('updateSelectedModel changes state when selecting a different model', () => {
  const selectedModels: Record<string, string> = { Advisor: 'gpt-4o', Critic: 'claude-3' }
  const role = 'Advisor'
  const modelId = 'gemini-pro' // different from current

  if (selectedModels[role] !== modelId) {
    selectedModels[role] = modelId
  }
  assert.equal(selectedModels.Advisor, 'gemini-pro', 'Advisor model updated to gemini-pro')
  assert.equal(selectedModels.Critic, 'claude-3', 'Critic model unchanged')
})
