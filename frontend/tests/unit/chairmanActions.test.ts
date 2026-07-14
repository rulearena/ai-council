import assert from 'node:assert/strict'
import test from 'node:test'

import {
  chairmanActionOptions,
  chairmanActionBlockReason,
  chairmanActionPresentation,
  executeChairmanAction,
  runWithPendingRoles,
  meetingEditPolicy,
  projectFixedRoundFailedRole,
  projectPrimaryAction,
  requestRoleSequenceWithFailureGuard,
} from '../../src/chairmanActions.ts'

const roles = [
  { role_id: 'Prosecutor', display_name: '檢察官' },
  { role_id: 'Defense', display_name: '辯護律師' },
  { role_id: 'Judge', display_name: '法官' },
]

test('chairman composer exposes note, council, and every active role from one action list', () => {
  assert.deepEqual(
    chairmanActionOptions({ modeId: 'red-blue', modeCategory: 'relay', participants: roles, courtroom: null, nextActionLabel: '開始審議：下一位是檢察官' }),
    [
      { value: 'note', label: '記錄補充（不會呼叫 AI）' },
      { value: 'all', label: '請全體回應（下一步：開始審議：下一位是檢察官）' },
      { value: 'role:Prosecutor', label: '請檢察官回答' },
      { value: 'role:Defense', label: '請辯護律師回答' },
      { value: 'role:Judge', label: '請法官回答' },
    ],
  )
})

test('courtroom AI composer actions follow the backend available actions', () => {
  assert.deepEqual(
    chairmanActionOptions({
      modeId: 'courtroom',
      modeCategory: 'relay',
      participants: roles,
      courtroom: {
        available_actions: ['start-issue', 'add-note', 'directed-response'],
        current_issue_id: null,
        issues: [{ id: 'issue-1', title: '佔有權源', status: 'pending' }],
      },
    }),
    [
      { value: 'note', label: '記錄補充（不會呼叫 AI）' },
      { value: 'all', label: '請全體回應（下一步：開始爭點「佔有權源」）' },
      { value: 'role:Prosecutor', label: '請檢察官回答' },
      { value: 'role:Defense', label: '請辯護律師回答' },
      { value: 'role:Judge', label: '請法官回答' },
    ],
  )

  assert.deepEqual(
    chairmanActionOptions({
      modeId: 'courtroom',
      modeCategory: 'relay',
      participants: roles,
      courtroom: { available_actions: ['draft-issues', 'edit-issues'], current_issue_id: null, issues: [] },
    }),
    [{ value: 'note', label: '記錄補充（不會呼叫 AI）' }],
  )
})

test('parallel composer only exposes actions supported by the backend mode capability', () => {
  assert.deepEqual(
    chairmanActionOptions({
      modeId: 'brainstorm',
      modeCategory: 'parallel',
      participants: roles,
      courtroom: null,
    }),
    [
      { value: 'note', label: '記錄補充（不會呼叫 AI）' },
      { value: 'all', label: '請全體回應' },
    ],
  )
})

test('failed relay step leaves only notes until the failed role is cleared', () => {
  const input = {
    modeId: 'red-blue',
    modeCategory: 'relay',
    participants: roles,
    courtroom: null,
  }

  assert.deepEqual(
    chairmanActionOptions({ ...input, failedRole: 'Defense' }),
    [{ value: 'note', label: '記錄補充（不會呼叫 AI）' }],
  )
  assert.equal(
    chairmanActionBlockReason('all', 'Defense', roles),
    '辯護律師的回應失敗，請先重試失敗步驟，再請 AI 回應。',
  )
  assert.equal(
    chairmanActionBlockReason('role:Prosecutor', 'Defense', roles),
    '辯護律師的回應失敗，請先重試失敗步驟，再請 AI 回應。',
  )
  assert.equal(chairmanActionBlockReason('note', 'Defense', roles), null)

  assert.equal(
    chairmanActionOptions({ ...input, failedRole: null }).some((option) => option.value === 'all'),
    true,
  )
  assert.equal(
    chairmanActionOptions({ ...input, failedRole: null }).some((option) => option.value === 'role:Defense'),
    true,
  )
})

