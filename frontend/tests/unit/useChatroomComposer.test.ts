import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildCanonicalChatroomPayload,
  parseAndSendChatMessage,
  rebaseTrackedChatroomTokens,
} from '../../src/composables/useChatroomComposer.ts'

function boundary(calls: Array<{ fn: string; args: unknown[] }>) {
  return {
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'structured' } },
  }
}

const advisor = (start = 0, end = 3, token_id = 'm-1') => ({
  token_id, role_id: 'Advisor', display_text: '@顧問', start, end,
})

const source = (start = 0, end = 3, token_id = 's-1') => ({
  token_id, source_ref: 'attachment:brief', display_text: '#需求', start, end,
})

test('plain Host sends the exact structured payload', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const result = await parseAndSendChatMessage({
    content: '請整理目前討論', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: [], boundary: boundary(calls),
  })

  assert.equal(result.ok, true)
  assert.deepEqual(calls[0].args, ['meeting-1', '請整理目前討論', [], [], [], undefined])
})

test('edit before/after chips rebases exact code-point spans', () => {
  const token = advisor()
  const before = '@顧問 請回答'
  const afterPrefix = '前言：' + before
  const shifted = rebaseTrackedChatroomTokens(before, afterPrefix, [token])
  assert.deepEqual(shifted, [advisor(3, 6)])

  const afterSuffix = afterPrefix + '，謝謝'
  assert.deepEqual(rebaseTrackedChatroomTokens(afterPrefix, afterSuffix, shifted), shifted)
  const payload = buildCanonicalChatroomPayload({ content: afterSuffix, mentionTokens: shifted })
  assert.equal('error' in payload, false)
  if (!('error' in payload)) assert.deepEqual(payload.mentions, shifted)
})

test('edit inside a chip invalidates it and retyping the same display text stays raw', async () => {
  const deleted = rebaseTrackedChatroomTokens('@顧問 請回答', ' 請回答', [advisor()])
  assert.deepEqual(deleted, [])
  const retyped = rebaseTrackedChatroomTokens(' 請回答', ' 請回答 @顧問', deleted)
  assert.deepEqual(retyped, [])

  const calls: Array<{ fn: string; args: unknown[] }> = []
  const result = await parseAndSendChatMessage({
    content: ' 請回答 @顧問', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: retyped, boundary: boundary(calls),
  })
  assert.equal(result.ok, true)
  assert.deepEqual(calls[0].args.slice(2, 5), [[], [], []])
})

test('source token deletion and retyping also invalidates metadata', () => {
  const deleted = rebaseTrackedChatroomTokens('#需求 內容', ' 內容', [source()])
  assert.deepEqual(deleted, [])
  const retyped = rebaseTrackedChatroomTokens(' 內容', ' 內容 #需求', deleted)
  assert.deepEqual(retyped, [])
})

test('edits within a chip fail closed for both token classes', () => {
  assert.deepEqual(rebaseTrackedChatroomTokens('@顧問', '@顧X', [advisor()]), [])
  assert.deepEqual(rebaseTrackedChatroomTokens('#需求', '#需X', [source()]), [])
})

test('duplicate real chips preserve separate IDs and rebase independently', () => {
  const tokens = [advisor(0, 3, 'm-1'), advisor(7, 10, 'm-2')]
  const rebased = rebaseTrackedChatroomTokens(
    '@顧問 再問 @顧問',
    '前言 @顧問 再問 @顧問',
    tokens,
  )
  assert.deepEqual(rebased, [advisor(3, 6, 'm-1'), advisor(10, 13, 'm-2')])
})

test('NFC combining content maps normalized spans without trimming leading whitespace', () => {
  const content = '  @顧問 e\u0301'
  const token = advisor(2, 5)
  const payload = buildCanonicalChatroomPayload({ content, mentionTokens: [token] })
  assert.equal('error' in payload, false)
  if (!('error' in payload)) {
    assert.equal(payload.content, '  @顧問 é')
    assert.deepEqual(payload.mentions, [advisor(2, 5)])
  }
})

test('source chip and uncovered hashtag remain separate classes', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const result = await parseAndSendChatMessage({
    content: '#需求 #需求標籤', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: [], sourceTokens: [source()], boundary: boundary(calls),
  })
  assert.equal(result.ok, true)
  assert.deepEqual(calls[0].args.slice(2, 5), [[], [source()], ['attachment:brief']])
})

test('same-label hand-typed role beside a surviving chip stays uncovered for backend authority', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const result = await parseAndSendChatMessage({
    content: '@顧問 再問 @顧問', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: [advisor()], boundary: boundary(calls),
  })
  assert.equal(result.ok, true)
  assert.deepEqual(calls[0].args[2], [advisor()])
})

test('display-name chip and @all serialize exact structured spans', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const mentions = [
    { token_id: 'all-1', role_id: 'all', display_text: '@全部角色', start: 0, end: 5 },
    { token_id: 'advisor-1', role_id: 'Advisor', display_text: '@顧問', start: 6, end: 9 },
  ]
  const result = await parseAndSendChatMessage({
    content: '@全部角色 @顧問 請回答', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: mentions, boundary: boundary(calls),
  })
  assert.equal(result.ok, true)
  assert.deepEqual(calls[0].args[2], mentions)
})

test('blank content never invokes API', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const result = await parseAndSendChatMessage({
    content: '  ', meetingId: 'meeting-1', quotedEventId: null,
    mentionTokens: [], boundary: boundary(calls),
  })
  assert.equal(result.ok, false)
  assert.deepEqual(calls, [])
})
