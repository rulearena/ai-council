import assert from 'node:assert/strict'
import test from 'node:test'
import {
  canLeaveMeetingSettings,
  registerMeetingSettingsNavigationState,
} from '../../src/meetingSettingsNavigation.ts'

test.afterEach(() => registerMeetingSettingsNavigationState(null))

test('cancelled navigation retains a dirty meeting settings draft', () => {
  let discarded = false
  globalThis.window = {
    confirm: () => false,
    alert: () => undefined,
  } as unknown as Window & typeof globalThis
  registerMeetingSettingsNavigationState({ dirty: () => true, saving: () => false, discard: () => { discarded = true } })

  assert.equal(canLeaveMeetingSettings(), false)
  assert.equal(discarded, false)
})

test('confirmed navigation discards the draft before proceeding', () => {
  let discarded = false
  globalThis.window = {
    confirm: () => true,
    alert: () => undefined,
  } as unknown as Window & typeof globalThis
  registerMeetingSettingsNavigationState({ dirty: () => true, saving: () => false, discard: () => { discarded = true } })

  assert.equal(canLeaveMeetingSettings(), true)
  assert.equal(discarded, true)
})

test('saving meeting settings cannot be closed or switched', () => {
  let alerted = false
  globalThis.window = {
    confirm: () => true,
    alert: () => { alerted = true },
  } as unknown as Window & typeof globalThis
  registerMeetingSettingsNavigationState({ dirty: () => true, saving: () => true, discard: () => assert.fail('must not discard') })

  assert.equal(canLeaveMeetingSettings(), false)
  assert.equal(alerted, true)
})
