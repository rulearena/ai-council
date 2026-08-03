import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createUploadEntry,
  uploadFailed,
  uploadStarted,
  uploadStatusLabel,
  uploadSucceeded,
} from '../../src/attachmentUpload.ts'
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

test('isAttachmentEvent stays true for removed attachment events', () => {
  assert.equal(
    isAttachmentEvent({ step_id: 'attachment-added', removed: true }),
    true,
  )
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

test('materialCountFor skips removed attachment events', () => {
  const meeting = {
    case_materials: { evidence: [{ status: 'active' }] },
    events: [
      {
        step_id: 'attachment-added',
        mime_type: 'image/png',
        removed: true,
      },
      {
        step_id: 'attachment-added',
        mime_type: 'image/png',
      },
      { step_id: 'human-message' },
    ],
  }
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

const courtroomMode = {
  id: 'courtroom',
  category: 'courtroom',
  roles: [{ id: 'Judge', name: '法官' }, { id: 'Advocate', name: '辯護人' }],
}

const courtroomMeeting = {
  meeting_id: 'meeting-court',
  mode_id: 'courtroom',
  activity_status: 'idle' as const,
  participants: [
    { role_id: 'Judge', display_name: '法官' },
    { role_id: 'Advocate', display_name: '辯護人' },
  ],
  courtroom: {
    status: 'draft',
    issues: [],
    current_issue_id: null,
    final_status: 'pending',
    available_actions: [],
    case_type: null,
    requires_case_type: false,
  },
  events: [
    {
      event_id: 'attachment-court-1', meeting_id: 'meeting-court', step_id: 'attachment-added',
      role: 'Human', attempt: 1, status: 'completed',
      file_id: 'attachment-court123', filename: '證物照.png', size: 4096,
      mime_type: 'image/png', extension: '.png',
      created_at: '2025-01-01T00:00:01Z',
    },
  ],
}

test('courtroom projection keeps attachment events in the general record', () => {
  const workspace = projectMeetingWorkspace({ meeting: courtroomMeeting, mode: courtroomMode })
  assert.equal(workspace.family, 'court-hearing')
  if (workspace.family !== 'court-hearing') return
  const record = workspace.ungroupedMessages
  assert.equal(record.length, 1)
  assert.equal(isAttachmentEvent(record[0].event), true)
  assert.equal(record[0].kind, 'human')
  assert.equal(record[0].roleId, 'Human')
  assert.equal(record[0].content, '')
  assert.equal(record[0].event.file_id, 'attachment-court123')
})

test('upload state machine: uploading → done', () => {
  const entry = createUploadEntry(new File(['zip-bytes'], 'bundle.zip'))
  assert.equal(entry.status, 'uploading')
  assert.equal(entry.retryFile?.name, 'bundle.zip')
  const done = uploadSucceeded(entry)
  assert.equal(done.status, 'done')
  assert.equal(done.error, undefined)
})

test('upload state machine: uploading → error → retry → done', () => {
  const entry = createUploadEntry(new File(['zip-bytes'], 'bundle.zip'))
  const failed = uploadFailed(entry, 'per-file limit exceeded')
  assert.equal(failed.status, 'error')
  assert.equal(failed.error, 'per-file limit exceeded')
  const retried = uploadStarted(failed)
  assert.equal(retried.status, 'uploading')
  assert.equal(retried.error, undefined)
  assert.equal(retried.retryFile, entry.retryFile)
  const done = uploadSucceeded(retried)
  assert.equal(done.status, 'done')
})

test('upload status labels cover uploading/done/error', () => {
  assert.equal(uploadStatusLabel('uploading'), '上傳中…')
  assert.equal(uploadStatusLabel('done'), '已上傳')
  assert.equal(uploadStatusLabel('error'), '上傳失敗')
})
