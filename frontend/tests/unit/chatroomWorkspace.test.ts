import assert from 'node:assert/strict'
import test from 'node:test'

import {
  projectMeetingWorkspace,
  shouldShowChatroomComposer,
} from '../../src/meetingWorkspace.ts'

test('shouldShowChatroomComposer returns true only for chatroom category', () => {
  assert.equal(shouldShowChatroomComposer('chatroom'), true)
  assert.equal(shouldShowChatroomComposer('parallel'), false)
  assert.equal(shouldShowChatroomComposer('relay'), false)
  assert.equal(shouldShowChatroomComposer('debate'), false)
})

const chatroomMode = {
  id: 'chatroom',
  category: 'chatroom',
  roles: [{ id: 'Analyst', name: '分析師' }, { id: 'Critic', name: '批評者' }],
}

const chatroomMeeting = {
  meeting_id: 'meeting-chat',
  mode_id: 'chatroom',
  activity_status: 'running' as const,
  participants: [
    { role_id: 'Analyst', display_name: '分析師' },
    { role_id: 'Critic', display_name: '批評者' },
  ],
  courtroom: null,
  events: [
    {
      event_id: 'human-1', meeting_id: 'meeting-chat', step_id: 'human-message',
      role: 'Human', attempt: 1, status: 'completed', content: '請討論方案',
      created_at: '2025-01-01T00:00:00Z',
    },
    {
      event_id: 'fanout-critic', meeting_id: 'meeting-chat', step_id: 'chat-fanout-critic',
      role: 'Critic', attempt: 1, status: 'completed', content: '我認為有風險',
      created_at: '2025-01-01T00:00:01Z',
    },
    {
      event_id: 'fanout-analyst', meeting_id: 'meeting-chat', step_id: 'chat-fanout-analyst',
      role: 'Analyst', attempt: 1, status: 'completed', content: '我同意，但可以優化',
      created_at: '2025-01-01T00:00:02Z',
    },
  ],
}

test('chatroom projection preserves backend arrival order (not role-alphabetical)', () => {
  const workspace = projectMeetingWorkspace({
    meeting: chatroomMeeting,
    mode: chatroomMode,
  })

  assert.equal(workspace.family, 'conversation')
  assert.deepEqual(
    workspace.messages.map((message) => [message.id, message.roleId, message.kind]),
    [
      ['human-1', 'Human', 'human'],
      ['fanout-critic', 'Critic', 'ai'],
      ['fanout-analyst', 'Analyst', 'ai'],
    ],
  )
  assert.deepEqual(workspace.parallel, null)
})

test('chatroom projection does not re-sort when roles appear out of participant-list order', () => {
  const reversedRoleMeeting = {
    ...chatroomMeeting,
    events: [
      {
        event_id: 'human-1', meeting_id: 'meeting-chat', step_id: 'human-message',
        role: 'Human', attempt: 1, status: 'completed', content: '請討論',
      },
      {
        event_id: 'fanout-analyst', meeting_id: 'meeting-chat', step_id: 'chat-fanout-analyst',
        role: 'Analyst', attempt: 1, status: 'completed', content: '先完成的分析',
      },
      {
        event_id: 'fanout-critic', meeting_id: 'meeting-chat', step_id: 'chat-fanout-critic',
        role: 'Critic', attempt: 1, status: 'completed', content: '後完成的批評',
      },
    ],
  }

  const workspace = projectMeetingWorkspace({
    meeting: reversedRoleMeeting,
    mode: chatroomMode,
  })

  assert.deepEqual(
    workspace.messages.map((message) => [message.id, message.roleId]),
    [
      ['human-1', 'Human'],
      ['fanout-analyst', 'Analyst'],
      ['fanout-critic', 'Critic'],
    ],
  )
})

test('chatroom with empty goal produces no goal section (v-if guards it)', () => {
  const noGoalMeeting = { ...chatroomMeeting, goal: '' }
  const workspace = projectMeetingWorkspace({
    meeting: noGoalMeeting,
    mode: chatroomMode,
  })
  assert.equal(workspace.family, 'conversation')
})

test('chatroom parallel is always null (no step-based progress)', () => {
  const workspace = projectMeetingWorkspace({
    meeting: chatroomMeeting,
    mode: chatroomMode,
  })
  assert.equal(workspace.parallel, null)
})
