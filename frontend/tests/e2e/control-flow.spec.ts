import { expect, test, type Page } from '@playwright/test'

// The whole UI is now a stage with modals/drawers layered on top of it, so most flows
// need a small amount of "open this surface, do the thing, close it" choreography.
// These helpers keep the actual test bodies readable.

async function createMeetingViaNewCase(page: Page, topic: string) {
  await page.getByTestId('new-case-button').click()
  await page.getByLabel('會議主題').fill(topic)
  await page.getByTestId('create-meeting-button').click()
  // NewCaseModal closes itself once createNewMeeting() resolves.
  await expect(page.getByTestId('new-case-modal')).not.toBeVisible()
}

async function setModelsInSettings(
  page: Page,
  models: { blue: string; red: string; judge: string },
) {
  await page.getByTestId('settings-button').click()
  await page.getByTestId('blue-model-select').selectOption(models.blue)
  await page.getByTestId('red-model-select').selectOption(models.red)
  await page.getByTestId('judge-model-select').selectOption(models.judge)
}

async function closeSettings(page: Page) {
  await page.getByTestId('settings-close-button').click()
  await expect(page.getByTestId('settings-modal')).not.toBeVisible()
}

async function openRoleDrawer(page: Page, role: 'blue' | 'red' | 'judge' | 'chairman') {
  await page.getByTestId(`role-seat-${role}`).click()
  await expect(page.getByTestId('role-drawer')).toBeVisible()
}

async function closeRoleDrawer(page: Page) {
  await page.getByTestId('role-drawer-close-button').click()
  await expect(page.getByTestId('role-drawer')).not.toBeVisible()
}

async function openAdvancedOptions(page: Page) {
  await page.getByTestId('advanced-options-button').click()
  await expect(page.getByTestId('advanced-options-panel')).toBeVisible()
}

async function closeAdvancedOptions(page: Page) {
  await page.getByTestId('advanced-options-button').click()
  await expect(page.getByTestId('advanced-options-panel')).not.toBeVisible()
}

test('keeps the council stage centered with no horizontal scroll', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByTestId('council-stage')).toBeVisible()
  await expect(page.getByTestId('role-seat-chairman')).toBeVisible()
  await expect(page.getByTestId('role-seat-blue')).toBeVisible()
  await expect(page.getByTestId('role-seat-red')).toBeVisible()
  await expect(page.getByTestId('role-seat-judge')).toBeVisible()

  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBe(await page.evaluate(() => document.documentElement.clientWidth))
})