test('fixed round failure survives later directed events and clears only after fixed retry', () => {
  const steps = [
    { role: 'Blue', label: '藍軍提案', template: 'blue_propose' },
    { role: 'Red', label: '紅軍質疑', template: 'red_critique' },
  ]
  const failedThenDirected = [
    { role: 'Blue', step_id: 'blue-propose', base_step_id: 'blue-propose', round: 1, attempt: 1, status: 'completed' },
    { role: 'Red', step_id: 'red-critique', base_step_id: 'red-critique', round: 1, attempt: 1, status: 'failed' },
    { role: 'Red', step_id: 'directed-1-red-response', base_step_id: 'red-response', round: 2, attempt: 1, status: 'completed', interaction_type: 'directed-role-response' },
    { role: 'Red', step_id: 'sequence-1-red-response', base_step_id: 'red-response', round: 3, attempt: 1, status: 'completed', interaction_type: 'role-sequence-response' },
  ]

  assert.equal(projectFixedRoundFailedRole(steps, failedThenDirected), 'Red')
  assert.equal(projectFixedRoundFailedRole(steps, [
    ...failedThenDirected,
    { role: 'Red', step_id: 'red-critique', base_step_id: 'red-critique', round: 1, attempt: 2, status: 'completed' },
  ]), null)
  assert.equal(projectFixedRoundFailedRole(steps, [
    { role: 'Red', step_id: 'directed-1-red-response', base_step_id: 'red-response', round: 1, attempt: 1, status: 'failed', interaction_type: 'directed-role-response' },
  ]), null)
})

test('each chairman action states its audience and whether it invokes AI', () => {
  assert.deepEqual(chairmanActionPresentation('note', roles), {
    placeholder: '輸入要加入會議紀錄的補充；不會呼叫 AI…',
    submitLabel: '記錄主席補充',
    successMessage: '已加入會議紀錄，未呼叫 AI。',
  })
  assert.deepEqual(chairmanActionPresentation('all', roles), {
    placeholder: '輸入要請全體回應的問題或補充…',
    submitLabel: '請全體回應',
    successMessage: '已記錄主席發言，並啟動畫面所示的下一步。',
  })
  assert.deepEqual(chairmanActionPresentation('role:Defense', roles), {
    placeholder: '輸入要請辯護律師回答的問題或指示…',
    submitLabel: '請辯護律師回答',
    successMessage: '已請辯護律師針對這項指示回答。',
  })
})

test('chairman action execution never duplicates the Human message for a targeted response', async () => {
  const calls: string[] = []
  const boundary = {
    appendNote: async () => { calls.push('note'); return true },
    requestAll: async () => { calls.push('all'); return true },
    requestRole: async (role: string) => { calls.push(`role:${role}`); return true },
  }

  await executeChairmanAction('note', '補充證據', boundary)
  assert.deepEqual(calls, ['note'])

  calls.length = 0
  await executeChairmanAction('role:Defense', '請回答', boundary)
  assert.deepEqual(calls, ['role:Defense'])

  calls.length = 0
  await executeChairmanAction('all', '請全體回應', boundary)
  assert.deepEqual(calls, ['note', 'all'])
})

test('failed chairman AI action rolls back its optimistic role queue', async () => {
  const pendingRoles = ['Existing']

  const succeeded = await runWithPendingRoles(
    pendingRoles,
    ['Prosecutor', 'Defense'],
    async () => false,
  )

  assert.equal(succeeded, false)
  assert.deepEqual(pendingRoles, ['Existing'])
})

test('accepted chairman AI action keeps its optimistic role queue', async () => {
  const pendingRoles = ['Existing']

  const succeeded = await runWithPendingRoles(
    pendingRoles,
    ['Prosecutor', 'Defense'],
    async () => true,
  )

  assert.equal(succeeded, true)
  assert.deepEqual(pendingRoles, ['Existing', 'Prosecutor', 'Defense'])
})

