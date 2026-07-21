import assert from 'node:assert/strict'
import test from 'node:test'

import {
  detectMentionTrigger,
  filterMentionOptions,
  selectMentionOption,
  resolveMentionInsertion,
  buildMentionMenuItems,
  shouldShowMentionAutocomplete,
  type MentionOption,
} from '../../src/composables/useMentionAutocomplete.ts'

const filterMentionMenuItems = buildMentionMenuItems

const participants: MentionOption[] = [
  { role_id: 'Blue', display_name: '藍軍', name: 'Blue Team' },
  { role_id: 'Red', display_name: '紅軍', name: 'Red Team' },
  { role_id: 'Prosecutor', display_name: '檢察官', name: null },
]

test('test_trigger_on_at — typing @ at start or after whitespace activates the menu', () => {
  assert.deepEqual(detectMentionTrigger(''), { triggered: false })
  assert.deepEqual(detectMentionTrigger('hello'), { triggered: false })
  assert.deepEqual(detectMentionTrigger('@'), { triggered: true, filterText: '' })
  assert.deepEqual(detectMentionTrigger('@B'), { triggered: true, filterText: 'B' })
  assert.deepEqual(detectMentionTrigger('hello @'), { triggered: true, filterText: '' })
  assert.deepEqual(detectMentionTrigger('hello @R'), { triggered: true, filterText: 'R' })
  assert.deepEqual(detectMentionTrigger('hello @R test'), { triggered: false })
  assert.deepEqual(detectMentionTrigger('contact@'), { triggered: false })
  assert.deepEqual(detectMentionTrigger('a@b'), { triggered: false })
})

test('test_filters_participants — typing @B filters to roles matching B (plus @all always present)', () => {
  const filtered = filterMentionOptions(participants, 'B')
  const roleMatches = filtered.filter((o) => o.role_id !== 'all')
  assert.equal(roleMatches.length, 1)
  assert.equal(roleMatches[0].role_id, 'Blue')
  assert.ok(filtered.some((o) => o.role_id === 'all'), '@all always present')
})

test('test_filters_participants — empty filter returns all participants plus @all', () => {
  const filtered = filterMentionOptions(participants, '')
  assert.equal(filtered.length, 4)
  assert.equal(filtered[0].role_id, 'all')
  assert.equal(filtered[0].display_name, '全體成員')
})

test('test_select_inserts_role_id — selecting Blue inserts @Blue  into text', () => {
  const input = '@Bl'
  const triggerInfo = detectMentionTrigger(input)
  assert.equal(triggerInfo.triggered, true)

  const filtered = filterMentionOptions(participants, triggerInfo.filterText)
  const blueOption = filtered.find((o) => o.role_id === 'Blue')!
  assert.ok(blueOption)

  const result = selectMentionOption(input, blueOption)
  assert.equal(result.text, '@Blue ')
  assert.equal(result.selectionStart, result.text.length)
})

test('test_all_option_present — @all option always in menu', () => {
  const all = filterMentionOptions(participants, '')
  assert.ok(all.some((o) => o.role_id === 'all'), 'all option should always be present')
  assert.equal(all[0].role_id, 'all')

  const filteredForAll = filterMentionOptions(participants, 'all')
  assert.ok(filteredForAll.some((o) => o.role_id === 'all'))

  const filteredForNonMatch = filterMentionOptions(participants, 'xyz')
  assert.ok(filteredForNonMatch.some((o) => o.role_id === 'all'), '@all should always be present even with unrelated filter')
})

test('test_escape_dismisses — Escape closes menu without insertion', () => {
  const state = { open: true, filterText: 'B', activeIndex: 0 }
  const result = resolveMentionInsertion(state, 'escape')
  assert.equal(result.action, 'dismiss')
  assert.equal(result.text, undefined)
  assert.equal(result.open, false)
})

test('test_escape_dismisses — Enter on active item selects and returns replacement', () => {
  const allItems = filterMentionMenuItems(participants, 'R')
  const redIndex = allItems.findIndex((o) => o.role_id === 'Red')
  const state = { open: true, filterText: 'R', activeIndex: redIndex }
  const result = resolveMentionInsertion(state, 'enter', allItems)
  assert.equal(result.action, 'select')
  assert.equal(result.selectedOption?.role_id, 'Red')
})

test('test_escape_dismisses — ArrowDown increments active index', () => {
  const allItems = filterMentionMenuItems(participants, '')
  const state = { open: true, filterText: '', activeIndex: 0 }
  const result = resolveMentionInsertion(state, 'arrow-down', allItems)
  assert.equal(result.newActiveIndex, 1)
})

test('test_escape_dismisses — ArrowDown wraps at end', () => {
  const allItems = filterMentionMenuItems(participants, '')
  const state = { open: true, filterText: '', activeIndex: allItems.length - 1 }
  const result = resolveMentionInsertion(state, 'arrow-down', allItems)
  assert.equal(result.newActiveIndex, 0)
})

test('test_escape_dismisses — ArrowUp wraps at start', () => {
  const allItems = filterMentionMenuItems(participants, '')
  const state = { open: true, filterText: '', activeIndex: 0 }
  const result = resolveMentionInsertion(state, 'arrow-up', allItems)
  assert.equal(result.newActiveIndex, allItems.length - 1)
})

test('test_no_autocomplete_non_chatroom — shouldShowMentionAutocomplete returns false for non-chatroom', () => {
  assert.equal(shouldShowMentionAutocomplete('red-blue'), false)
  assert.equal(shouldShowMentionAutocomplete('courtroom'), false)
  assert.equal(shouldShowMentionAutocomplete('brainstorm'), false)
  assert.equal(shouldShowMentionAutocomplete('chatroom'), true)
})

test('test_insert_text_replaces_trigger_portion — typing @Bl and selecting Blue replaces @Bl with @Blue ', () => {
  const result = selectMentionOption('say @Bl', participants.find((p) => p.role_id === 'Blue')!)
  assert.equal(result.text, 'say @Blue ')
})

test('test_insert_text_at_start — selecting from @ produces @Blue ', () => {
  const result = selectMentionOption('@', participants.find((p) => p.role_id === 'Blue')!)
  assert.equal(result.text, '@Blue ')
  assert.equal(result.selectionStart, result.text.length)
})

test('buildMentionMenuItems — combines participants with @all and applies filter', () => {
  const items = buildMentionMenuItems(participants, 'R')
  assert.ok(items.some((i) => i.role_id === 'Red'))
  assert.ok(!items.some((i) => i.role_id === 'Blue'))
  assert.ok(items.some((i) => i.role_id === 'all'), '@all always present')
})

test('buildMentionMenuItems — @all is case-insensitive matching', () => {
  const items = buildMentionMenuItems(participants, 'All')
  assert.ok(items.some((i) => i.role_id === 'all'))
})

test('filterMentionOptions — case-insensitive filtering', () => {
  const filtered = filterMentionOptions(participants, 'blue')
  const roleMatches = filtered.filter((o) => o.role_id !== 'all')
  assert.equal(roleMatches.length, 1)
  assert.equal(roleMatches[0].role_id, 'Blue')
})