test('shows the meeting ID next to the topic and copies it to the clipboard', async ({
  page,
  context,
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/')

  const topic = `E2E meeting id ${Date.now()}`
  await createMeetingViaNewCase(page, topic)

  const meetingId = await page.getByTestId('meeting-id-display').innerText()
  expect(meetingId).toMatch(/^meeting-/)

  // The same ID shows up in Past Topics, confirming the top bar reflects the real record.
  await page.getByTestId('past-topics-button').click()
  await expect(
    page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-id-text'),
  ).toHaveText(meetingId)
  await page.getByTestId('meetings-close-button').click()

  const copyButton = page.getByTestId('copy-meeting-id-button')
  await expect(copyButton).toContainText('複製')
  await copyButton.click()
  await expect(copyButton).toContainText('已複製')

  const clipboardText = await page.evaluate(() => navigator.clipboard.readText())
  expect(clipboardText).toBe(meetingId)

  // Feedback reverts to the plain "複製" label ~1.5s after copying. "已複製" also
  // contains "複製" as a substring, so assert the "已" prefix is specifically gone
  // rather than just polling for "複製" (which would trivially match immediately).
  await expect(copyButton).not.toContainText('已複製')
  await expect(copyButton).toContainText('複製')

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('user can run a mock meeting and add chair feedback', async ({ page }) => {
  await page.goto('/')

  const topic = `E2E mock meeting ${Date.now()}`
  await createMeetingViaNewCase(page, topic)

  await expect(page.getByTestId('operation-status')).toContainText('狀態：idle')
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'waiting')
  await expect(page.getByTestId('role-seat-blue')).toHaveClass(/role-blue/)

  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await page.getByTestId('test-blue-model-button').click()
  await expect(page.getByTestId('model-test-status')).toContainText('Blue: available')
  await expect(page.getByTestId('model-test-status')).toContainText('測試')
  await closeSettings(page)

  await page.getByTestId('start-meeting-button').click()

  // The role queue is pushed synchronously before the network call, so the Blue seat
  // flips to "thinking" the instant the button is clicked - not racy.
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'thinking')
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'waiting')

  await expect(page.getByTestId('operation-status')).toContainText('狀態：running')
  await expect(page.getByTestId('start-meeting-button')).toContainText('執行中...')

  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')
  await expect(page.getByTestId('operation-status')).toContainText('最後步驟：judge-decide')
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-judge')).toHaveAttribute('data-status', 'completed')

  await openRoleDrawer(page, 'judge')
  await expect(page.getByTestId('role-output-panel')).toContainText('Role Outputs')
  await expect(page.getByTestId('role-output-panel')).toContainText('judge-decide')
  await expect(page.getByTestId('role-output-panel')).toContainText('Recommendation')
  const outputRoleBadge = page.getByTestId('role-output-panel').getByTestId('role-badge')
  await expect(outputRoleBadge.locator('img')).toHaveAttribute('alt', 'Judge')
  await expect(outputRoleBadge).toHaveClass(/role-judge/)
  await closeRoleDrawer(page)

  await expect(page.getByTestId('start-meeting-button')).toContainText('繼續討論')

  await page.getByTestId('chair-message-input').fill('主席補充：請先限制在一週可以完成的方案。')
  await page.getByTestId('send-chair-message-button').click()

  await expect(page.getByTestId('operation-status')).toContainText('狀態：waiting')
  await expect(page.getByTestId('chair-message-input')).toHaveValue('')

  // The speech bubble is transient (auto-hides after ~2.5s) - assert it while it's up.
  await expect(page.getByTestId('role-seat-chairman')).toContainText(
    '主席補充：請先限制在一週可以完成的方案。',
  )

  await openRoleDrawer(page, 'chairman')
  await expect(page.getByTestId('chairman-history-list')).toContainText(
    '主席補充：請先限制在一週可以完成的方案。',
  )

  page.once('dialog', async (dialog) => {
    expect(dialog.type()).toBe('prompt')
    await dialog.accept('主席修正：限制放寬到兩週。')
  })
  await page.getByTestId('edit-message-button').click()
  await expect(page.getByTestId('chairman-history-list')).toContainText('主席修正：限制放寬到兩週。')
  await expect(page.getByTestId('chairman-history-list')).toContainText('（訂正）')
  await closeRoleDrawer(page)

  await openRoleDrawer(page, 'blue')
  await page.getByTestId('request-blue-response-button').click()
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'thinking')
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')
  await expect(page.getByTestId('role-output-panel')).toContainText('directed-1-blue-response')
  await closeRoleDrawer(page)

  await openAdvancedOptions(page)
  await expect(page.getByTestId('role-sequence-controls')).toBeVisible()
  await page.getByTestId('sequence-preset-select').selectOption('red-blue-judge')
  await page.getByTestId('run-sequence-button').click()

  // Sequence roles are also pushed synchronously before the network call.
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'thinking')
  await closeAdvancedOptions(page)
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')

  await openRoleDrawer(page, 'judge')
  await expect(page.getByTestId('role-output-panel')).toContainText('sequence-1-judge-response')
  await closeRoleDrawer(page)

  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')

  await openRoleDrawer(page, 'blue')
  await expect(page.getByTestId('role-history-toggle')).toBeVisible()
  await page.getByTestId('role-history-toggle').click()
  await expect(page.getByTestId('role-history-list')).toContainText('blue-revise')
  await closeRoleDrawer(page)

  // Full audit trail lives in the records drawer.
  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('step-timeline')).toContainText('blue-propose')
  await expect(page.getByTestId('step-timeline')).toContainText('red-critique')
  await expect(page.getByTestId('step-timeline')).toContainText('judge-decide')
  await expect(page.getByTestId('step-timeline')).toContainText('directed-1-blue-response')
  await expect(page.getByTestId('step-timeline')).toContainText('sequence-1-red-response')
  await expect(page.getByTestId('step-timeline')).toContainText('round-2-blue-propose')
  await expect(page.getByTestId('step-timeline')).toContainText('round-2-judge-decide')
  await expect(
    page.getByTestId('step-timeline').locator('.role-badge', { hasText: 'Red' }).first(),
  ).toHaveClass(/role-red/)

  await page.getByTestId('records-tab-transcript').click()
  await expect(page.getByTestId('transcript-preview')).toContainText('## Blue - blue-propose')
  await expect(page.getByTestId('transcript-preview')).toContainText('## Judge - judge-decide')
  await expect(page.getByTestId('transcript-preview')).toContainText(
    '主席補充：請先限制在一週可以完成的方案。',
  )
  await expect(page.getByTestId('transcript-preview')).toContainText('主席修正：限制放寬到兩週。')
  await expect(page.getByTestId('transcript-preview')).toContainText('## Blue - round-2-blue-propose')

  // Debug tab only exists once developer mode is on (toggled earlier is not the case here,
  // so it should be absent by default).
  await expect(page.getByTestId('records-tab-debug')).toHaveCount(0)
  await page.getByTestId('records-close-button').click()

  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await page.getByTestId('dev-mode-toggle').check()
  await closeSettings(page)

  await page.getByTestId('records-button').click()

  // Selecting a timeline row feeds its raw event into the Debug tab - use that to verify
  // directed vs. sequence responses are actually typed differently, not just visually similar.
  await page.getByTestId('records-tab-timeline').click()
  await page
    .getByTestId('step-timeline')
    .locator('.timeline-main', { hasText: 'directed-1-blue-response' })
    .click()
  await page.getByTestId('records-tab-debug').click()
  await expect(page.getByTestId('debug-panel')).toContainText('"interaction_type": "directed-role-response"')
  await expect(page.getByTestId('debug-panel')).toContainText('"status": "completed"')

  await page.getByTestId('records-tab-timeline').click()
  await page
    .getByTestId('step-timeline')
    .locator('.timeline-main', { hasText: 'sequence-1-red-response' })
    .click()
  await page.getByTestId('records-tab-debug').click()
  await expect(page.getByTestId('debug-panel')).toContainText('"interaction_type": "role-sequence-response"')

  await page.getByTestId('records-close-button').click()

  await openAdvancedOptions(page)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId('close-meeting-button').click()
  await closeAdvancedOptions(page)

  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-status-filter').selectOption('all')
  await expect(page.getByTestId('meeting-list')).toContainText('closed')
  await page.getByTestId('meetings-close-button').click()

  await expect(page.getByTestId('operation-status')).toContainText('狀態：closed')
  await expect(page.getByTestId('start-meeting-button')).toBeDisabled()
  await expect(page.getByTestId('chair-message-input')).toBeDisabled()
  await expect(page.getByTestId('send-chair-message-button')).toBeDisabled()

  await openAdvancedOptions(page)
  await expect(page.getByTestId('cancel-meeting-button')).toBeDisabled()
  await expect(page.getByTestId('close-meeting-button')).toBeDisabled()
  await expect(page.getByTestId('run-sequence-button')).toBeDisabled()

  await page.getByTestId('past-topics-button').click()
  const meetingRow = page.getByTestId('meeting-list-item').filter({ hasText: topic })
  page.once('dialog', async (dialog) => {
    expect(dialog.type()).toBe('prompt')
    await dialog.accept('urgent, backend')
  })
  await meetingRow.getByTestId('edit-tags-button').click()
  await expect(meetingRow.getByTestId('meeting-tags')).toContainText('urgent')
  await expect(meetingRow.getByTestId('meeting-tags')).toContainText('backend')

  await page.getByTestId('meeting-search-input').fill('urgent')
  await expect(page.getByTestId('meeting-list')).toContainText(topic)
  await page.getByTestId('meeting-search-input').fill('')

  // Transcript content search hits the backend's ?q= full-text path, distinct from the
  // title-only meeting-search-input filter above - both need coverage.
  await page.getByTestId('transcript-search-input').fill('一週可以完成的方案')
  await page.getByTestId('transcript-search-button').click()
  await expect(page.getByTestId('transcript-search-results')).toContainText(topic)

  await expect(meetingRow.getByTestId('pin-meeting-button')).toHaveAttribute('aria-label', `釘選 ${topic}`)
  await meetingRow.getByTestId('pin-meeting-button').click()
  await expect(meetingRow.getByTestId('pin-meeting-button')).toHaveAttribute('aria-label', `取消釘選 ${topic}`)

  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('無法復原')
    await dialog.accept()
  })
  await meetingRow.getByTestId('delete-meeting-button').click()
  await expect(page.getByTestId('meeting-list')).not.toContainText(topic)
  await page.getByTestId('meetings-close-button').click()

  await expect(page.getByTestId('council-stage')).toContainText('尚未選擇會議')
})