test('role sequence guard blocks stale direct calls and rolls back rejected requests', async () => {
  const pendingRoles = ['Existing']
  const blockedReasons: string[] = []
  let requests = 0

  const blocked = await requestRoleSequenceWithFailureGuard({
    failedRole: 'Defense',
    participants: roles,
    pendingRoles,
    queuedRoles: ['Prosecutor', 'Defense'],
    onBlocked: (reason) => blockedReasons.push(reason),
    request: async () => { requests += 1; return true },
  })

  assert.equal(blocked, false)
  assert.equal(requests, 0)
  assert.deepEqual(pendingRoles, ['Existing'])
  assert.deepEqual(blockedReasons, [
    '辯護律師的回應失敗，請先重試失敗步驟，再請 AI 回應。',
  ])

  const rejected = await requestRoleSequenceWithFailureGuard({
    failedRole: null,
    participants: roles,
    pendingRoles,
    queuedRoles: ['Prosecutor', 'Defense'],
    onBlocked: (reason) => blockedReasons.push(reason),
    request: async () => { requests += 1; return false },
  })

  assert.equal(rejected, false)
  assert.equal(requests, 1)
  assert.deepEqual(pendingRoles, ['Existing'])
})

test('primary action ignores Human notes and names the exact next relay action', () => {
  const steps = [
    { role: 'Blue', label: '藍軍提案', template: 'blue_propose' },
    { role: 'Red', label: '紅軍質疑', template: 'red_critique' },
    { role: 'Blue', label: '藍軍修正', template: 'blue_revise' },
    { role: 'Judge', label: '裁判', template: 'judge_decide' },
  ]
  const participants = [
    { role_id: 'Blue', display_name: '藍軍' },
    { role_id: 'Red', display_name: '紅軍' },
    { role_id: 'Judge', display_name: '裁判' },
  ]

  assert.equal(projectPrimaryAction({ modeId: 'red-blue', steps, participants, events: [
    { role: 'Human', step_id: 'human-message', status: 'completed' },
  ], courtroom: null }).label, '開始審議：下一位是藍軍')

  assert.equal(projectPrimaryAction({ modeId: 'red-blue', steps, participants, events: [
    { role: 'Blue', step_id: 'blue-propose', base_step_id: 'blue-propose', round: 1, status: 'completed' },
  ], courtroom: null }).label, '繼續本回合：下一位是紅軍')

  assert.equal(projectPrimaryAction({ modeId: 'red-blue', steps, participants, events: steps.map((step) => ({
    role: step.role,
    step_id: step.template.replaceAll('_', '-'),
    base_step_id: step.template.replaceAll('_', '-'),
    round: 1,
    status: 'completed',
  })), courtroom: null }).label, '開始新回合：下一位是藍軍')
})

test('courtroom primary action is derived from its projected available action', () => {
  const result = projectPrimaryAction({
    modeId: 'courtroom',
    steps: [],
    participants: roles,
    events: [],
    courtroom: {
      available_actions: ['submit-ruling', 'add-note', 'directed-response'],
      current_issue_id: 'issue-2',
      issues: [{ id: 'issue-2', title: '是否應返還土地', status: 'awaiting-ruling' }],
    },
  })
  assert.deepEqual(result, {
    kind: 'courtroom-ruling',
    issueId: 'issue-2',
    label: '送交爭點裁定：是否應返還土地（下一位是法官）',
    disabled: false,
  })
})

test('meeting edit policy locks running meetings and confirmed courtroom goals', () => {
  assert.deepEqual(meetingEditPolicy({
    modeId: 'courtroom',
    activityStatus: 'idle',
    courtroomStatus: 'confirmed',
    hasAiOutput: true,
  }), {
    canEdit: true,
    goalReadonly: true,
    confirmGoalChange: false,
  })
  assert.deepEqual(meetingEditPolicy({
    modeId: 'red-blue',
    activityStatus: 'running',
    courtroomStatus: null,
    hasAiOutput: true,
  }), {
    canEdit: false,
    goalReadonly: false,
    confirmGoalChange: true,
  })
})
