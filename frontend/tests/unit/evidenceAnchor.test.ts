import assert from 'node:assert/strict'
import test from 'node:test'

import { draftEvidenceAnchor } from '../../src/meetingWorkspace.ts'

test('draftEvidenceAnchor uses 證物 for courtroom', () => {
  assert.equal(draftEvidenceAnchor(1, 'courtroom'), '[證物一]')
  assert.equal(draftEvidenceAnchor(2, 'courtroom'), '[證物二]')
})

test('draftEvidenceAnchor uses 附件 for chatroom', () => {
  assert.equal(draftEvidenceAnchor(1, 'chatroom'), '[附件一]')
  assert.equal(draftEvidenceAnchor(2, 'chatroom'), '[附件二]')
})

test('draftEvidenceAnchor uses 附件 for other non-courtroom modes', () => {
  assert.equal(draftEvidenceAnchor(1, 'red-blue'), '[附件一]')
  assert.equal(draftEvidenceAnchor(1, 'relay'), '[附件一]')
  assert.equal(draftEvidenceAnchor(1, 'parallel'), '[附件一]')
})

test('draftEvidenceAnchor renders Chinese numerals up to 萬', () => {
  assert.equal(draftEvidenceAnchor(10, 'chatroom'), '[附件十]')
  assert.equal(draftEvidenceAnchor(101, 'chatroom'), '[附件一百零一]')
  assert.equal(draftEvidenceAnchor(10003, 'chatroom'), '[附件一萬零三]')
})
