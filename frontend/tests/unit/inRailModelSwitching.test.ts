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

test('workspace projection returns role states that model label depends on', () => {
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
