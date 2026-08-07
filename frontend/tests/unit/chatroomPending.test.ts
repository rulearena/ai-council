import assert from 'node:assert/strict'
import test from 'node:test'

import {
  chatroomQueuedRoleIds,
  reconcileChatroomAcceptedTargets,
} from '../../src/chatroomPending.ts'
import { runWithPendingRoles } from '../../src/chairmanActions.ts'

const mention = (role_id: string) => ({
  token_id: `m-${role_id}`, role_id, display_text: `@${role_id}`, start: 0, end: role_id.length + 1,
})

test('public store seam queues Host for ordinary text and projects Host in @all', () => {
  assert.deepEqual(chatroomQueuedRoleIds([], ['Advisor', 'Critic']), ['host'])
  assert.deepEqual(chatroomQueuedRoleIds([mention('all')], ['Advisor', 'Critic']), ['host', 'Advisor', 'Critic'])
  assert.deepEqual(chatroomQueuedRoleIds([mention('host'), mention('Advisor')], ['host', 'Advisor']), ['host', 'Advisor'])
})

test('successful ordinary chat keeps Host thinking until its completion event settles it', async () => {
  const pending: string[] = []
  const succeeded = await runWithPendingRoles(
    pending,
    chatroomQueuedRoleIds([], ['Advisor', 'Critic']),
    async () => true,
  )

  assert.equal(succeeded, true)
  assert.deepEqual(pending, ['host'])
  pending.splice(pending.indexOf('host'), 1)
  assert.deepEqual(pending, [])
})

test('validation rejection rolls Host pending state back without leaving a bubble', async () => {
  const pending = ['Advisor']
  const succeeded = await runWithPendingRoles(
    pending,
    chatroomQueuedRoleIds([], ['Advisor', 'Critic']),
    async () => false,
  )

  assert.equal(succeeded, false)
  assert.deepEqual(pending, ['Advisor'])
})

test('accepted subset routing reconciles an optimistic full roster to server targets', () => {
  assert.deepEqual(
    reconcileChatroomAcceptedTargets(
      ['host', 'Advisor', 'Critic', 'Strategist', 'Analyst'],
      ['host', 'Advisor', 'Critic', 'Strategist', 'Analyst'],
      ['host', 'Advisor', 'Critic'],
    ),
    ['host', 'Advisor', 'Critic'],
  )
})
