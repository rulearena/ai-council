import assert from 'node:assert/strict'
import test from 'node:test'

import {
  courtroomFailedPhaseLabel,
  courtroomIssueStatusLabel,
  courtroomOutcomeLabel,
  nextCourtroomDraft,
} from '../../src/courtroomWorkspace.ts'

test('courtroom editor preserves unsaved work for same meeting and isolates meeting switches', () => {
  const drafts = {
    'meeting-a': { revision: 1, issues: [{ id: 'issue-1', title: '主席尚未儲存的修改' }] },
  }

  assert.deepEqual(nextCourtroomDraft(drafts, {
    meetingId: 'meeting-a',
    revision: 1,
    issues: [{ id: 'issue-1', title: '串流重新投影的舊標題' }],
  }), drafts['meeting-a'])
  assert.deepEqual(nextCourtroomDraft(drafts, {
    meetingId: 'meeting-b',
    revision: 0,
    issues: [],
  }), { revision: 0, issues: [] })
})

test('courtroom presentation uses understandable Chinese status and outcome labels', () => {
  assert.equal(courtroomIssueStatusLabel('awaiting-ruling'), '等待主席送交法官')
  assert.equal(courtroomIssueStatusLabel('failed'), '執行失敗，請重試')
  assert.equal(courtroomFailedPhaseLabel('defense'), '辯護律師答辯')
  assert.equal(courtroomOutcomeLabel('proponent-wins'), '主張方勝')
  assert.equal(courtroomOutcomeLabel('respondent-wins'), '答辯方勝')
  assert.equal(courtroomOutcomeLabel('partially-upheld'), '部分成立')
  assert.equal(courtroomOutcomeLabel('insufficient-evidence'), '證據不足／無法判定')
})
