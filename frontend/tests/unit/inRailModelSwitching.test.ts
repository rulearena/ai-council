import assert from 'node:assert/strict'
import test from 'node:test'

import {
  projectMeetingWorkspace,
  isSameModelAssignment,
  applyOptimisticModelUpdate,
  replaceServerParticipantModels,
} from '../../src/meetingWorkspace.ts'

// ── Fixtures ─────────────────────────────────────────────────────────────────

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

// ── Workspace projection tests ────────────────────────────────────────────────

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

test('projection reflects role states independent of model assignments', () => {
  const result = projectMeetingWorkspace({
    meeting: baseMeeting as any,
    mode: baseMode as any,
    eventRoleIdToSeatId: (r) => r,
  })

  for (const role of result.roles) {
    assert.ok(['waiting', 'thinking', 'completed', 'failed'].includes(role.state),
      `Role ${role.roleId} has valid state: ${role.state}`)
  }
})

// ── isSameModelAssignment ─────────────────────────────────────────────────────
// These are the REAL guard checks used by useCouncil.updateSelectedModel.
// If this function breaks, every call site that prevents redundant saves breaks.

test('isSameModelAssignment returns true when current model equals target', () => {
  const models = { Advisor: 'gpt-4o', Critic: 'claude-3' }
  assert.ok(isSameModelAssignment(models, 'Advisor', 'gpt-4o'))
})

test('isSameModelAssignment returns false when current model differs from target', () => {
  const models = { Advisor: 'gpt-4o', Critic: 'claude-3' }
  assert.ok(!isSameModelAssignment(models, 'Advisor', 'gemini-pro'))
})

test('isSameModelAssignment returns false for unknown role', () => {
  const models = { Advisor: 'gpt-4o' }
  assert.ok(!isSameModelAssignment(models, 'Unknown', 'gpt-4o'))
})

test('isSameModelAssignment treats empty-string model as a real value', () => {
  const models = { Advisor: '' }
  assert.ok(isSameModelAssignment(models, 'Advisor', ''))
  assert.ok(!isSameModelAssignment(models, 'Advisor', 'gpt-4o'))
})

// ── applyOptimisticModelUpdate ────────────────────────────────────────────────
// This is the REAL state transition used by useCouncil.updateSelectedModel
// for both the no-meeting path (direct save) and the with-meeting path
// (optimistic update before API call).

test('applyOptimisticModelUpdate sets the target role model', () => {
  const models = { Advisor: 'gpt-4o', Critic: 'claude-3' }
  const next = applyOptimisticModelUpdate(models, 'Advisor', 'gemini-pro')
  assert.equal(next.Advisor, 'gemini-pro')
  assert.equal(next.Critic, 'claude-3', 'Other roles untouched')
})

test('applyOptimisticModelUpdate does not mutate the original object', () => {
  const models = { Advisor: 'gpt-4o', Critic: 'claude-3' }
  const next = applyOptimisticModelUpdate(models, 'Advisor', 'gemini-pro')
  assert.equal(models.Advisor, 'gpt-4o', 'Original Advisor unchanged')
  assert.notEqual(models, next, 'Different object reference')
})

test('applyOptimisticModelUpdate adds a new role key if not already present', () => {
  const models = { Advisor: 'gpt-4o' }
  const next = applyOptimisticModelUpdate(models, 'Critic', 'claude-3')
  assert.equal(next.Advisor, 'gpt-4o')
  assert.equal(next.Critic, 'claude-3')
})

// ── replaceServerParticipantModels ────────────────────────────────────────────
// This is the REAL replacement logic used by useCouncil.updateSelectedModel after
// a successful API response. It re-syncs the client state from the server.

test('replaceServerParticipantModels overwrites all roles from server response', () => {
  const current = { Advisor: 'gpt-4o', Critic: 'claude-3' }
  const participants = [
    { role_id: 'Advisor', model_config_id: 'gemini-pro' },
    { role_id: 'Critic', model_config_id: 'llama-3' },
  ]
  const result = replaceServerParticipantModels(current, participants)
  assert.deepEqual(result, { Advisor: 'gemini-pro', Critic: 'llama-3' })
})

