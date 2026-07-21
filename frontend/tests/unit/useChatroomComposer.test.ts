import assert from 'node:assert/strict'
import test from 'node:test'

import { parseAndSendChatMessage } from '../../src/composables/useChatroomComposer.ts'

const participants = [
  { role_id: 'Prosecutor', display_name: '檢察官' },
  { role_id: 'Defense', display_name: '辯護律師' },
  { role_id: 'Judge', display_name: '法官' },
]

test('test_send_without_mention dispatches human-message API call', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const boundary = {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'evt-1' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'evt-2' } },
  }

  const result = await parseAndSendChatMessage({
    content: 'Hello everyone',
    meetingId: 'meeting-1',
    participants,
    quotedEventId: null,
    boundary,
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].fn, 'sendChatMessage')
  assert.deepEqual(calls[0].args, ['meeting-1', 'Hello everyone', undefined])
  assert.equal(result.ok, true)
})

test('test_send_without_mention passes quotedEventId when present', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const boundary = {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'evt-1' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'evt-2' } },
  }

  const result = await parseAndSendChatMessage({
    content: 'I agree with the above',
    meetingId: 'meeting-1',
    participants,
    quotedEventId: 'evt-quote-42',
    boundary,
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].fn, 'sendChatMessage')
  assert.deepEqual(calls[0].args, ['meeting-1', 'I agree with the above', 'evt-quote-42'])
  assert.equal(result.ok, true)
})

test('test_send_with_mention dispatches /chat/mention API call with mentions array', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const boundary = {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'evt-1' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'evt-2' } },
  }

  const result = await parseAndSendChatMessage({
    content: '@Prosecutor what do you think?',
    meetingId: 'meeting-1',
    participants,
    quotedEventId: null,
    boundary,
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].fn, 'sendChatMention')
  assert.equal(calls[0].args[0], 'meeting-1')
  assert.equal(calls[0].args[1], '@Prosecutor what do you think?')
  assert.deepEqual(calls[0].args[2], ['Prosecutor'])
  assert.equal(calls[0].args[3], undefined)
  assert.equal(result.ok, true)
})

test('test_send_with_mention parses @all token', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const boundary = {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'evt-1' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'evt-2' } },
  }

  await parseAndSendChatMessage({
    content: '@all please review this',
    meetingId: 'meeting-1',
    participants,
    quotedEventId: null,
    boundary,
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].fn, 'sendChatMention')
  assert.deepEqual(calls[0].args[2], ['all'])
})

test('test_send_with_mention deduplicates repeated mentions', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const boundary = {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'evt-1' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'evt-2' } },
  }

  await parseAndSendChatMessage({
    content: '@Prosecutor and @Prosecutor again',
    meetingId: 'meeting-1',
    participants,
    quotedEventId: null,
    boundary,
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].fn, 'sendChatMention')
  assert.deepEqual(calls[0].args[2], ['Prosecutor'])
})

test('test_send_with_mention ignores unknown role_id tokens', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const boundary = {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'evt-1' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'evt-2' } },
  }

  await parseAndSendChatMessage({
    content: '@UnknownRole hello',
    meetingId: 'meeting-1',
    participants,
    quotedEventId: null,
    boundary,
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].fn, 'sendChatMessage')
  assert.deepEqual(calls[0].args[2], undefined)
})

test('test_send_with_mention parses multiple different mentions', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const boundary = {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'evt-1' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'evt-2' } },
  }

  await parseAndSendChatMessage({
    content: '@Prosecutor and @Defense please respond',
    meetingId: 'meeting-1',
    participants,
    quotedEventId: null,
    boundary,
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].fn, 'sendChatMention')
  assert.deepEqual(calls[0].args[2], [
    'Prosecutor',
    'Defense',
  ])
})

test('test_send_with_quote dispatches with quoted_event_id', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const boundary = {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'evt-1' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'evt-2' } },
  }

  const result = await parseAndSendChatMessage({
    content: '@Prosecutor see above',
    meetingId: 'meeting-1',
    participants,
    quotedEventId: 'evt-quote-99',
    boundary,
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].fn, 'sendChatMention')
  assert.equal(calls[0].args[3], 'evt-quote-99')
  assert.equal(result.ok, true)
})

test('returns ok=false when content is blank', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const boundary = {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'evt-1' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'evt-2' } },
  }

  const result = await parseAndSendChatMessage({
    content: '   ',
    meetingId: 'meeting-1',
    participants,
    quotedEventId: null,
    boundary,
  })

  assert.equal(calls.length, 0)
  assert.equal(result.ok, false)
})

test('returns ok=false and error when boundary throws', async () => {
  const boundary = {
    sendChatMessage: async () => { throw new Error('network failure') },
    sendChatMention: async () => { throw new Error('network failure') },
  }

  const result = await parseAndSendChatMessage({
    content: 'Hello',
    meetingId: 'meeting-1',
    participants,
    quotedEventId: null,
    boundary,
  })

  assert.equal(result.ok, false)
  assert.equal(result.error, 'network failure')
})

test('@ token mid-word is not treated as a mention', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const boundary = {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'evt-1' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'evt-2' } },
  }

  await parseAndSendChatMessage({
    content: 'email@Prosecutor.com hello',
    meetingId: 'meeting-1',
    participants,
    quotedEventId: null,
    boundary,
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].fn, 'sendChatMessage')
  assert.deepEqual(calls[0].args[2], undefined)
})

test('mention is case-sensitive for role_id matching', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const boundary = {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'evt-1' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'evt-2' } },
  }

  await parseAndSendChatMessage({
    content: '@prosecutor hello',
    meetingId: 'meeting-1',
    participants,
    quotedEventId: null,
    boundary,
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].fn, 'sendChatMessage')
  assert.deepEqual(calls[0].args[2], undefined)
})

test('@all plus role mention produces array with @all first', async () => {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const boundary = {
    sendChatMessage: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMessage', args }); return { event_id: 'evt-1' } },
    sendChatMention: async (...args: unknown[]) => { calls.push({ fn: 'sendChatMention', args }); return { event_id: 'evt-2' } },
  }
  const participantsWithBlue = [
    ...participants,
    { role_id: 'Blue', display_name: '藍方' },
  ]

  await parseAndSendChatMessage({
    content: '@all @Blue please respond',
    meetingId: 'meeting-1',
    participants: participantsWithBlue,
    quotedEventId: null,
    boundary,
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].fn, 'sendChatMention')
  const mentions = calls[0].args[2] as string[]
  assert.ok(mentions.includes('all'), 'should include "all"')
  assert.ok(mentions.includes('Blue'), 'should include "Blue"')
  assert.equal(mentions[0], 'all', '@all should appear first')
})
