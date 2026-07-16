import assert from 'node:assert/strict'
import test from 'node:test'

import { projectOperationStatusText } from '../../src/operationStatus.ts'

const courtroom = {
  status: 'confirmed',
  available_actions: ['start-issue'],
  current_issue_id: null,
  issues: [{ id: 'issue-1', title: '責任是否成立', status: 'pending' }],
}

test('terminal courtroom lifecycle status wins over pending workflow guidance', () => {
  assert.equal(projectOperationStatusText('completed', courtroom, 'closed'), '已結案')
  assert.equal(projectOperationStatusText('completed', courtroom, 'cancelled'), '已取消')
})

test('active courtroom status uses workflow guidance except while the model is running', () => {
  assert.equal(projectOperationStatusText('idle', courtroom), '待主席開始攻防')
  assert.equal(projectOperationStatusText('completed', courtroom), '待主席開始攻防')
  assert.equal(projectOperationStatusText('running', courtroom), '執行中')
  assert.equal(projectOperationStatusText('idle', null), '尚未開始')
})
