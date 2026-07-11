import { expect, test } from '@playwright/test'

test('keeps transcript search and workspace in the main column', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByTestId('meeting-list')).toBeVisible()
  await expect(page.getByTestId('transcript-search')).toBeVisible()
  await expect(page.getByTestId('step-timeline')).toBeVisible()

  const sidebar = await page.getByTestId('meeting-list').boundingBox()
  const search = await page.getByTestId('transcript-search').boundingBox()
  const timeline = await page.getByTestId('step-timeline').boundingBox()
  expect(sidebar).not.toBeNull()
  expect(search).not.toBeNull()
  expect(timeline).not.toBeNull()

  expect(search!.x).toBeGreaterThanOrEqual(sidebar!.x + sidebar!.width - 1)
  expect(timeline!.x).toBeGreaterThanOrEqual(sidebar!.x + sidebar!.width - 1)
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
  await page.getByLabel('會議主題').fill(topic)
  await page.getByTestId('create-meeting-button').click()

  const sidebarMeetingId = await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .locator('.meeting-id-text')
    .innerText()

  await expect(page.getByTestId('meeting-id-display')).toHaveText(sidebarMeetingId)

  const copyButton = page.getByTestId('copy-meeting-id-button')
  await expect(copyButton).toContainText('複製')
  await copyButton.click()
  await expect(copyButton).toContainText('已複製')

  const clipboardText = await page.evaluate(() => navigator.clipboard.readText())
  expect(clipboardText).toBe(sidebarMeetingId)

  // Feedback reverts to the plain "複製" label ~1.5s after copying. "已複製" also
  // contains "複製" as a substring, so assert the "已" prefix is specifically gone
  // rather than just polling for "複製" (which would trivially match immediately).
  await expect(copyButton).not.toContainText('已複製')
  await expect(copyButton).toContainText('複製')

  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('user can run a mock meeting and add chair feedback', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByTestId('meeting-list')).toBeVisible()
  await expect(page.getByTestId('blue-model-select')).toBeVisible()
  await expect(page.getByTestId('red-model-select')).toBeVisible()
  await expect(page.getByTestId('judge-model-select')).toBeVisible()

  const topic = `E2E mock meeting ${Date.now()}`
  await page.getByLabel('會議主題').fill(topic)
  await page.getByTestId('create-meeting-button').click()

  await expect(page.getByTestId('transcript-preview')).toContainText('No transcript yet')
  await expect(page.getByTestId('step-timeline')).toContainText('open')
  await expect(page.getByTestId('operation-status')).toContainText('狀態：idle')

  await page.getByTestId('meeting-search-input').fill(topic)
  await expect(page.getByTestId('meeting-list')).toContainText(topic)
  await page.getByTestId('meeting-status-filter').selectOption('open')
  await expect(page.getByTestId('meeting-list')).toContainText('open')

  await page.getByTestId('blue-model-select').selectOption('mock-slow')
  await page.getByTestId('red-model-select').selectOption('mock-slow')
  await page.getByTestId('judge-model-select').selectOption('mock-slow')
  await page.getByTestId('test-blue-model-button').click()
  await expect(page.getByTestId('model-test-status')).toContainText('Blue: available')
  await expect(page.getByTestId('model-test-status')).toContainText('測試')
  await page.getByTestId('start-meeting-button').click()

  // The role queue is pushed synchronously before the network call, so the Blue card
  // flips to "thinking" the instant the button is clicked - not racy.
  await expect(page.getByTestId('role-status-card-blue')).toHaveAttribute('data-status', 'thinking')
  await expect(page.getByTestId('role-status-card-red')).toHaveAttribute('data-status', 'waiting')

  await expect(page.getByTestId('operation-status')).toContainText('狀態：running')
  await expect(page.getByTestId('start-meeting-button')).toContainText('執行中...')
  await expect(page.getByTestId('step-timeline')).toContainText('blue-propose')
  // NOTE: we don't assert an intermediate "Red is thinking" state here. Each mock step
  // only takes ~300ms, so the window between blue-propose landing and red-critique
  // landing is too narrow to poll reliably - see the dedicated failed/retry test below
  // for a deterministic (optimistic, pre-network) assertion of the thinking state instead.
  await expect(page.getByTestId('operation-status')).toContainText('狀態：running')
  await expect(page.getByTestId('step-timeline')).toContainText('red-critique')
  await expect(page.getByTestId('step-timeline')).toContainText('blue-revise')
  await expect(page.getByTestId('step-timeline')).toContainText('judge-decide')
  await expect(page.getByTestId('debug-panel')).toContainText('"status": "completed"')
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')
  await expect(page.getByTestId('operation-status')).toContainText('最後步驟：judge-decide')
  await expect(page.getByTestId('role-output-panel')).toContainText('Role Outputs')
  await expect(page.getByTestId('role-output-panel')).toContainText('blue-propose')
  await expect(page.getByTestId('role-output-panel')).toContainText('Recommendation')

  await expect(page.getByTestId('role-status-card-blue')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-status-card-red')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-status-card-judge')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-status-card-judge')).toContainText('Mock response')
  await expect(page.getByTestId('role-status-card-judge')).toContainText('建議')

  const toolbarRoleBadges = page.locator('.toolbar').getByTestId('role-badge')
  await expect(toolbarRoleBadges.nth(0)).toHaveClass(/role-blue/)
  await expect(toolbarRoleBadges.nth(0).locator('img')).toHaveAttribute('alt', 'Blue')
  await expect(toolbarRoleBadges.nth(1)).toHaveClass(/role-red/)
  await expect(toolbarRoleBadges.nth(2)).toHaveClass(/role-judge/)
  const timelineRoleBadges = page.getByTestId('step-timeline').getByTestId('role-badge')
  await expect(timelineRoleBadges.filter({ hasText: 'Blue' }).first()).toHaveClass(/role-blue/)
  await expect(timelineRoleBadges.filter({ hasText: 'Red' }).first()).toHaveClass(/role-red/)
  await expect(timelineRoleBadges.filter({ hasText: 'Judge' }).first()).toHaveClass(/role-judge/)
  const outputRoleBadges = page.getByTestId('role-output-panel').getByTestId('role-badge')
  await expect(outputRoleBadges.filter({ hasText: 'Blue' }).first().locator('img')).toHaveAttribute('alt', 'Blue')
  await expect(page.getByTestId('transcript-preview')).toContainText('## Blue - blue-propose')
  await expect(page.getByTestId('transcript-preview')).toContainText('## Judge - judge-decide')

  await expect(page.getByTestId('start-meeting-button')).toContainText('繼續討論')

  await page.getByTestId('chair-message-input').fill('主席補充：請先限制在一週可以完成的方案。')
  await page.getByTestId('send-chair-message-button').click()

  await expect(page.getByTestId('step-timeline')).toContainText('human-message')
  await expect(page.getByTestId('debug-panel')).toContainText('"role": "Human"')
  await expect(page.getByTestId('operation-status')).toContainText('狀態：waiting')
  await expect(page.getByTestId('transcript-preview')).toContainText(
    '主席補充：請先限制在一週可以完成的方案。',
  )
  await expect(page.getByTestId('chair-message-input')).toHaveValue('')

  await page.getByTestId('transcript-search-input').fill('一週可以完成的方案')
  await page.getByTestId('transcript-search-button').click()
  await expect(page.getByTestId('transcript-search-results')).toContainText(topic)

  page.once('dialog', async (dialog) => {
    expect(dialog.type()).toBe('prompt')
    await dialog.accept('主席修正：限制放寬到兩週。')
  })
  await page.getByTestId('edit-message-button').click()
  await expect(page.getByTestId('step-timeline')).toContainText('human-message')
  await expect(page.getByTestId('transcript-preview')).toContainText('主席修正：限制放寬到兩週。')
  await expect(page.getByTestId('transcript-preview')).toContainText('（訂正）')

  await page.getByTestId('request-blue-response-button').click()

  await expect(page.getByTestId('step-timeline')).toContainText('directed-1-blue-response')
  await expect(page.getByTestId('debug-panel')).toContainText('"interaction_type": "directed-role-response"')
  await expect(page.getByTestId('transcript-preview')).toContainText(
    '## Blue - directed-1-blue-response',
  )

  await expect(page.getByTestId('role-sequence-controls')).toBeVisible()
  await page.getByTestId('sequence-preset-select').selectOption('red-blue-judge')
  await page.getByTestId('run-sequence-button').click()

  // Sequence roles are also pushed synchronously before the network call.
  await expect(page.getByTestId('role-status-card-red')).toHaveAttribute('data-status', 'thinking')

  await expect(page.getByTestId('step-timeline')).toContainText('sequence-1-red-response')
  await expect(page.getByTestId('step-timeline')).toContainText('sequence-1-blue-response')
  await expect(page.getByTestId('step-timeline')).toContainText('sequence-1-judge-response')
  await expect(page.getByTestId('debug-panel')).toContainText('"interaction_type": "role-sequence-response"')
  await expect(page.getByTestId('transcript-preview')).toContainText(
    '## Red - sequence-1-red-response',
  )
  await expect(page.getByTestId('transcript-preview')).toContainText(
    '## Judge - sequence-1-judge-response',
  )

  await page.getByTestId('start-meeting-button').click()

  await expect(page.getByTestId('step-timeline')).toContainText('round-2-blue-propose')
  await expect(page.getByTestId('step-timeline')).toContainText('round-2-judge-decide')
  await expect(page.getByTestId('transcript-preview')).toContainText('## Blue - round-2-blue-propose')

  await page.getByTestId('close-meeting-button').click()

  await page.getByTestId('meeting-status-filter').selectOption('all')
  await expect(page.getByTestId('step-timeline')).toContainText('closed')
  await expect(page.getByTestId('meeting-list')).toContainText('closed')
  await expect(page.getByTestId('operation-status')).toContainText('狀態：closed')
  await expect(page.getByTestId('transcript-preview')).toContainText('**Status:** closed')
  await expect(page.getByTestId('start-meeting-button')).toBeDisabled()
  await expect(page.getByTestId('cancel-meeting-button')).toBeDisabled()
  await expect(page.getByTestId('close-meeting-button')).toBeDisabled()
  await expect(page.getByTestId('chair-message-input')).toBeDisabled()
  await expect(page.getByTestId('send-chair-message-button')).toBeDisabled()
  await expect(page.getByTestId('request-blue-response-button')).toBeDisabled()
  await expect(page.getByTestId('request-red-response-button')).toBeDisabled()
  await expect(page.getByTestId('request-judge-response-button')).toBeDisabled()
  await expect(page.getByTestId('run-sequence-button')).toBeDisabled()
  await expect(page.getByTestId('edit-message-button').first()).toBeDisabled()

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

  await expect(meetingRow.getByTestId('pin-meeting-button')).toHaveAttribute('aria-label', `釘選 ${topic}`)
  await meetingRow.getByTestId('pin-meeting-button').click()
  await expect(meetingRow.getByTestId('pin-meeting-button')).toHaveAttribute('aria-label', `取消釘選 ${topic}`)

  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('無法復原')
    await dialog.accept()
  })
  await meetingRow.getByTestId('delete-meeting-button').click()
  await expect(page.getByTestId('meeting-list')).not.toContainText(topic)
  await expect(page.getByTestId('step-timeline')).toContainText('尚未選擇會議')
})