test('shows a connection error banner when the backend is unreachable on load', async ({ page }) => {
  await page.route('**/models', (route) => route.abort('connectionrefused'))

  await page.goto('/')

  await expect(page.getByTestId('app-error')).toBeVisible()
  await expect(page.getByTestId('council-stage')).toBeVisible()
})

test('role seat shows failed state, halts the rest of the round, and recovers via retry', async ({
  page,
}) => {
  await page.goto('/')

  const topic = `E2E failing role seat ${Date.now()}`
  await createMeetingViaNewCase(page, topic)

  // mock-broken raises immediately (missing base_url/model), no network call involved.
  await setModelsInSettings(page, { blue: 'mock-broken', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  await page.getByTestId('start-meeting-button').click()

  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'failed')

  // The backend halts the fixed round after the first failure, so Red and Judge never run.
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'waiting')
  await expect(page.getByTestId('role-seat-red')).not.toContainText('等待發言')
  await expect(page.getByTestId('role-seat-judge')).toHaveAttribute('data-status', 'waiting')

  await openRoleDrawer(page, 'blue')
  await expect(page.getByTestId('role-output-panel')).toContainText('base_url')
  const retryButton = page.getByTestId('role-status-retry-button')
  await expect(retryButton).toBeVisible()

  // Fix the broken assignment before retrying, same as a real operator would.
  await closeRoleDrawer(page)
  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  await openRoleDrawer(page, 'blue')
  await page.getByTestId('role-status-retry-button').click()

  // retrySelectedStep pushes the whole remaining fixed-round tail (Blue, Red, Blue, Judge
  // for a blue-propose retry), so the seat flips to "thinking" immediately on click.
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'thinking')
  await closeRoleDrawer(page)

  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-judge')).toHaveAttribute('data-status', 'completed')

  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('step-timeline')).toContainText('judge-decide')
  await page.getByTestId('records-close-button').click()

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('continuing a fully completed round runs the sequence preset instead of a no-op start', async ({
  page,
}) => {
  await page.goto('/')

  const topic = `E2E smart continue ${Date.now()}`
  await createMeetingViaNewCase(page, topic)

  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')

  // Sending a chair message on an idle (non-running) meeting should surface the hint.
  await expect(page.getByTestId('continue-hint')).not.toBeVisible()
  await page.getByTestId('chair-message-input').fill('主席補充：請議會針對成本做更仔細的討論。')
  await page.getByTestId('send-chair-message-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：waiting')
  await expect(page.getByTestId('continue-hint')).toBeVisible()

  // The fixed round (blue-propose/red-critique/blue-revise/judge-decide) is already
  // fully completed at this point, so clicking "continue" must run the currently
  // selected sequence preset (default: Red -> Blue -> Judge) rather than calling
  // /start again, which would silently no-op (see runner.py's start()) and leave the
  // seat stuck on "thinking" forever with no event ever resolving it.
  await page.getByTestId('start-meeting-button').click()

  // The hint clears the instant a real role action is triggered, not on a timer.
  await expect(page.getByTestId('continue-hint')).not.toBeVisible()

  // Sequence roles are pushed synchronously before the network call resolves.
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'thinking')
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed', { timeout: 15000 })

  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('step-timeline')).toContainText('sequence-1-red-response')
  await expect(page.getByTestId('step-timeline')).toContainText('sequence-1-blue-response')
  await expect(page.getByTestId('step-timeline')).toContainText('sequence-1-judge-response')
  // A no-op start() would never have produced a fresh fixed-round step for round 2.
  await expect(page.getByTestId('step-timeline')).not.toContainText('round-2-blue-propose')
  await page.getByTestId('records-close-button').click()

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('scene switcher persists the selected scene across a reload', async ({ page }) => {
  await page.goto('/')

  const stageScene = page.getByTestId('council-stage').locator('.stage-scene')
  await expect(stageScene).toHaveAttribute('data-scene', 'meeting-room')

  // Cycle through all three registered scenes (scenes.ts's `scenes` array), not just
  // one, so a future scene added to the registry without wiring up its switch/persist
  // path correctly would show up here too.
  await page.getByTestId('settings-button').click()
  await page.getByTestId('scene-select').selectOption('courtroom')
  await expect(stageScene).toHaveAttribute('data-scene', 'courtroom')

  await page.getByTestId('scene-select').selectOption('default-chamber')
  await expect(stageScene).toHaveAttribute('data-scene', 'default-chamber')
  await page.getByTestId('settings-close-button').click()

  await page.reload()
  await expect(page.getByTestId('council-stage').locator('.stage-scene')).toHaveAttribute(
    'data-scene',
    'default-chamber',
  )
})

