import assert from 'node:assert/strict'
import test from 'node:test'
import type { ChatroomSource } from '../../src/api.ts'
import {
  detectSourceTrigger,
  filterSourceOptions,
  insertSourceToken,
  orderedUniqueSourceRefs,
  sourceOptionMetadata,
} from '../../src/chatroomSources.ts'

const source = (overrides: Partial<ChatroomSource> = {}): ChatroomSource => ({
  source_ref: 'attachment:file-1', label: '待辦總覽.md', kind: 'attachment', active: true,
  readable: true, reader_ref: 'attachment:file-1', available_segment_refs: ['full'], size: 42,
  created_at: '2026-08-10T00:00:00Z', presentation_discriminator: '1', ...overrides,
})

test('source trigger supports astral prefixes and filters only readable active options', () => {
  assert.deepEqual(detectSourceTrigger('😀 #待', 5), { triggered: true, filterText: '待', start: 3 })
  assert.deepEqual(filterSourceOptions([
    source(),
    source({ source_ref: 'attachment:pdf', label: 'scan.pdf', readable: false }),
    source({ source_ref: 'evidence:old', active: false }),
  ], '待'), [source()])
})

test('source insertion replaces only the trigger and preserves mid-text suffix with code-point spans', () => {
  const result = insertSourceToken('😀 #待 後文', 5, source(), 's-1')
  assert.equal(result.content, '😀 #待辦總覽.md 後文')
  assert.deepEqual(result.token, {
    token_id: 's-1', source_ref: 'attachment:file-1', display_text: '#待辦總覽.md', start: 2, end: 10,
  })
})

test('source option metadata disambiguates same-label sources without exposing stable refs', () => {
  const metadata = sourceOptionMetadata(source({ kind: 'evidence', source_ref: 'evidence:2' }))
  assert.match(metadata, /證據/)
  assert.match(metadata, /42 bytes/)
  assert.doesNotMatch(metadata, /evidence:2/)
})

test('source option metadata includes a stable same-label discriminator', () => {
  assert.match(sourceOptionMetadata(source({ presentation_discriminator: '2' })), /#2/)
})

test('ordered source refs deduplicate repeated selections without changing first order', () => {
  assert.deepEqual(orderedUniqueSourceRefs([
    { token_id: '1', source_ref: 'attachment:a', display_text: '#A', start: 0, end: 2 },
    { token_id: '2', source_ref: 'attachment:b', display_text: '#B', start: 3, end: 5 },
    { token_id: '3', source_ref: 'attachment:a', display_text: '#A', start: 6, end: 8 },
  ]), ['attachment:a', 'attachment:b'])
})