test('replaceServerParticipantModels handles null model_config_id as empty string', () => {
  const current = { Advisor: 'gpt-4o' }
  const participants = [
    { role_id: 'Advisor', model_config_id: null },
  ]
  const result = replaceServerParticipantModels(current, participants)
  assert.equal(result.Advisor, '')
})

test('replaceServerParticipantModels can add roles from server not in current', () => {
  const current = { Advisor: 'gpt-4o' }
  const participants = [
    { role_id: 'Advisor', model_config_id: 'gpt-4o' },
    { role_id: 'Critic', model_config_id: 'claude-3' },
  ]
  const result = replaceServerParticipantModels(current, participants)
  assert.deepEqual(result, { Advisor: 'gpt-4o', Critic: 'claude-3' })
})

test('replaceServerParticipantModels drops roles from current not in server response', () => {
  const current = { Advisor: 'gpt-4o', Critic: 'claude-3', Judge: 'gemini-pro' }
  const participants = [
    { role_id: 'Advisor', model_config_id: 'gpt-4o' },
    { role_id: 'Critic', model_config_id: 'claude-3' },
  ]
  const result = replaceServerParticipantModels(current, participants)
  assert.deepEqual(result, { Advisor: 'gpt-4o', Critic: 'claude-3' })
  assert.equal((result as any).Judge, undefined, 'Judge removed — server is authoritative')
  assert.deepEqual(current, { Advisor: 'gpt-4o', Critic: 'claude-3', Judge: 'gemini-pro' },
    'Current model state is not mutated')
  assert.deepEqual(participants, [
    { role_id: 'Advisor', model_config_id: 'gpt-4o' },
    { role_id: 'Critic', model_config_id: 'claude-3' },
  ], 'Server participants are not mutated')
})

// ── Integration: end-to-end model switch logic ────────────────────────────────
// Simulates the full updateSelectedModel flow (guard → optimistic → merge)
// using the REAL extracted functions, proving they compose correctly.

test('full model switch: guard passes → optimistic applied → server replacement overwrites', () => {
  const initial = { Blue: 'mock-fast', Red: 'mock-fast', Judge: 'mock-fast' }

  // Step 1: guard check — should NOT skip
  assert.ok(!isSameModelAssignment(initial, 'Blue', 'mock-slow'), 'Guard allows the change')

  // Step 2: optimistic update — Blue changes, others stay
  const optimistic = applyOptimisticModelUpdate(initial, 'Blue', 'mock-slow')
  assert.equal(optimistic.Blue, 'mock-slow', 'Blue updated optimistically')
  assert.equal(optimistic.Red, 'mock-fast', 'Red untouched')
  assert.equal(optimistic.Judge, 'mock-fast', 'Judge untouched')

  // Step 3: server response — Blue was rejected, server keeps mock-fast
  const serverParticipants = [
    { role_id: 'Blue', model_config_id: 'mock-fast' },
    { role_id: 'Red', model_config_id: 'mock-fast' },
    { role_id: 'Judge', model_config_id: 'mock-fast' },
  ]
  const finalState = replaceServerParticipantModels(optimistic, serverParticipants)
  assert.equal(finalState.Blue, 'mock-fast', 'Blue reverted to server value')
  assert.equal(finalState.Red, 'mock-fast', 'Red unchanged')
  assert.equal(finalState.Judge, 'mock-fast', 'Judge unchanged')
})

test('full model switch: guard blocks redundant same-model call', () => {
  const current = { Blue: 'mock-fast', Red: 'mock-fast' }
  assert.ok(isSameModelAssignment(current, 'Blue', 'mock-fast'),
    'Same-model guard triggers — no state change should occur')
  // If the guard were broken, the optimistic update would still produce
  // the same state, but the API call would be wasted:
  const wouldBeNoOp = applyOptimisticModelUpdate(current, 'Blue', 'mock-fast')
  assert.deepEqual(wouldBeNoOp, current, 'Optimistic update is a no-op for same model')
})