test('switching to the courtroom scene renders its own seat positions', async ({ page }) => {
  await page.goto('/')

  await page.getByTestId('settings-button').click()
  await page.getByTestId('scene-select').selectOption('courtroom')
  await page.getByTestId('settings-close-button').click()

  await expect(page.getByTestId('council-stage').locator('.stage-scene')).toHaveAttribute(
    'data-scene',
    'courtroom',
  )

  // Seat coordinates come straight from courtroomScene.seats (scenes.ts) - a distinct
  // layout from meeting-room's (Judge near the bench, Chairman at the bar) - confirming
  // CouncilStage actually re-reads the scene prop instead of caching the first one seen.
  await expect(page.getByTestId('role-seat-judge')).toHaveAttribute('style', /left:\s*50%/)
  await expect(page.getByTestId('role-seat-judge')).toHaveAttribute('style', /top:\s*44%/)
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('style', /left:\s*21\.6%/)
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('style', /left:\s*78\.4%/)
  await expect(page.getByTestId('role-seat-chairman')).toHaveAttribute('style', /top:\s*80%/)

  // All four seats still render and stay visible/clickable - the scene swap doesn't
  // break CouncilStage's core rendering for a non-4:3, non-meeting-room scene.
  await expect(page.getByTestId('role-seat-chairman')).toBeVisible()
  await expect(page.getByTestId('role-seat-blue')).toBeVisible()
  await expect(page.getByTestId('role-seat-red')).toBeVisible()
  await expect(page.getByTestId('role-seat-judge')).toBeVisible()
})

