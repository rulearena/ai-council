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
