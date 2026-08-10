import test from 'node:test'
import assert from 'node:assert/strict'
import { resolveChatroomCitation } from '../../src/chatroomCitations.ts'
import type { ChatroomSource } from '../../src/api.ts'

const source = (overrides: Partial<ChatroomSource> = {}): ChatroomSource => ({
  source_ref: 'attachment:file-1', label: '待辦總覽.md', kind: 'attachment', active: true,
  readable: true, reader_ref: 'attachment:file-1', available_segment_refs: ['full'], ...overrides,
})

test('citation opens the exact current reader target when still readable', () => {
  assert.deepEqual(resolveChatroomCitation({
    source_ref: 'attachment:file-1', label: '待辦總覽.md', segment_refs: ['full'],
  }, [source()]), { label: '待辦總覽.md', reader_ref: 'attachment:file-1', available: true })
})

test('historical citation stays unavailable when the source is deleted or inactive', () => {
  const citation = { source_ref: 'evidence:e-1', label: '決議', segment_refs: ['paragraph:0001'] }
  assert.equal(resolveChatroomCitation(citation, []).available, false)
  assert.equal(resolveChatroomCitation(citation, [source({
    source_ref: 'evidence:e-1', reader_ref: 'evidence:e-1', active: false,
  })]).available, false)
})

test('citation resolution exposes the authoritative reader target, not a presentation row', () => {
  const state = resolveChatroomCitation(
    { source_ref: 'evidence:e-9', label: '同名資料', segment_refs: ['full'] },
    [source({ source_ref: 'evidence:e-9', reader_ref: 'evidence:e-9', label: '同名資料' })],
  )
  assert.equal(state.reader_ref, 'evidence:e-9')
  assert.equal(state.available, true)
})