test('falls back to the default scene when localStorage holds an unknown scene id', async ({
  page,
}) => {
  // Simulates a scene that was later removed from the registry - the stored id is stale,
  // but the stage must still render something instead of going blank.
  await page.addInitScript(() => {
    window.localStorage.setItem('ai-council-scene', 'a-scene-that-no-longer-exists')
  })
  await page.goto('/')

  await expect(page.getByTestId('council-stage')).toBeVisible()
  await expect(page.getByTestId('council-stage').locator('.stage-scene')).toHaveAttribute(
    'data-scene',
    'meeting-room',
  )

  // The stored preference itself is sanitized on load too - not just the stage's fallback
  // computed - so the settings picker shows "議事廳" selected, not a blank <select> with
  // no option matching the stale stored id.
  await page.getByTestId('settings-button').click()
  await expect(page.getByTestId('scene-select')).toHaveValue('meeting-room')
})

test('the explicit "開始新回合" button always starts a fresh fixed round', async ({ page }) => {
  await page.goto('/')

  const topic = `E2E explicit new round ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')

  await openAdvancedOptions(page)
  await expect(page.getByTestId('new-round-panel')).toContainText(
    'Blue 提案 → Red 質詢 → Blue 修訂 → Judge 裁決',
  )
  await page.getByTestId('start-new-round-button').click()

  // startSelectedMeeting pushes the fixed-round queue synchronously before the network
  // call, same as the main CTA - Blue flips to "thinking" immediately.
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'thinking')
  await closeAdvancedOptions(page)

  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed', {
    timeout: 15000,
  })

  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('step-timeline')).toContainText('round-2-blue-propose')
  await expect(page.getByTestId('step-timeline')).toContainText('round-2-judge-decide')
  await page.getByTestId('records-close-button').click()

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('shows a failed-step hint and disables round-level actions until the step is retried', async ({
  page,
}) => {
  await page.goto('/')

  const topic = `E2E failed step hint ${Date.now()}`
  await createMeetingViaNewCase(page, topic)

  // mock-broken raises immediately (missing base_url/model), no network call involved.
  await setModelsInSettings(page, { blue: 'mock-broken', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'failed')

  await expect(page.getByTestId('failed-step-hint')).toBeVisible()
  await expect(page.getByTestId('failed-step-hint')).toContainText(
    'Blue 的回應失敗了，點擊席位可重試',
  )

  // Confirmed against the real backend: calling /start (or /sequences) again once a step
  // has failed is a silent no-op - 200 response, zero new events, activity_status stuck
  // on "failed" forever. Both round-level actions must stay disabled until the step is
  // retried, rather than let the user hit that trap.
  await expect(page.getByTestId('start-meeting-button')).toBeDisabled()
  await expect(page.getByTestId('start-meeting-button')).toHaveAttribute(
    'title',
    'Blue 的回應失敗了，請點擊席位重試該步驟',
  )

  await openAdvancedOptions(page)
  await expect(page.getByTestId('start-new-round-button')).toBeDisabled()
  await closeAdvancedOptions(page)

  // Fix the broken assignment before retrying, same as a real operator would.
  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  await openRoleDrawer(page, 'blue')
  await page.getByTestId('role-status-retry-button').click()

  // The hint clears the instant the failed role re-enters the pending queue, not on a
  // timer - it's derived from the same seat status the seat itself reads.
  await expect(page.getByTestId('failed-step-hint')).not.toBeVisible()
  await closeRoleDrawer(page)

  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')
  await expect(page.getByTestId('start-meeting-button')).toBeEnabled()

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('keeps the advanced options panel within a 375px viewport without horizontal overflow', async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/')

  const topic = `E2E narrow viewport ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  await openAdvancedOptions(page)
  await expect(page.getByTestId('new-round-panel')).toBeVisible()

  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBe(await page.evaluate(() => document.documentElement.clientWidth))

  // document.scrollWidth only grows from overflow past the *right* edge - an absolutely
  // positioned popover bleeding off the *left* edge (as this one did before the
  // `.advanced-options { margin-left: auto }` fix at the 640px breakpoint) doesn't move
  // that number at all, so it needs its own bounding-box check against the viewport.
  const panelBox = await page.getByTestId('advanced-options-panel').boundingBox()
  expect(panelBox).not.toBeNull()
  expect(panelBox!.x).toBeGreaterThanOrEqual(0)
  expect(panelBox!.x + panelBox!.width).toBeLessThanOrEqual(375)

  await closeAdvancedOptions(page)

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('cancelling or closing a meeting asks for confirmation first', async ({ page }) => {
  await page.goto('/')

  const topic = `E2E cancel confirm ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  await openAdvancedOptions(page)

  // Dismissing the confirm dialog must leave the meeting untouched.
  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('無法從介面復原')
    await dialog.dismiss()
  })
  await page.getByTestId('cancel-meeting-button').click()
  await expect(page.getByTestId('operation-status')).not.toContainText('狀態：cancelled')

  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('無法從介面復原')
    await dialog.accept()
  })
  await page.getByTestId('cancel-meeting-button').click()
  await closeAdvancedOptions(page)
  await expect(page.getByTestId('operation-status')).toContainText('狀態：cancelled')

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})
