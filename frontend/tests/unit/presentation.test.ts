import assert from 'node:assert/strict'
import test from 'node:test'

import {
  decisionDisplayLabel,
  interactionDisplayLabel,
  roleDisplayName,
  stepDisplayLabel,
} from '../../src/presentation.ts'

const courtroom = {
  id: 'courtroom',
  roles: [
    { id: 'Prosecutor', name: '檢察官' },
    { id: 'Defense', name: '辯護律師' },
    { id: 'Judge', name: '法官' },
  ],
  steps: [
    { role: 'Prosecutor', label: '檢察官指控', template: 'courtroom_charge' },
    { role: 'Defense', label: '辯護律師答辯', template: 'courtroom_defense' },
    { role: 'Judge', label: '法官判決', template: 'courtroom_verdict' },
  ],
}

test('courtroom roles and relay step ids use catalog presentation labels', () => {
  const participants = [
    { role_id: 'Defense', display_name: '辯護律師' },
    { role_id: 'Judge', display_name: '' },
  ]

  assert.equal(roleDisplayName(courtroom, participants, 'Defense'), '辯護律師')
  assert.equal(roleDisplayName(courtroom, participants, 'Judge'), '法官')
  assert.equal(
    stepDisplayLabel(courtroom, participants, {
      role: 'Defense',
      step_id: 'round-2-courtroom-defense',
      base_step_id: 'courtroom-defense',
    }),
    '辯護律師答辯',
  )
})

test('directed and sequence events describe the user interaction instead of raw step ids', () => {
  const participants = [{ role_id: 'Defense', display_name: '辯護律師' }]

  assert.equal(
    interactionDisplayLabel(courtroom, participants, {
      role: 'Human',
      step_id: 'human-directed-message',
      interaction_type: 'directed-role-instruction',
      target_role_id: 'Defense',
    }),
    '主席追問辯護律師',
  )
  assert.equal(
    interactionDisplayLabel(courtroom, participants, {
      role: 'Defense',
      step_id: 'directed-1-defense-response',
      interaction_type: 'directed-role-response',
    }),
    '辯護律師回應主席追問',
  )
  assert.equal(
    interactionDisplayLabel(courtroom, participants, {
      role: 'Defense',
      step_id: 'sequence-2-1-defense-response',
      interaction_type: 'role-sequence-response',
    }),
    '辯護律師依序回應',
  )
})

test('parallel participant display name wins over the catalog prototype and raw role id', () => {
  const brainstorm = {
    id: 'brainstorm',
    roles: [{ id: 'Moderator', name: '主持人' }],
    fanout: { role: 'Member', label: '委員發想' },
    synthesis: { role: 'Moderator', label: '主持人彙整' },
  }
  const participants = [{ role_id: 'Member-1', display_name: '資安顧問' }]

  assert.equal(roleDisplayName(brainstorm, participants, 'Member-1'), '資安顧問')
  assert.equal(
    roleDisplayName(brainstorm, [{ id: 'Member-2', name: '委員 2' }], 'Member-2'),
    '委員 2',
  )
  assert.equal(
    stepDisplayLabel(brainstorm, participants, {
      role: 'Member-1',
      step_id: 'fanout-1-member-1',
      base_step_id: 'member-1',
    }),
    '資安顧問發想',
  )
})

test('structured verdict decisions are localized without changing unknown enum values', () => {
  assert.equal(decisionDisplayLabel('approve'), '核准')
  assert.equal(decisionDisplayLabel('approve-with-conditions'), '有條件核准')
  assert.equal(decisionDisplayLabel('reject'), '否決')
  assert.equal(decisionDisplayLabel('insufficient-evidence'), '證據不足')
  assert.equal(decisionDisplayLabel('future-value'), 'future-value')
})

test('meeting lifecycle events have user-facing system and action labels', () => {
  assert.equal(roleDisplayName(courtroom, [], 'System'), '系統')
  assert.equal(
    stepDisplayLabel(courtroom, [], {
      role: 'System',
      step_id: 'meeting',
      status: 'closed',
    }),
    '會議結案',
  )
})
