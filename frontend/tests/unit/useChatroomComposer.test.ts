import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildCanonicalChatroomPayload,
  parseAndSendChatMessage,
} from '../../src/composables/useChatroomComposer.ts'

function boundary(calls: Array<{ fn: string; args: unknown[] }>) {
  return {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'legacy' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'structured' } },
  }
}

test('plain Host sends the exact structured payload', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const result = await parseAndSendChatMessage({
    content: '請整理目前討論', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: [], boundary: boundary(calls),
  })

  assert.equal(result.ok, true)
  assert.deepEqual(calls[0].args, ['meeting-1', '請整理目前討論', [], [], [], undefined])
})

test('rebase recalculates display-name chip spans after leading whitespace and edits', () => {
  const payload = buildCanonicalChatroomPayload({
    content: '  新增文字 @顧問 請回答',
    mentionTokens: [{ token_id: 'm-1', role_id: 'Advisor', display_text: '@顧問', start: 0, end: 3 }],
  })

  assert.deepEqual(payload, {
    content: '  新增文字 @顧問 請回答',
    mentions: [{ token_id: 'm-1', role_id: 'Advisor', display_text: '@顧問', start: 7, end: 10 }],
    sourceTokens: [],
    sourceRefs: [],
  })
})

test('rebase uses code-point offsets for CJK and NFC combining content', () => {
  const payload = buildCanonicalChatroomPayload({
    content: '前言 @顧問 e\u0301',
    mentionTokens: [{ token_id: 'm-1', role_id: 'Advisor', display_text: '@顧問', start: 0, end: 3 }],
  })

  assert.equal('error' in payload, false)
  if (!('error' in payload)) {
    assert.equal(payload.content, '前言 @顧問 é')
    assert.deepEqual(payload.mentions[0], {
      token_id: 'm-1', role_id: 'Advisor', display_text: '@顧問', start: 3, end: 6,
    })
  }
})

test('duplicate real chips map in occurrence order and source refs dedupe in first order', () => {
  const payload = buildCanonicalChatroomPayload({
    content: '@顧問 再問 @顧問 #需求 #需求',
    mentionTokens: [
      { token_id: 'm-1', role_id: 'Advisor', display_text: '@顧問', start: 0, end: 3 },
      { token_id: 'm-2', role_id: 'Advisor', display_text: '@顧問', start: 0, end: 3 },
    ],
    sourceTokens: [
      { token_id: 's-1', source_ref: 'attachment:a', display_text: '#需求', start: 0, end: 3 },
      { token_id: 's-2', source_ref: 'attachment:a', display_text: '#需求', start: 0, end: 3 },
    ],
  })

  assert.equal('error' in payload, false)
  if (!('error' in payload)) {
    assert.deepEqual(payload.mentions.map((token) => [token.start, token.end]), [[0, 3], [7, 10]])
    assert.deepEqual(payload.sourceTokens.map((token) => [token.start, token.end]), [[11, 14], [15, 18]])
    assert.deepEqual(payload.sourceRefs, ['attachment:a'])
  }
})

test('same-label hand-typed beside one chip is ambiguous and never calls API', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const result = await parseAndSendChatMessage({
    content: '@顧問 再問 @顧問', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: [{ token_id: 'm-1', role_id: 'Advisor', display_text: '@顧問', start: 0, end: 3 }],
    boundary: boundary(calls),
  })

  assert.equal(result.ok, false)
  assert.match(result.error ?? '', /occurrence mismatch/)
  assert.deepEqual(calls, [])
})

test('# chip and hashtag use the same exact-occurrence safety rule', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const result = await parseAndSendChatMessage({
    content: '#需求 #需求標籤', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: [],
    sourceTokens: [{ token_id: 's-1', source_ref: 'attachment:a', display_text: '#需求', start: 0, end: 3 }],
    boundary: boundary(calls),
  })

  assert.equal(result.ok, false)
  assert.deepEqual(calls, [])
})

test('uncovered raw roles remain backend validation while plain email is sent as Host payload', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const rawRole = await parseAndSendChatMessage({
    content: '@Adviser 請回答', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: [], boundary: boundary(calls),
  })
  assert.equal(rawRole.ok, true)
  assert.equal(calls.length, 1)

  const email = await parseAndSendChatMessage({
    content: 'Email a@advisor.example', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: [], boundary: boundary(calls),
  })
  assert.equal(email.ok, true)
  assert.deepEqual(calls[1].args.slice(1, 5), ['Email a@advisor.example', [], [], []])
})

test('display-name chip and @all serialize structured role tokens', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const mentions = [
    { token_id: 'all-1', role_id: 'all', display_text: '@全部角色', start: 0, end: 5 },
    { token_id: 'advisor-1', role_id: 'Advisor', display_text: '@顧問', start: 0, end: 3 },
  ]
  const result = await parseAndSendChatMessage({
    content: '@全部角色 @顧問 請回答', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: mentions, boundary: boundary(calls),
  })

  assert.equal(result.ok, true)
  assert.equal(calls[0].fn, 'sendChatMention')
  assert.deepEqual(calls[0].args[2], [
    { ...mentions[0], start: 0, end: 5 },
    { ...mentions[1], start: 6, end: 9 },
  ])
})

test('blank content and send failures do not invoke legacy /messages boundary', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const blank = await parseAndSendChatMessage({
    content: '  ', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: [], boundary: boundary(calls),
  })
  assert.equal(blank.ok, false)
  assert.deepEqual(calls, [])
})
