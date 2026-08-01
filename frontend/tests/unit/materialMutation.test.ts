import assert from 'node:assert/strict'
import test from 'node:test'

import {
  hasAiOutput,
  materialImpactConfirmMessage,
} from '../../src/meetingWorkspace.ts'

test('hasAiOutput is true when a completed non-Human/System event exists', () => {
  assert.equal(hasAiOutput([{ role: 'Analyst', status: 'completed' }]), true)
})

test('hasAiOutput is false when only Human/System events exist', () => {
  assert.equal(hasAiOutput([
    { role: 'Human', status: 'completed' },
    { role: 'System', status: 'completed' },
  ]), false)
})

test('hasAiOutput is false when an AI event has not completed', () => {
  assert.equal(hasAiOutput([{ role: 'Analyst', status: 'failed' }]), false)
  assert.equal(hasAiOutput([{ role: 'Analyst', status: 'running' }]), false)
})

test('hasAiOutput is false for empty or undefined events', () => {
  assert.equal(hasAiOutput([]), false)
  assert.equal(hasAiOutput(undefined), false)
})

test('hasAiOutput ignores incomplete AI events but sees a completed one', () => {
  assert.equal(hasAiOutput([
    { role: 'Analyst', status: 'failed' },
    { role: 'Human', status: 'completed' },
    { role: 'Critic', status: 'completed' },
  ]), true)
})

test('materialImpactConfirmMessage differs between courtroom and other modes', () => {
  const courtroom = materialImpactConfirmMessage('courtroom')
  const chatroom = materialImpactConfirmMessage('chatroom')
  assert.notEqual(courtroom, chatroom)
  assert.match(courtroom, /證物/)
  assert.match(courtroom, /案卷/)
  assert.match(chatroom, /附件/)
})

test('materialImpactConfirmMessage mentions pausing and reopening in both modes', () => {
  for (const modeId of ['courtroom', 'chatroom', 'relay', 'parallel']) {
    const message = materialImpactConfirmMessage(modeId)
    assert.match(message, /暫停/)
    assert.match(message, /重開審議/)
    assert.match(message, /確定儲存/)
  }
})