test('shows a connection error banner when the backend is unreachable on load', async ({ page }) => {
  await page.route('**/models', (route) => route.abort('connectionrefused'))

  await page.goto('/')

  await expect(page.getByTestId('app-error')).toBeVisible()
  await expect(page.getByTestId('meeting-list')).toBeVisible()
})

test('role status card shows failed state, halts the rest of the round, and recovers via retry', async ({
  page,
}) => {
  await page.goto('/')

  const topic = `E2E failing role card ${Date.now()}`
  await page.getByLabel('會議主題').fill(topic)
  await page.getByTestId('create-meeting-button').click()

  // mock-broken raises immediately (missing base_url/model), no network call involved.
  await page.getByTestId('blue-model-select').selectOption('mock-broken')
  await page.getByTestId('red-model-select').selectOption('mock-slow')
  await page.getByTestId('judge-model-select').selectOption('mock-slow')

  await page.getByTestId('start-meeting-button').click()

  await expect(page.getByTestId('role-status-card-blue')).toHaveAttribute('data-status', 'failed')
  await expect(page.getByTestId('role-status-card-blue')).toContainText('base_url')

  // The backend halts the fixed round after the first failure, so Red and Judge never run.
  await expect(page.getByTestId('role-status-card-red')).toHaveAttribute('data-status', 'waiting')
  await expect(page.getByTestId('role-status-card-red')).not.toContainText('排隊中')
  await expect(page.getByTestId('role-status-card-judge')).toHaveAttribute('data-status', 'waiting')
  await expect(page.getByTestId('step-timeline')).not.toContainText('red-critique')

  const retryButton = page.getByTestId('role-status-card-blue').getByTestId('role-status-retry-button')
  await expect(retryButton).toBeVisible()

  // Fix the broken assignment before retrying, same as a real operator would.
  await page.getByTestId('blue-model-select').selectOption('mock-slow')
  await retryButton.click()

  // retrySelectedStep pushes the whole remaining fixed-round tail (Blue, Red, Blue, Judge
  // for a blue-propose retry), so the card flips to "thinking" immediately on click.
  await expect(page.getByTestId('role-status-card-blue')).toHaveAttribute('data-status', 'thinking')

  await expect(page.getByTestId('step-timeline')).toContainText('judge-decide')
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')
  await expect(page.getByTestId('role-status-card-blue')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-status-card-red')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-status-card-judge')).toHaveAttribute('data-status', 'completed')

  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})
