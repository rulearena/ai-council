import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatAttachmentSize,
  isAttachmentEvent,
  materialCountFor,
  projectMeetingWorkspace,
} from '../../src/meetingWorkspace.ts'

const chatroomMode = {
  id: 'chatroom',
  category: 'chatroom',
  roles: [{ id: 'Analyst', name: '分析師' }, { id: 'Critic', name: '批評者' }],
}

const chatroomMeeting = {
  meeting_id: 'meeting-chat',
  mode_id: 'chatroom',
  activity_status: 'idle' as const,
  participants: [
    { role_id: 'Analyst', display_name: '分析師' },
    { role_id: 'Critic', display_name: '批評者' },
  ],
  courtroom: null,
  events: [
    {
      event_id: 'attachment-1', meeting_id: 'meeting-chat', step_id: 'attachment-added',
      role: 'Human', attempt: 1, status: 'completed',
      file_id: 'attachment-abc123', filename: '照片.png', size: 2048,
      mime_type: 'image/png', extension: '.png',
      created_at: '2025-01-01T00:00:01Z',
    },
    {
      event_id: 'human-1', meeting_id: 'meeting-chat', step_id: 'human-message',
      role: 'Human', attempt: 1, status: 'completed', content: '請討論方案',
      created_at: '2025-01-01T00:00:02Z',
    },
  ],
}

test('isAttachmentEvent is true only for attachment-added step ids', () => {
  assert.equal(isAttachmentEvent({ step_id: 'attachment-added' }), true)
  assert.equal(isAttachmentEvent({ step_id: 'human-message' }), false)
  assert.equal(isAttachmentEvent({ step_id: 'chat-fanout-critic' }), false)
})

test('formatAttachmentSize renders human-readable byte sizes', () => {
  assert.equal(formatAttachmentSize(0), '0 B')
  assert.equal(formatAttachmentSize(512), '512 B')
  assert.equal(formatAttachmentSize(2048), '2.0 KB')
  assert.equal(formatAttachmentSize(3 * 1024 * 1024), '3.0 MB')
})

test('materialCountFor totals active evidence and binary attachments', () => {
  const meeting = {
    case_materials: {
      evidence: [
        { status: 'active' },
        { status: 'active' },
        { status: 'inactive' },
      ],
    },
    attachments_summary: { count: 2 },
  }
  assert.equal(materialCountFor(meeting), 4)
})

test('materialCountFor is zero when a meeting has neither kind', () => {
  assert.equal(materialCountFor({}), 0)
  assert.equal(materialCountFor({ case_materials: null, attachments_summary: null }), 0)
})

test('materialCountFor falls back to legacy case_files length', () => {
  const meeting = { case_files: [{ id: 'a' }, { id: 'b' }] }
  assert.equal(materialCountFor(meeting), 2)
})

test('attachment event projects as a Human chat message with no text', () => {
  const workspace = projectMeetingWorkspace({
    meeting: chatroomMeeting,
    mode: chatroomMode,
  })
  assert.equal(workspace.family, 'conversation')
  if (workspace.family !== 'conversation') return
  const attachmentMessage = workspace.messages.find((message) => message.id === 'attachment-1')
  assert.ok(attachmentMessage)
  assert.equal(attachmentMessage.kind, 'human')
  assert.equal(attachmentMessage.roleId, 'Human')
  assert.equal(attachmentMessage.content, '')
  assert.equal(isAttachmentEvent(attachmentMessage.event), true)
  assert.equal(attachmentMessage.event.file_id, 'attachment-abc123')
  assert.equal(attachmentMessage.event.filename, '照片.png')
  assert.equal(attachmentMessage.event.mime_type, 'image/png')
  assert.equal(attachmentMessage.event.size, 2048)
})
