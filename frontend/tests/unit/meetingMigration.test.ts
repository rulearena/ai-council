import assert from 'node:assert/strict'
import test from 'node:test'

import { nextMeetingMigrationDraft } from '../../src/meetingMigration.ts'

test('same-meeting object replacements preserve an unsaved migration draft', () => {
  const draft = { title: '舊土地案', goal: '尚未保存的使用者目標' }

  const next = nextMeetingMigrationDraft(
    draft,
    { meetingId: 'meeting-a', requiresGoal: true },
    { meetingId: 'meeting-a', requiresGoal: true, title: '伺服器舊標題', goal: null },
  )

  assert.deepEqual(next, draft)
})

test('meeting switches initialize the draft and successful migration clears it', () => {
  const switched = nextMeetingMigrationDraft(
    { title: 'A', goal: 'A draft' },
    { meetingId: 'meeting-a', requiresGoal: true },
    { meetingId: 'meeting-b', requiresGoal: true, title: 'B title', goal: null },
  )
  assert.deepEqual(switched, { title: 'B title', goal: '' })

  const migrated = nextMeetingMigrationDraft(
    { title: 'B title', goal: 'B goal' },
    { meetingId: 'meeting-b', requiresGoal: true },
    { meetingId: 'meeting-b', requiresGoal: false, title: 'B title', goal: 'B goal' },
  )
  assert.deepEqual(migrated, { title: '', goal: '' })
})
