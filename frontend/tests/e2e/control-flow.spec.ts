import { expect, test, type Page, type Route } from '@playwright/test'

// The whole UI is now a stage with modals/drawers layered on top of it, so most flows
// need a small amount of "open this surface, do the thing, close it" choreography.
// These helpers keep the actual test bodies readable.

async function createMeetingViaNewCase(
  page: Page,
  topic: string,
  options: {
    modeId?: string
    inputs?: Record<string, string>
    caseFiles?: Array<{ title: string; content: string; visibleRoles: string[] }>
    modelAssignments?: Record<string, string>
  } = {},
) {
  const modeId = options.modeId ?? 'red-blue'
  await page.getByTestId('new-case-button').click()
  // NewCaseModal step 1 (mode picker): as of mode-system slice B, every `relay` mode
  // (red-blue/courtroom/debate) has a live "選擇此模式" button - the three `parallel`
  // modes still render but stay disabled ("即將推出") until slice C.
  await page
    .getByTestId(`mode-select-card-${modeId}`)
    .getByRole('button', { name: '選擇此模式' })
    .click()
  // Step 2 (participant setup): the topic input moved here from the old flat form.
  await page.getByLabel('會議主題').fill(topic)
  // debate's position_a/position_b (or any future mode's `kind: 'text'` inputs) render as
  // one labeled field per input id - see NewCaseModal.vue's textInputs.
  for (const [inputId, value] of Object.entries(options.inputs ?? {})) {
    await page.getByTestId(`mode-input-${inputId}`).fill(value)
  }
  for (const [role, modelId] of Object.entries(options.modelAssignments ?? {})) {
    await page.getByTestId(`new-case-${role.toLowerCase()}-model-select`).selectOption(modelId)
  }
  for (const [index, file] of (options.caseFiles ?? []).entries()) {
    const fileNumber = index + 1
    await page.getByTestId('add-case-file-button').click()
    const expectedAnchor = fileNumber === 1 ? '[證物一]' : '[證物二]'
    await expect(page.getByTestId(`case-file-${fileNumber}-evidence-anchor`)).toHaveText(
      expectedAnchor,
    )
    await page.getByTestId(`case-file-${fileNumber}-title`).fill(file.title)
    await page.getByTestId(`case-file-${fileNumber}-content`).fill(file.content)
    for (const role of file.visibleRoles) {
      await page.getByTestId(`case-file-${fileNumber}-role-${role}`).check()
    }
  }
  if (options.caseFiles?.length) {
    const totalChars = options.caseFiles.reduce((total, file) => total + file.content.length, 0)
    await expect(page.getByTestId('case-file-cost-note')).toContainText(
      `目前 ${totalChars} / 120000 字元`,
    )
  }
  await page.getByTestId('create-meeting-button').click()
  // NewCaseModal closes itself once createNewMeeting() resolves.
  await expect(page.getByTestId('new-case-modal')).not.toBeVisible()
}

test('New Case persists the complete relay model roster and reload hydrates that meeting', async ({
  page,
}) => {
  let createPayload: Record<string, unknown> | null = null
  await page.route('**/meetings', async (route) => {
    if (route.request().method() === 'POST') {
      createPayload = route.request().postDataJSON() as Record<string, unknown>
    }
    await route.continue()
  })
  await page.goto('/')

  const topic = `E2E persisted relay assignment ${Date.now()}`
  await createMeetingViaNewCase(page, topic, {
    modelAssignments: {
      Blue: 'mock-slow',
      Red: 'mock-fast',
      Judge: 'mock-broken',
    },
  })

  expect(createPayload).toMatchObject({
    participants: [
      { role_id: 'Blue', model_config_id: 'mock-slow' },
      { role_id: 'Red', model_config_id: 'mock-fast' },
      { role_id: 'Judge', model_config_id: 'mock-broken' },
    ],
  })
  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-slow')
  await expect(page.getByTestId('seat-model-label-red')).toHaveText('Mock · mock-fast')
  await expect(page.getByTestId('seat-model-label-judge')).toHaveText('Custom OpenAI-compatible · mock-broken')

  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()
  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-slow')
  await expect(page.getByTestId('seat-model-label-red')).toHaveText('Mock · mock-fast')
  await expect(page.getByTestId('seat-model-label-judge')).toHaveText('Custom OpenAI-compatible · mock-broken')
})

test('Settings persists complete participant assignments across reload', async ({ page }) => {
  const replacementPayloads: Array<Record<string, string>> = []
  await page.route('**/meetings/*/participant-models', async (route) => {
    replacementPayloads.push((route.request().postDataJSON() as { models: Record<string, string> }).models)
    await route.continue()
  })
  await page.goto('/')

  const topic = `E2E persisted Settings assignment ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  await setModelsInSettings(page, {
    blue: 'mock-slow',
    red: 'mock-fast',
    judge: 'mock-broken',
  })
  await closeSettings(page)

  expect(replacementPayloads.at(-1)).toEqual({
    Blue: 'mock-slow',
    Red: 'mock-fast',
    Judge: 'mock-broken',
  })
  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()
  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-slow')
  await expect(page.getByTestId('seat-model-label-red')).toHaveText('Mock · mock-fast')
  await expect(page.getByTestId('seat-model-label-judge')).toHaveText('Custom OpenAI-compatible · mock-broken')
})

test('Settings rolls back a rejected participant assignment and shows the server error', async ({
  page,
}) => {
  await page.goto('/')
  await createMeetingViaNewCase(page, `E2E assignment rollback ${Date.now()}`)
  await page.getByTestId('settings-button').click()
  await expect(page.getByTestId('blue-model-select')).toHaveValue('mock-fast')
  await page.route(/\/meetings\/[^/]+\/participant-models$/, (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Assignment save failed' }),
    }),
  )

  await page.getByTestId('blue-model-select').selectOption('mock-slow')

  await expect(page.getByTestId('assignment-update-error')).toHaveText('Assignment save failed')
  await expect(page.getByTestId('blue-model-select')).toHaveValue('mock-fast')
  await closeSettings(page)
  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-fast')
})

test('a delayed assignment save cannot overwrite a meeting selected while it was pending', async ({
  page,
}) => {
  await page.goto('/')
  const topicA = `E2E delayed assignment A ${Date.now()}`
  const topicB = `E2E delayed assignment B ${Date.now()}`
  await createMeetingViaNewCase(page, topicA)
  const meetingAId = await page.getByTestId('meeting-id-display').innerText()
  await createMeetingViaNewCase(page, topicB, {
    modelAssignments: { Blue: 'mock-broken' },
  })
  const meetingBId = await page.getByTestId('meeting-id-display').innerText()

  const openTopic = async (topic: string) => {
    await page.getByTestId('past-topics-button').click()
    await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()
  }
  const assignmentUrl = new RegExp(`/meetings/${meetingAId}/participant-models$`)

  await openTopic(topicA)
  let releaseSuccess!: () => void
  const successGate = new Promise<void>((resolve) => {
    releaseSuccess = resolve
  })
  let successIntercepted = false
  await page.route(assignmentUrl, async (route) => {
    successIntercepted = true
    await successGate
    const response = await route.fetch()
    await route.fulfill({ response })
  })
  await page.getByTestId('settings-button').click()
  const successResponse = page.waitForResponse(assignmentUrl)
  await page.getByTestId('blue-model-select').selectOption('mock-slow')
  await expect.poll(() => successIntercepted).toBe(true)
  await closeSettings(page)
  await openTopic(topicB)
  releaseSuccess()
  await successResponse

  await expect(page.getByTestId('meeting-id-display')).toHaveText(meetingBId)
  await expect(page.getByTestId('seat-model-label-blue')).toContainText('mock-broken')

  await page.unroute(assignmentUrl)
  await openTopic(topicA)
  let releaseFailure!: () => void
  const failureGate = new Promise<void>((resolve) => {
    releaseFailure = resolve
  })
  let failureIntercepted = false
  await page.route(assignmentUrl, async (route) => {
    failureIntercepted = true
    await failureGate
    await route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Delayed A save failed' }),
    })
  })
  await page.getByTestId('settings-button').click()
  const failureResponse = page.waitForResponse(assignmentUrl)
  await page.getByTestId('blue-model-select').selectOption('mock-broken')
  await expect.poll(() => failureIntercepted).toBe(true)
  await closeSettings(page)
  await openTopic(topicB)
  releaseFailure()
  await failureResponse

  await expect(page.getByTestId('meeting-id-display')).toHaveText(meetingBId)
  await expect(page.getByTestId('seat-model-label-blue')).toContainText('mock-broken')
  await page.getByTestId('settings-button').click()
  await expect(page.getByTestId('assignment-update-error')).toHaveCount(0)
})

test('a deleted assigned model shows the backend fallback warning without persisting it', async ({
  page,
}) => {
  const modelsResponsePromise = page.waitForResponse(
    (response) => response.request().method() === 'GET' && response.url().endsWith('/models'),
  )
  await page.goto('/')
  const apiOrigin = new URL((await modelsResponsePromise).url()).origin
  const deletedModelId = `e2e-deleted-assignment-${Date.now()}`
  expect(
    (
      await page.request.post(`${apiOrigin}/models`, {
        data: { id: deletedModelId, adapter: 'mock' },
      })
    ).ok(),
  ).toBeTruthy()
  await page.reload()

  const topic = `E2E deleted assignment fallback ${Date.now()}`
  await createMeetingViaNewCase(page, topic, {
    modelAssignments: { Blue: deletedModelId },
  })
  const meetingId = await page.getByTestId('meeting-id-display').innerText()
  expect((await page.request.delete(`${apiOrigin}/models/${deletedModelId}`)).ok()).toBeTruthy()

  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()
  await page.getByTestId('settings-button').click()
  await expect(page.getByTestId('assignment-fallback-warning')).toContainText(deletedModelId)

  const projected = await (await page.request.get(`${apiOrigin}/meetings/${meetingId}`)).json()
  const blue = projected.participants.find(
    (participant: { role_id: string }) => participant.role_id === 'Blue',
  )
  expect(blue.model_assignment_source).toBe('default')
  expect(blue.model_assignment_warning).toContain(deletedModelId)
})

test('run actions omit frontend model maps and rely on the meeting assignment', async ({ page }) => {
  const runBodies: Record<string, unknown>[] = []
  page.on('request', (request) => {
    if (
      request.method() === 'POST' &&
      (/\/start$/.test(request.url()) ||
        /\/roles\/[^/]+\/respond$/.test(request.url()) ||
        /\/sequences$/.test(request.url()))
    ) {
      runBodies.push({ url: request.url(), body: request.postDataJSON() })
    }
  })
  await page.goto('/')
  await createMeetingViaNewCase(page, `E2E authoritative run assignment ${Date.now()}`)

  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')
  await openRoleDrawer(page, 'blue')
  await page.getByTestId('request-blue-response-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')
  await closeRoleDrawer(page)
  await openAdvancedOptions(page)
  await page.getByTestId('run-sequence-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')

  expect(runBodies.map(({ url, body }) => ({ path: new URL(url as string).pathname, body }))).toEqual([
    { path: expect.stringMatching(/\/start$/), body: {} },
    { path: expect.stringMatching(/\/roles\/Blue\/respond$/), body: {} },
    { path: expect.stringMatching(/\/sequences$/), body: { roles: ['Red', 'Blue', 'Judge'] } },
  ])
})

test('meeting switches hydrate isolated assignments and New Case keeps local defaults', async ({
  page,
}) => {
  await page.goto('/')
  const topicA = `E2E isolated assignment A ${Date.now()}`
  const topicB = `E2E isolated assignment B ${Date.now()}`
  await createMeetingViaNewCase(page, topicA, {
    modelAssignments: { Blue: 'mock-slow' },
  })
  await createMeetingViaNewCase(page, topicB)
  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-fast')

  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topicA }).locator('.meeting-item').click()
  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-slow')
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topicB }).locator('.meeting-item').click()
  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-fast')

  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-red-blue')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await expect(page.getByTestId('new-case-blue-model-select')).toHaveValue('mock-fast')
})

test('legacy recovery hydration trusts the participant projection instead of event history', async ({
  page,
}) => {
  await page.goto('/')
  const topic = `E2E legacy recovered assignment ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  const meetingId = await page.getByTestId('meeting-id-display').innerText()
  await page.route(new RegExp(`/meetings/${meetingId}$`), async (route) => {
    const response = await route.fetch()
    const meeting = await response.json()
    meeting.participants = meeting.participants.map(
      (participant: { role_id: string; model_config_id: string; model_assignment_source: string }) =>
        participant.role_id === 'Blue'
          ? {
              ...participant,
              model_config_id: 'mock-slow',
              model_assignment_source: 'latest-event',
            }
          : participant,
    )
    meeting.events = [
      {
        event_id: 'contradictory-event',
        meeting_id: meetingId,
        step_id: 'blue-propose',
        role: 'Blue',
        status: 'completed',
        model_config_id: 'mock-broken',
      },
    ]
    await route.fulfill({ response, json: meeting })
  })

  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()

  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-slow')
})

// Generalized model-assignment helper (mode-system slice B task 9 made the model-select
// testid role-derived - `${role.toLowerCase()}-model-select` - for any mode's roster, not
// just red-blue's Blue/Red/Judge). Leaves the Settings modal open, same as before.
async function setRoleModelsInSettings(page: Page, assignments: Record<string, string>) {
  await page.getByTestId('settings-button').click()
  for (const [role, model] of Object.entries(assignments)) {
    const select = page.getByTestId(`${role.toLowerCase()}-model-select`)
    if ((await select.inputValue()) === model) continue
    const response = page.waitForResponse(
      (candidate) =>
        candidate.request().method() === 'PUT' &&
        candidate.url().includes('/participant-models'),
    )
    await select.selectOption(model)
    await response
    await expect(select).toBeEnabled()
  }
}

async function setModelsInSettings(
  page: Page,
  models: { blue: string; red: string; judge: string },
) {
  await setRoleModelsInSettings(page, { Blue: models.blue, Red: models.red, Judge: models.judge })
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

// ModelManagerPanel.vue renders one row per model, keyed by `data-model-id` (Task 5) -
// scoping to a single row this way is exact, unlike a text filter, since model ids can be
// substrings of each other (e.g. 'mock' vs 'mock-fast').
function modelManagerRow(page: Page, modelId: string) {
  return page.locator(`[data-testid="model-manager-row"][data-model-id="${modelId}"]`)
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
  await createMeetingViaNewCase(page, topic, {
    caseFiles: [
      {
        title: '上線檢查表',
        content: '驗收測試已完成，回滾演練待確認。',
        visibleRoles: ['Judge'],
      },
    ],
  })

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
  await expect(page.getByTestId('rich-verdict-decision')).toContainText(
    'approve-with-conditions',
  )
  await expect(page.getByTestId('rich-verdict-findings')).toContainText('Mock finding')
  await expect(page.getByTestId('rich-verdict-findings')).toContainText('[證物一]')
  await expect(page.getByTestId('rich-verdict-conditions')).toContainText('Verify the result.')
  await expect(page.getByTestId('rich-verdict-unresolved')).toContainText(
    'Is more evidence available?',
  )
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
  await expect(page.getByTestId('role-output-panel')).toContainText('Arguments')
  await expect(page.getByTestId('role-output-panel')).toContainText('Mock argument')
  await expect(page.getByTestId('rich-verdict-decision')).toHaveCount(0)
  await closeRoleDrawer(page)

  await openAdvancedOptions(page)
  await expect(page.getByTestId('role-sequence-controls')).toBeVisible()
  // Preset ids are now generic (mode-system slice B task 9): 'members-reversed-adj' is
  // red-blue's [Red, Blue, Judge] preset, same roles/label as the old 'red-blue-judge' id.
  await page.getByTestId('sequence-preset-select').selectOption('members-reversed-adj')
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
  let retryBody: unknown
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/steps\/[^/]+\/retry$/.test(request.url())) {
      retryBody = request.postDataJSON()
    }
  })
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
  await expect.poll(() => retryBody).toEqual({})

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

test('records drawer keeps failed attempt diagnostics collapsed and copies safe JSON', async ({
  page,
  context,
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/')

  const topic = `E2E attempt diagnostics ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  await setModelsInSettings(page, { blue: 'mock-broken', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)
  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'failed')

  await page.getByTestId('records-button').click()
  const diagnostics = page.getByTestId('meeting-attempt-diagnostics')
  await expect(diagnostics).toHaveCount(1)
  await expect(diagnostics).not.toHaveAttribute('open', '')
  await diagnostics.locator('summary').click()
  await expect(diagnostics).toHaveAttribute('open', '')
  await expect(diagnostics).toContainText('configuration_error')
  await expect(diagnostics).toContainText('mock-broken')
  await expect(diagnostics).toContainText('openai-compatible-http')

  await diagnostics.getByTestId('copy-attempt-diagnostics').click()
  const copied = JSON.parse(await page.evaluate(() => navigator.clipboard.readText()))
  expect(copied).toMatchObject({
    failure_kind: 'configuration_error',
    model_config_id: 'mock-broken',
    adapter: 'openai-compatible-http',
    attempt: 1,
    retry_scheduled: false,
  })
  expect(copied.prompt_messages[0].role).toBe('user')
  expect(copied).not.toHaveProperty('command')
  expect(copied).not.toHaveProperty('env')

  await page.getByTestId('records-close-button').click()
  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('records drawer announces clipboard rejection without an unhandled promise', async ({ page }) => {
  await page.goto('/')
  await page.evaluate(() => {
    const trackedWindow = window as typeof window & { diagnosticUnhandledRejections: string[] }
    trackedWindow.diagnosticUnhandledRejections = []
    window.addEventListener('unhandledrejection', (event) => {
      trackedWindow.diagnosticUnhandledRejections.push(String(event.reason))
    })
    Object.defineProperty(navigator.clipboard, 'writeText', {
      configurable: true,
      value: () => Promise.reject(new Error('clipboard denied')),
    })
  })

  const topic = `E2E rejected diagnostic copy ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  await setModelsInSettings(page, { blue: 'mock-broken', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)
  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'failed')
  await page.getByTestId('records-button').click()
  const diagnostics = page.getByTestId('meeting-attempt-diagnostics')
  await diagnostics.locator('summary').click()

  await diagnostics.getByTestId('copy-attempt-diagnostics').click()

  await expect(diagnostics.getByTestId('copy-attempt-diagnostics')).toHaveText('複製失敗')
  await expect(diagnostics.getByTestId('copy-attempt-diagnostics-status')).toHaveText('複製失敗')
  expect(
    await page.evaluate(
      () =>
        (window as typeof window & { diagnosticUnhandledRejections: string[] })
          .diagnosticUnhandledRejections,
    ),
  ).toEqual([])

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
  // Mode-system slice B (feat: drive active mode from the selected meeting) replaced the
  // hardcoded English role summary with the active mode's own catalog step labels
  // (ActionBar.vue's roundStepsSummary) - red-blue's are Chinese.
  await expect(page.getByTestId('new-round-panel')).toContainText(
    '藍軍提案 → 紅軍質詢 → 藍軍修訂 → 裁判裁決',
  )
  await page.getByTestId('start-new-round-button').click()

  // startSelectedMeeting pushes the fixed-round queue synchronously before the network
  // call, same as the main CTA - Blue flips to "thinking" immediately.
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'thinking')
  await closeAdvancedOptions(page)

  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed', {
    timeout: 15000,
  })

  // The queue must actually *drain* back to completed, not just fill and stall - a
  // filtering fix that over-filters (treats round-2's own new events as "already seen"
  // too) would leave seats stuck on "thinking" forever while activity_status still
  // reports completed independently, so this has to be asserted on the seats directly.
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-judge')).toHaveAttribute('data-status', 'completed')

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

test('reloading mid-round still shows the real final state after reopening the meeting', async ({
  page,
}) => {
  await page.goto('/')

  const topic = `E2E reload mid-round ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  const startAccepted = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      response.url().endsWith('/start') &&
      response.status() === 202,
  )
  await page.getByTestId('start-meeting-button').click()
  await startAccepted
  await expect(page.getByTestId('operation-status')).toContainText('狀態：running')

  // The backend keeps running the synchronous /start call regardless of the client, so
  // reloading here throws away every bit of in-memory state (pendingRoles, the
  // seenEventIds bookkeeping in useCouncil.ts) - the reopened meeting has to reconstruct
  // status purely from the reconnect's snapshot, with nothing left in the pending queue
  // to (correctly or incorrectly) reconcile against.
  await page.reload()
  await expect(page.getByTestId('council-stage')).toContainText('尚未選擇會議')

  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()

  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed', { timeout: 15000 })
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

test('switching meetings does not leak pendingRoles state, and a revisited meeting can still start a fresh round', async ({
  page,
}) => {
  await page.goto('/')

  const topicA = `E2E switch meeting A ${Date.now()}`
  await createMeetingViaNewCase(page, topicA)
  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)
  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')

  const topicB = `E2E switch meeting B ${Date.now()}`
  await createMeetingViaNewCase(page, topicB)
  await expect(page.getByTestId('council-stage')).toContainText(topicB)
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'waiting')

  // Revisit meeting A (already fully completed) and start an explicit new round on it -
  // this is exactly the scenario the pendingRoles/seenEventIds race hit: reconnecting
  // the websocket right after pushing the new round's queue, with A's already-completed
  // round-1 events sitting right there in the very next snapshot.
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topicA }).locator('.meeting-item').click()
  await expect(page.getByTestId('council-stage')).toContainText(topicA)

  await openAdvancedOptions(page)
  await page.getByTestId('start-new-round-button').click()
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'thinking')
  await closeAdvancedOptions(page)

  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed', { timeout: 15000 })

  // The queue must actually drain, not just fill and stall - see the identical note in
  // the "開始新回合" test above for why this needs its own assertion on the seats.
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-judge')).toHaveAttribute('data-status', 'completed')

  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('step-timeline')).toContainText('round-2-blue-propose')
  await page.getByTestId('records-close-button').click()

  await page.getByTestId('past-topics-button').click()
  for (const topic of [topicA, topicB]) {
    page.once('dialog', (dialog) => dialog.accept())
    await page
      .getByTestId('meeting-list-item')
      .filter({ hasText: topic })
      .getByTestId('delete-meeting-button')
      .click()
  }
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

test('reopening a closed meeting restores discussion actions', async ({ page }) => {
  await page.goto('/')

  const topic = `E2E reopen ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  await setModelsInSettings(page, { blue: 'mock-fast', red: 'mock-fast', judge: 'mock-fast' })
  await closeSettings(page)

  await openAdvancedOptions(page)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId('close-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：closed')
  await expect(page.getByTestId('start-new-round-button')).toBeDisabled()

  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('重新開啟')
    await dialog.accept()
  })
  await page.getByTestId('reopen-meeting-button').click()

  await expect(page.getByTestId('operation-status')).toContainText('狀態：waiting')
  await expect(page.getByTestId('start-new-round-button')).toBeEnabled()
  await closeAdvancedOptions(page)
})

const ALL_MODE_IDS = ['red-blue', 'courtroom', 'debate', 'brainstorm', 'six-hats', 'persona-testing']
const AVAILABLE_MODE_IDS = ALL_MODE_IDS

test('New Case mode picker shows all six modes and all six can be created', async ({
  page,
}) => {
  await page.goto('/')

  await page.getByTestId('new-case-button').click()
  await expect(page.getByTestId('mode-picker-step')).toBeVisible()

  for (const modeId of ALL_MODE_IDS) {
    await expect(page.getByTestId(`mode-select-card-${modeId}`)).toBeVisible()
  }

  for (const modeId of AVAILABLE_MODE_IDS) {
    const card = page.getByTestId(`mode-select-card-${modeId}`)
    await expect(card.getByRole('button', { name: '選擇此模式' })).toBeEnabled()
  }

  await page.getByTestId('mode-select-card-brainstorm').getByRole('button', { name: '選擇此模式' }).click()
  await expect(page.getByTestId('participant-setup-step')).toBeVisible()
  await expect(page.getByTestId('parallel-member-editor')).toBeVisible()

  await page.getByTestId('new-case-close-button').click()
})

test('mode card SOP expands with the mode SOP steps, and a parallel mode also shows its ring preview', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByTestId('new-case-button').click()

  const redBlueCard = page.getByTestId('mode-select-card-red-blue')
  await expect(redBlueCard.getByTestId('mode-sop-panel')).not.toBeVisible()
  await redBlueCard.getByTestId('mode-sop-toggle').click()
  await expect(redBlueCard.getByTestId('mode-sop-panel')).toBeVisible()
  await expect(redBlueCard.getByTestId('mode-sop-panel')).toContainText('輸入要被驗證的方案主題')
  // red-blue is `relay`, so it never renders the parallel-only ring preview.
  await expect(redBlueCard.getByTestId('mode-ring-preview')).toHaveCount(0)
  await redBlueCard.getByTestId('mode-sop-toggle').click()
  await expect(redBlueCard.getByTestId('mode-sop-panel')).not.toBeVisible()

  // brainstorm is `parallel` with a 2-6 member fanout - its SOP panel additionally shows
  // a ring-seat preview (ringSeatLayout, scenes.ts/modes.ts), sized to the fanout minimum.
  const brainstormCard = page.getByTestId('mode-select-card-brainstorm')
  await brainstormCard.getByTestId('mode-sop-toggle').click()
  await expect(brainstormCard.getByTestId('mode-ring-preview')).toBeVisible()
  await expect(brainstormCard.getByTestId('mode-ring-preview-seat')).toHaveCount(2)

  // six-hats has a fixed 5-member roster (no fanout) - its preview exercises
  // ringSeatLayout's actual *distribution* math (not just a count), so assert the seats
  // are genuinely spread across the arc and symmetric around the center, not bunched up.
  const sixHatsCard = page.getByTestId('mode-select-card-six-hats')
  await sixHatsCard.getByTestId('mode-sop-toggle').click()
  const ringSeats = sixHatsCard.getByTestId('mode-ring-preview-seat')
  await expect(ringSeats).toHaveCount(5)
  const cxValues = await ringSeats.evaluateAll((nodes) => nodes.map((node) => Number(node.getAttribute('cx'))))
  expect(cxValues[0]).toBeCloseTo(12, 0)
  expect(cxValues[2]).toBeCloseTo(50, 0)
  expect(cxValues[4]).toBeCloseTo(88, 0)
  // Symmetric around the center: seat 0 and the last seat are equidistant from x=50,
  // and so are seat 1 and seat 3 - a bunched-up or non-arc layout would fail this.
  expect(cxValues[0] + cxValues[4]).toBeCloseTo(100, 0)
  expect(cxValues[1] + cxValues[3]).toBeCloseTo(100, 0)

  await page.getByTestId('new-case-close-button').click()
})

test('step progress indicator reflects the active relay step during a fixed round', async ({ page }) => {
  await page.goto('/')

  const topic = `E2E step progress ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  await expect(page.getByTestId('step-progress-indicator')).not.toBeVisible()

  await page.getByTestId('start-meeting-button').click()

  // pendingRoles is pushed synchronously before the network call (see startSelectedMeeting),
  // so the indicator reflects step 1/4 (blue-propose) the instant the round starts.
  await expect(page.getByTestId('step-progress-indicator')).toContainText('第 1 步／共 4 步：藍軍提案中')

  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed')
  await expect(page.getByTestId('step-progress-indicator')).not.toBeVisible()

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('TopBar help button opens the mode help drawer with the same mode catalog', async ({ page }) => {
  await page.goto('/')

  await page.getByTestId('mode-help-button').click()
  await expect(page.getByTestId('mode-help-drawer')).toBeVisible()

  for (const modeId of ALL_MODE_IDS) {
    await expect(page.getByTestId(`mode-help-card-${modeId}`)).toBeVisible()
  }
  // Browsing-only: no "選擇此模式"/"即將推出" CTA in the help drawer.
  await expect(page.getByTestId('mode-help-card-red-blue').getByRole('button')).toHaveCount(1)

  await page.getByTestId('mode-help-drawer-close-button').click()
  await expect(page.getByTestId('mode-help-drawer')).not.toBeVisible()
})

test('keeps the New Case mode picker within a 375px viewport without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/')

  await page.getByTestId('new-case-button').click()
  await expect(page.getByTestId('mode-select-card-red-blue')).toBeVisible()

  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBe(await page.evaluate(() => document.documentElement.clientWidth))

  await page.getByTestId('new-case-close-button').click()
})

test('New Case keeps user input when create fails', async ({ page }) => {
  await page.route('**/meetings', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 413,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Case file content exceeds 10 characters: 保留案卷' }),
      })
      return
    }
    await route.continue()
  })
  await page.goto('/')

  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-red-blue')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await page.getByLabel('會議主題').fill('保留這個輸入')
  await page.getByTestId('add-case-file-button').click()
  await page.getByTestId('case-file-1-upload').setInputFiles({
    name: '保留案卷.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('失敗後不應清空這段內容'),
  })
  await page.getByTestId('case-file-1-role-Blue').check()
  await page.getByTestId('create-meeting-button').click()

  await expect(page.getByTestId('new-case-modal')).toBeVisible()
  await expect(page.getByLabel('會議主題')).toHaveValue('保留這個輸入')
  await expect(page.getByTestId('case-file-1-title')).toHaveValue('保留案卷')
  await expect(page.getByTestId('case-file-1-content')).toHaveValue('失敗後不應清空這段內容')
  await expect(page.getByTestId('case-file-1-role-Blue')).toBeChecked()
  await expect(page.getByTestId('case-file-cost-note')).toContainText('目前 11 / 120000 字元')
  await expect(page.getByTestId('case-file-cost-note')).toContainText('粗估約 11 tokens')
  await expect(page.getByTestId('new-case-server-error')).toHaveText(
    'Case file content exceeds 10 characters: 保留案卷',
  )
  await expect(page.getByTestId('new-case-server-error')).toHaveAttribute('role', 'alert')
  await expect(page.getByTestId('app-error')).toContainText('POST /meetings failed: 413')

  await page.getByTestId('case-file-1-content').fill('編輯案卷後應清除舊錯誤')
  await expect(page.getByTestId('new-case-server-error')).not.toBeVisible()
  await page.getByTestId('create-meeting-button').click()
  await expect(page.getByTestId('new-case-server-error')).toBeVisible()
  await page.getByLabel('會議主題').fill('編輯主題後清除舊錯誤')
  await expect(page.getByTestId('new-case-server-error')).not.toBeVisible()
})

test('New Case uses server case file limits and blocks oversized drafts before POST', async ({
  page,
}) => {
  let releaseLimits!: () => void
  const limitsGate = new Promise<void>((resolve) => {
    releaseLimits = resolve
  })
  await page.route('**/case-file-limits', async (route) => {
    await limitsGate
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ per_file_chars: 10, total_chars: 15 }),
    })
  })
  let createRequests = 0
  await page.route('**/meetings', async (route) => {
    if (route.request().method() === 'POST') createRequests += 1
    await route.continue()
  })
  await page.goto('/')
  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-red-blue')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await page.getByLabel('會議主題').fill('容量預檢')
  await page.getByTestId('add-case-file-button').click()
  await page.getByTestId('case-file-1-title').fill('第一份')
  await page.getByTestId('case-file-1-content').fill('abcdefghijk')
  await page.getByTestId('case-file-1-role-Blue').check()

  await expect(page.getByTestId('case-file-limits-status')).toHaveText('正在載入案卷限制…')
  await expect(page.getByTestId('create-meeting-button')).toBeDisabled()
  await page.getByTestId('create-meeting-button').evaluate((button: HTMLButtonElement) =>
    button.click(),
  )
  await expect.poll(() => createRequests).toBe(0)
  releaseLimits()
  await expect(page.getByTestId('case-file-limits-status')).not.toBeVisible()
  await expect(page.getByTestId('case-file-1-char-count')).toHaveText('11 / 10 字元')
  await expect(page.getByTestId('case-file-1-limit-error')).toHaveText(
    '案卷 1 超過單份上限 10 字元',
  )
  await expect(page.getByTestId('case-file-1-limit-error')).toHaveAttribute('role', 'alert')
  await expect(page.getByTestId('case-file-1-content')).toHaveAttribute('aria-invalid', 'true')
  await expect(page.getByTestId('case-file-1-content')).toHaveAttribute(
    'aria-describedby',
    'case-file-1-char-count case-file-1-limit-error',
  )
  await expect(page.getByTestId('case-file-cost-note')).toContainText('目前 11 / 15 字元')
  await expect(page.getByTestId('case-file-cost-note')).toContainText('粗估約 3 tokens')
  await expect(page.getByTestId('case-file-cost-note')).toContainText('可能超出模型 context window')
  await expect(page.getByTestId('create-meeting-button')).toBeDisabled()

  await page.getByTestId('case-file-1-content').fill('abcdefgh')
  await page.getByTestId('add-case-file-button').click()
  await page.getByTestId('case-file-2-title').fill('第二份')
  await page.getByTestId('case-file-2-content').fill('ijklmnop')
  await page.getByTestId('case-file-2-role-Blue').check()

  await expect(page.getByTestId('case-file-total-limit-error')).toHaveText(
    '全部案卷超過總量上限 15 字元',
  )
  await expect(page.getByTestId('case-file-total-limit-error')).toHaveAttribute('role', 'alert')
  await expect(page.getByTestId('create-meeting-button')).toBeDisabled()
  await page.getByTestId('create-meeting-button').evaluate((button: HTMLButtonElement) =>
    button.click(),
  )
  await expect.poll(() => createRequests).toBe(0)
})

test('New Case fails closed and can retry when limits endpoint is unavailable', async ({
  page,
}) => {
  let limitsRequests = 0
  await page.route('**/case-file-limits', (route) => {
    limitsRequests += 1
    if (limitsRequests === 1) {
      return route.fulfill({ status: 503, contentType: 'application/json', body: '{}' })
    }
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ per_file_chars: 10, total_chars: 15 }),
    })
  })
  let createRequests = 0
  await page.route('**/meetings', async (route) => {
    if (route.request().method() === 'POST') createRequests += 1
    await route.continue()
  })
  await page.goto('/')
  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-red-blue')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await page.getByLabel('會議主題').fill('limits unavailable')
  await page.getByTestId('add-case-file-button').click()
  await page.getByTestId('case-file-1-title').fill('draft')
  await page.getByTestId('case-file-1-content').fill('short')
  await page.getByTestId('case-file-1-role-Blue').check()

  await expect(page.getByTestId('case-file-limits-status')).not.toBeVisible()
  await expect(page.getByTestId('case-file-limits-error')).toContainText(
    '無法載入案卷限制，請重試',
  )
  await expect(page.getByTestId('create-meeting-button')).toBeDisabled()
  await page.getByTestId('create-meeting-button').evaluate((button: HTMLButtonElement) =>
    button.click(),
  )
  await expect.poll(() => createRequests).toBe(0)

  await page.getByTestId('retry-case-file-limits-button').click()
  await expect(page.getByTestId('case-file-limits-error')).not.toBeVisible()
  await expect(page.getByTestId('case-file-1-char-count')).toHaveText('5 / 10 字元')
  await expect(page.getByTestId('create-meeting-button')).toBeEnabled()
})

test('New Case ignores an older limits response after reopening the modal', async ({ page }) => {
  let limitsRequests = 0
  let releaseFirst!: () => void
  const firstGate = new Promise<void>((resolve) => {
    releaseFirst = resolve
  })
  await page.route('**/case-file-limits', async (route) => {
    limitsRequests += 1
    if (limitsRequests === 1) {
      await firstGate
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ per_file_chars: 99, total_chars: 100 }),
      })
      return
    }
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ per_file_chars: 7, total_chars: 9 }),
    })
  })
  await page.goto('/')

  await page.getByTestId('new-case-button').click()
  await expect(page.getByTestId('case-file-limits-status')).toBeVisible()
  await page.getByTestId('new-case-close-button').click()
  await page.getByTestId('new-case-button').click()
  await expect.poll(() => limitsRequests).toBe(2)
  await expect(page.getByTestId('case-file-limits-status')).not.toBeVisible()
  await page
    .getByTestId('mode-select-card-red-blue')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await page.getByTestId('add-case-file-button').click()
  await expect(page.getByTestId('case-file-1-char-count')).toHaveText('0 / 7 字元')

  releaseFirst()
  await page.waitForTimeout(100)
  await expect(page.getByTestId('case-file-limits-status')).not.toBeVisible()
  await expect(page.getByTestId('case-file-1-char-count')).toHaveText('0 / 7 字元')
})

test('New Case counts emoji as Unicode code points at the server boundary', async ({ page }) => {
  await page.route('**/case-file-limits', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ per_file_chars: 2, total_chars: 2 }),
    }),
  )
  await page.goto('/')
  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-red-blue')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await page.getByLabel('會議主題').fill('emoji boundary')
  await page.getByTestId('add-case-file-button').click()
  await page.getByTestId('case-file-1-title').fill('emoji')
  await page.getByTestId('case-file-1-role-Blue').check()
  await page.getByTestId('case-file-1-content').fill('😀😀')

  await expect(page.getByTestId('case-file-1-char-count')).toHaveText('2 / 2 字元')
  await expect(page.getByTestId('create-meeting-button')).toBeEnabled()

  await page.getByTestId('case-file-1-content').fill('😀😀😀')
  await expect(page.getByTestId('case-file-1-char-count')).toHaveText('3 / 2 字元')
  await expect(page.getByTestId('create-meeting-button')).toBeDisabled()
})

test('New Case token estimate treats Japanese and Hangul code points conservatively', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-red-blue')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await page.getByTestId('add-case-file-button').click()
  await page.getByTestId('case-file-1-content').fill('かなカナ')
  await expect(page.getByTestId('case-file-cost-note')).toContainText('粗估約 4 tokens')

  await page.getByTestId('case-file-1-content').fill('한글테스트')
  await expect(page.getByTestId('case-file-cost-note')).toContainText('粗估約 5 tokens')

  await page.getByTestId('case-file-1-content').fill('ケーキーーー')
  await expect(page.getByTestId('case-file-cost-note')).toContainText('粗估約 6 tokens')
})

test('New Case clears a stale creation error when parallel members change', async ({ page }) => {
  await page.route('**/meetings', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 413,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Meeting rejected' }),
      })
      return
    }
    await route.continue()
  })
  await page.goto('/')
  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-brainstorm')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await page.getByLabel('會議主題').fill('parallel stale error')
  await page.getByTestId('create-meeting-button').click()
  await expect(page.getByTestId('new-case-server-error')).toHaveText('Meeting rejected')

  await page.getByTestId('parallel-member-increment').click()
  await expect(page.getByTestId('new-case-server-error')).not.toBeVisible()
  await page.getByTestId('create-meeting-button').click()
  await expect(page.getByTestId('new-case-server-error')).toBeVisible()
  await page.getByTestId('parallel-member-1-name').fill('新的委員名稱')
  await expect(page.getByTestId('new-case-server-error')).not.toBeVisible()
})

test('New Case creates a meeting with numbered role-scoped case files', async ({ page }) => {
  let createPayload: Record<string, unknown> | null = null
  await page.route('**/meetings', async (route) => {
    if (route.request().method() === 'POST') {
      createPayload = route.request().postDataJSON() as Record<string, unknown>
    }
    await route.continue()
  })
  await page.goto('/')

  const topic = `E2E case files ${Date.now()}`
  const createResponsePromise = page.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().endsWith('/meetings'),
  )
  await createMeetingViaNewCase(page, topic, {
    modeId: 'courtroom',
    caseFiles: [
      {
        title: '事故時間線',
        content: '10:05 error rate spike\n10:07 rollback started',
        visibleRoles: ['Prosecutor', 'Judge'],
      },
      {
        title: '回滾紀錄',
        content: '10:07 rollback started',
        visibleRoles: ['Defense', 'Judge'],
      },
    ],
  })
  const createResponse = await createResponsePromise

  expect(createPayload).toMatchObject({
    topic,
    mode_id: 'courtroom',
    case_files: [
      {
        title: '事故時間線',
        content: '10:05 error rate spike\n10:07 rollback started',
        visible_roles: ['Prosecutor', 'Judge'],
      },
      {
        title: '回滾紀錄',
        content: '10:07 rollback started',
        visible_roles: ['Defense', 'Judge'],
      },
    ],
  })
  const meetingId = await page.getByTestId('meeting-id-display').innerText()
  const meeting = await page.request.get(`${new URL(createResponse.url()).origin}/meetings/${meetingId}`)
  expect(meeting.ok()).toBeTruthy()
  expect((await meeting.json()).case_files).toMatchObject([
    { evidence_index: 1, citation_anchor: '[證物一]' },
    { evidence_index: 2, citation_anchor: '[證物二]' },
  ])
  await expect(page.getByTestId('role-seat-prosecutor')).toBeVisible()
  await expect(page.getByTestId('role-seat-defense')).toBeVisible()
  await expect(page.getByTestId('role-seat-judge')).toBeVisible()

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('New Case blocks an empty model catalog and seat nameplates follow persisted Settings', async ({
  page,
}) => {
  // New meetings now require a complete assignment roster, so an empty catalog must
  // fail closed before creation instead of producing an unassigned meeting.
  await page.route('**/models', (route) => route.fulfill({ json: [] }))
  await page.goto('/')

  const topic = `E2E seat model label ${Date.now()}`
  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-red-blue')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await page.getByLabel('會議主題').fill(topic)
  await expect(page.getByTestId('new-case-model-error')).toBeVisible()
  await expect(page.getByTestId('create-meeting-button')).toBeDisabled()
  await page.getByTestId('new-case-close-button').click()

  await page.unroute('**/models')
  await page.reload()
  await createMeetingViaNewCase(page, topic)
  // Chairman is the fixed human seat, not a mode role - it never gets a model label.
  await expect(
    page.getByTestId('role-seat-chairman').locator('[data-testid^="seat-model-label"]'),
  ).toHaveCount(0)

  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-fast', judge: 'mock-broken' })
  await closeSettings(page)

  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-slow')
  await expect(page.getByTestId('seat-model-label-red')).toHaveText('Mock · mock-fast')
  await expect(page.getByTestId('seat-model-label-judge')).toHaveText('Custom OpenAI-compatible · mock-broken')
  await expect(page.getByTestId('seat-model-label-blue')).toHaveAttribute('title', 'Mock · mock-slow')

  // Changing the model again in Settings must update the seat immediately -
  // and persist through the explicit participant-model replacement endpoint.
  await page.getByTestId('settings-button').click()
  const saved = page.waitForResponse(
    (response) => response.request().method() === 'PUT' && response.url().includes('/participant-models'),
  )
  await page.getByTestId('blue-model-select').selectOption('mock-fast')
  await saved
  await page.getByTestId('settings-close-button').click()
  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-fast')

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('courtroom mode runs its full four-step relay and renders the Prosecutor/Defense/Judge roster', async ({
  page,
}) => {
  await page.goto('/')

  const topic = `E2E courtroom happy path ${Date.now()}`
  await createMeetingViaNewCase(page, topic, { modeId: 'courtroom' })

  // Selecting courtroom in the mode picker produces a courtroom-shaped roster, not the
  // red-blue triple - CouncilStage's seat testids are role-derived (role.toLowerCase()).
  await expect(page.getByTestId('role-seat-prosecutor')).toBeVisible()
  await expect(page.getByTestId('role-seat-defense')).toBeVisible()
  await expect(page.getByTestId('role-seat-judge')).toBeVisible()
  await expect(page.getByTestId('role-seat-blue')).toHaveCount(0)

  await setRoleModelsInSettings(page, { Prosecutor: 'mock-slow', Defense: 'mock-slow', Judge: 'mock-slow' })
  await closeSettings(page)

  await page.getByTestId('start-meeting-button').click()

  // Same synchronous pendingRoles push as the red-blue flow - Prosecutor (courtroom's
  // first step) flips to "thinking" immediately.
  await expect(page.getByTestId('role-seat-prosecutor')).toHaveAttribute('data-status', 'thinking')

  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed', { timeout: 15000 })
  await expect(page.getByTestId('operation-status')).toContainText('最後步驟：courtroom-verdict')
  await expect(page.getByTestId('role-seat-prosecutor')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-defense')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-judge')).toHaveAttribute('data-status', 'completed')

  // Full step_id sequence in the records drawer confirms the relay actually ran
  // courtroom's mode-derived plan (courtroom-charge -> courtroom-defense ->
  // courtroom-rebuttal -> courtroom-verdict), not the red-blue fixed round.
  await page.getByTestId('records-button').click()
  const courtroomStepIds = ['courtroom-charge', 'courtroom-defense', 'courtroom-rebuttal', 'courtroom-verdict']
  for (const stepId of courtroomStepIds) {
    await expect(page.getByTestId('step-timeline')).toContainText(stepId)
  }
  // Presence alone (the loop above) would also pass if the steps ran out of order -
  // execution order is the relay executor's core guarantee, so read each row's step_id
  // (RecordsDrawer.vue renders `events` - and therefore these rows - in event order) and
  // assert courtroom's four steps appear in ascending position, not just somewhere.
  const renderedStepIds = await page.getByTestId('step-timeline').locator('.timeline-row strong').allTextContents()
  const observedPositions = courtroomStepIds.map((stepId) => renderedStepIds.indexOf(stepId))
  expect(observedPositions.every((position) => position >= 0)).toBe(true)
  expect(observedPositions).toEqual([...observedPositions].sort((a, b) => a - b))
  await page.getByTestId('records-close-button').click()

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('brainstorm mode creates member instances and runs fanout plus synthesis', async ({ page }) => {
  await page.goto('/')

  const topic = `E2E brainstorm happy path ${Date.now()}`
  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-brainstorm')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await page.getByLabel('會議主題').fill(topic)
  await expect(page.getByTestId('parallel-member-count')).toHaveText('2')
  await page.getByTestId('parallel-member-increment').click()
  await expect(page.getByTestId('parallel-member-count')).toHaveText('3')
  await page.getByTestId('parallel-member-1-name').fill('成本委員')
  await page.getByTestId('parallel-member-1-prompt').fill('從成本與維護角度發想')
  await page.getByTestId('parallel-member-2-name').fill('使用者委員')
  await page.getByTestId('parallel-member-2-prompt').fill('從新手使用者角度發想')
  await page.getByTestId('parallel-member-3-name').fill('營運委員')
  await page.getByTestId('parallel-member-3-prompt').fill('從營運落地角度發想')
  await page.getByTestId('new-case-member-1-model-select').selectOption('mock-slow')
  await page.getByTestId('new-case-member-2-model-select').selectOption('mock-fast')
  await page.getByTestId('new-case-member-3-model-select').selectOption('mock-fast')
  await page.getByTestId('new-case-moderator-model-select').selectOption('mock-slow')
  const createResponsePromise = page.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().endsWith('/meetings'),
  )
  await page.getByTestId('create-meeting-button').click()
  await expect(page.getByTestId('new-case-modal')).not.toBeVisible()
  const created = await (await createResponsePromise).json()
  expect(
    created.participants.map((participant: { role_id: string; model_config_id: string }) => [
      participant.role_id,
      participant.model_config_id,
    ]),
  ).toEqual([
    ['Member-1', 'mock-slow'],
    ['Member-2', 'mock-fast'],
    ['Member-3', 'mock-fast'],
    ['Moderator', 'mock-slow'],
  ])

  await expect(page.getByTestId('role-seat-member-1')).toBeVisible()
  await expect(page.getByTestId('role-seat-member-2')).toBeVisible()
  await expect(page.getByTestId('role-seat-member-3')).toBeVisible()
  await expect(page.getByTestId('role-seat-moderator')).toBeVisible()

  await setRoleModelsInSettings(page, {
    'Member-1': 'mock-slow',
    'Member-2': 'mock-slow',
    'Member-3': 'mock-slow',
    Moderator: 'mock-slow',
  })
  await closeSettings(page)

  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('role-seat-member-1')).toHaveAttribute('data-status', 'thinking')
  await expect(page.getByTestId('operation-status')).toContainText('狀態：completed', { timeout: 15000 })
  await expect(page.getByTestId('operation-status')).toContainText('最後步驟：synthesis-1')
  await expect(page.getByTestId('role-seat-member-1')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-member-2')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-member-3')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-moderator')).toHaveAttribute('data-status', 'completed')

  await page.getByTestId('records-button').click()
  for (const stepId of ['fanout-1-member-1', 'fanout-1-member-2', 'fanout-1-member-3', 'synthesis-1']) {
    await expect(page.getByTestId('step-timeline')).toContainText(stepId)
  }
  await page.getByTestId('records-close-button').click()

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('six-hats New Case persists its fixed catalog roster and reloads every assignment', async ({
  page,
}) => {
  await page.goto('/')
  const topic = `E2E fixed six hats roster ${Date.now()}`
  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-six-hats')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await page.getByLabel('會議主題').fill(topic)
  await expect(page.getByTestId('parallel-member-editor')).toHaveCount(0)

  const assignments: Record<string, string> = {
    HatWhite: 'mock-slow',
    HatRed: 'mock-fast',
    HatBlack: 'mock-slow',
    HatYellow: 'mock-fast',
    HatGreen: 'mock-slow',
    HatBlue: 'mock-fast',
  }
  for (const [role, modelId] of Object.entries(assignments)) {
    await page.getByTestId(`new-case-${role.toLowerCase()}-model-select`).selectOption(modelId)
  }
  const createdResponsePromise = page.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().endsWith('/meetings'),
  )
  await page.getByTestId('create-meeting-button').click()
  const createdResponse = await createdResponsePromise
  expect(createdResponse.ok()).toBeTruthy()
  await expect(page.getByTestId('new-case-modal')).not.toBeVisible()
  const created = await createdResponse.json()
  expect(
    created.participants.map((participant: { role_id: string; model_config_id: string }) => [
      participant.role_id,
      participant.model_config_id,
    ]),
  ).toEqual(Object.entries(assignments))

  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()
  for (const [role, modelId] of Object.entries(assignments)) {
    await expect(page.getByTestId(`role-seat-${role.toLowerCase()}`)).toBeVisible()
    await expect(page.getByTestId(`seat-model-label-${role.toLowerCase()}`)).toContainText(modelId)
  }
  await expect(page.locator('[data-testid^="role-seat-hat-"]')).toHaveCount(0)
})

test('debate mode gates creation on both position inputs, then builds a Pro/Con/Arbiter meeting', async ({
  page,
}) => {
  await page.goto('/')

  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-debate')
    .getByRole('button', { name: '選擇此模式' })
    .click()

  const topic = `E2E debate inputs ${Date.now()}`
  await page.getByLabel('會議主題').fill(topic)

  // Both position_a/position_b are required `kind: 'text'` inputs (NewCaseModal.vue's
  // hasEmptyRequiredInput) - the create CTA must stay disabled until both are filled,
  // even once the topic itself is valid.
  await expect(page.getByTestId('create-meeting-button')).toBeDisabled()

  await page.getByTestId('mode-input-position_a').fill('先做後端')
  await expect(page.getByTestId('create-meeting-button')).toBeDisabled()

  await page.getByTestId('mode-input-position_b').fill('先做前端')
  await expect(page.getByTestId('create-meeting-button')).toBeEnabled()

  await page.getByTestId('create-meeting-button').click()
  await expect(page.getByTestId('new-case-modal')).not.toBeVisible()

  // Created with a debate-shaped roster (Pro/Con/Arbiter), confirming the create actually
  // went through rather than silently no-oping. (Whether position_a/position_b themselves
  // reach the prompts is covered at the backend unit level - test_debate_inputs_reach_prompts,
  // Task 6 - not re-verified here.)
  await expect(page.getByTestId('role-seat-pro')).toBeVisible()
  await expect(page.getByTestId('role-seat-con')).toBeVisible()
  await expect(page.getByTestId('role-seat-arbiter')).toBeVisible()

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('opening a courtroom meeting switches the stage to the courtroom scene, and a red-blue meeting switches it back', async ({
  page,
}) => {
  await page.goto('/')

  const courtroomTopic = `E2E scene auto-switch courtroom ${Date.now()}`
  await createMeetingViaNewCase(page, courtroomTopic, { modeId: 'courtroom' })
  // courtroom's default_scene (config/modes.yaml) applies automatically on open/create -
  // spec.md 16.7 / scenes.ts's applyModeScene - without the user ever touching Settings.
  await expect(page.getByTestId('council-stage').locator('.stage-scene')).toHaveAttribute(
    'data-scene',
    'courtroom',
  )

  const redBlueTopic = `E2E scene auto-switch red-blue ${Date.now()}`
  await createMeetingViaNewCase(page, redBlueTopic)
  await expect(page.getByTestId('council-stage').locator('.stage-scene')).toHaveAttribute(
    'data-scene',
    'meeting-room',
  )

  // Reopening the courtroom meeting re-applies its default scene - this is a live
  // mode-driven switch on every meeting selection, not a one-time effect from creation.
  await page.getByTestId('past-topics-button').click()
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: courtroomTopic })
    .locator('.meeting-item')
    .click()
  await expect(page.getByTestId('council-stage').locator('.stage-scene')).toHaveAttribute(
    'data-scene',
    'courtroom',
  )
  // MeetingsModal.selectMeeting() sets selectedMeeting (which the scene assertion above
  // reacts to) *before* it emits close - openMeeting() itself resolves first, then the
  // modal closes as a separate step. Without waiting for the modal to actually be gone,
  // the very next past-topics-button click below can race its still-open (or
  // still-closing) overlay and land on the wrong target.
  await expect(page.getByTestId('meetings-modal')).not.toBeVisible()

  await page.getByTestId('past-topics-button').click()
  for (const topic of [courtroomTopic, redBlueTopic]) {
    page.once('dialog', (dialog) => dialog.accept())
    await page
      .getByTestId('meeting-list-item')
      .filter({ hasText: topic })
      .getByTestId('delete-meeting-button')
      .click()
  }
  await page.getByTestId('meetings-close-button').click()
})

test('model manager tab supports create, test, edit, and delete for a model config', async ({
  page,
}) => {
  await page.goto('/')

  const modelId = 'e2e-added-mock'
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()

  await page.getByTestId('add-model-button').click()
  await page.getByTestId('model-form-id-input').fill(modelId)
  // Provider defaults to Mock - leave it, so
  // the Test step below resolves deterministically to "available" with no real network
  // call (check_model_health's mock branch just calls adapter.complete() locally).
  await page.getByTestId('model-form-save').click()
  await expect(page.getByTestId('model-form')).not.toBeVisible()
  await expect(modelManagerRow(page, modelId)).toBeVisible()

  // The role dropdowns in 一般 tab read the same `models` ref refreshModels() just updated -
  // no reload needed for the new model to show up there.
  await page.getByTestId('general-tab').click()
  await expect(page.getByTestId('blue-model-select').locator(`option[value="${modelId}"]`)).toHaveCount(1)

  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId(`test-model-button-${modelId}`).click()
  await expect(modelManagerRow(page, modelId).locator('.status-dot')).toHaveAttribute(
    'data-status',
    'available',
  )

  // A mock model has no editable connection field besides its (readonly) id, so
  // exercising a real edit means switching the Provider as part of the edit, like an
  // operator converting a placeholder mock entry into a real
  // one would.
  await page.getByTestId(`edit-model-button-${modelId}`).click()
  await expect(page.getByTestId('model-form-id-input')).toHaveValue(modelId)
  await page.getByTestId('model-form-provider-select').selectOption('custom-openai-compatible')
  await page.getByTestId('model-form-base-url-input').fill('http://127.0.0.1:9/v1')
  await page.getByTestId('model-form-model-input').fill('dummy-model')
  await page.getByTestId('model-form-timeout-input').fill('60')
  await page.getByTestId('model-form-save').click()
  await expect(page.getByTestId('model-form')).not.toBeVisible()

  // Round-trip check: re-open the edit form and confirm the PUT actually persisted, not
  // just that the form closed without error.
  await page.getByTestId(`edit-model-button-${modelId}`).click()
  await expect(page.getByTestId('model-form-timeout-input')).toHaveValue('60')
  await expect(page.getByTestId('model-form-base-url-input')).toHaveValue('http://127.0.0.1:9/v1')
  await page.getByTestId('model-form-cancel').click()

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId(`delete-model-button-${modelId}`).click()
  await expect(modelManagerRow(page, modelId)).toHaveCount(0)

  await page.getByTestId('general-tab').click()
  await expect(page.getByTestId('blue-model-select').locator(`option[value="${modelId}"]`)).toHaveCount(0)

  await closeSettings(page)
})

test('model manager shows accessible connection-test progress, slow feedback, and success', async ({
  page,
}) => {
  let pendingRoute: Route | undefined
  let requestCount = 0
  let markRequestStarted!: () => void
  const requestStarted = new Promise<void>((resolve) => {
    markRequestStarted = resolve
  })
  await page.route('**/models/mock-slow/test', async (route) => {
    requestCount += 1
    pendingRoute = route
    markRequestStarted()
  })

  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()

  const row = modelManagerRow(page, 'mock-slow')
  const button = page.getByTestId('test-model-button-mock-slow')
  const status = row.getByTestId('model-test-feedback-mock-slow')
  await button.click()
  await requestStarted

  await expect(button).toBeDisabled()
  await expect(button).toContainText('正在測試連線…')
  await expect(button.locator('.spinner')).toBeVisible()
  await expect(status).toHaveAttribute('aria-live', 'polite')
  await expect(status).toHaveText('正在測試連線…')
  await button.evaluate((element) => (element as HTMLButtonElement).click())
  expect(requestCount).toBe(1)

  await expect(status).toHaveText('Provider 回應較慢，仍在等待…', { timeout: 3_000 })
  await pendingRoute!.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ status: 'available', tested_at: '2026-07-14T12:00:00Z' }),
  })

  await expect(button).toBeEnabled()
  await expect(status).toHaveText('連線成功')
  await expect(row.locator('.status-dot')).toHaveAttribute('data-status', 'available')
})

test('model manager reports a clear connection-test failure', async ({ page }) => {
  await page.route('**/models/mock-fast/test', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Provider 暫時無法連線' }),
    })
  })

  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('test-model-button-mock-fast').click()

  const feedback = modelManagerRow(page, 'mock-fast').getByTestId('model-test-feedback-mock-fast')
  await expect(feedback).toHaveText('測試失敗：Provider 暫時無法連線')
  await expect(feedback).toHaveAttribute('role', 'status')
})

test('model health remains projected after connection-test feedback is unmounted', async ({
  page,
}) => {
  const modelId = `e2e-health-projection-${Date.now()}`
  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('add-model-button').click()
  await page.getByTestId('model-form-id-input').fill(modelId)
  await page.getByTestId('model-form-save').click()
  const row = modelManagerRow(page, modelId)
  await expect(row.locator('.status-dot')).toHaveAttribute('data-status', 'unknown')

  await page.getByTestId(`test-model-button-${modelId}`).click()
  await expect(row.getByTestId(`model-test-feedback-${modelId}`)).toHaveText('連線成功')
  await page.getByTestId('general-tab').click()
  await page.getByTestId('model-manager-tab').click()
  await expect(modelManagerRow(page, modelId).locator('.status-dot')).toHaveAttribute(
    'data-status',
    'available',
  )

  await page.getByTestId(`edit-model-button-${modelId}`).click()
  await page.getByTestId('model-form-provider-select').selectOption('custom-openai-compatible')
  await page.getByTestId('model-form-base-url-input').fill('http://127.0.0.1:9/v1')
  await page.getByTestId('model-form-model-input').fill('unreachable-model')
  await page.getByTestId('model-form-timeout-input').fill('1')
  await page.getByTestId('model-form-save').click()
  await expect(modelManagerRow(page, modelId).locator('.status-dot')).toHaveAttribute(
    'data-status',
    'unknown',
  )
  await page.getByTestId(`test-model-button-${modelId}`).click()
  await expect(
    modelManagerRow(page, modelId).getByTestId(`model-test-feedback-${modelId}`),
  ).toContainText('測試失敗：')
  await page.getByTestId('general-tab').click()
  await page.getByTestId('model-manager-tab').click()
  const failedRow = modelManagerRow(page, modelId)
  await expect(failedRow.locator('.status-dot')).toHaveAttribute('data-status', 'unavailable')
  await expect(failedRow.locator('.model-manager-test-error')).not.toBeEmpty()

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId(`delete-model-button-${modelId}`).click()
  await expect(modelManagerRow(page, modelId)).toHaveCount(0)
})

test('a late connection-test response cannot replace a newer result after the modal closes', async ({
  page,
}) => {
  const pendingRoutes: Route[] = []
  let markFirstRequestStarted!: () => void
  const firstRequestStarted = new Promise<void>((resolve) => {
    markFirstRequestStarted = resolve
  })
  await page.route('**/models/mock-fast/test', async (route) => {
    pendingRoutes.push(route)
    if (pendingRoutes.length === 1) markFirstRequestStarted()
  })

  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('test-model-button-mock-fast').click()
  await firstRequestStarted
  await closeSettings(page)

  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('test-model-button-mock-fast').click()
  await expect.poll(() => pendingRoutes.length).toBe(2)
  await pendingRoutes[1].fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ status: 'available', tested_at: '2026-07-14T12:01:00Z' }),
  })

  const row = modelManagerRow(page, 'mock-fast')
  const feedback = row.getByTestId('model-test-feedback-mock-fast')
  await expect(feedback).toHaveText('連線成功')
  await pendingRoutes[0].fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ detail: '舊請求失敗' }),
  })
  await expect(feedback).toHaveText('連線成功')
  await expect(row).not.toContainText('舊請求失敗')
})

test('editing a model invalidates its pending connection-test feedback', async ({ page }) => {
  let pendingRoute: Route | undefined
  await page.route('**/models/mock-fast/test', async (route) => {
    pendingRoute = route
  })

  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('test-model-button-mock-fast').click()
  await expect.poll(() => Boolean(pendingRoute)).toBe(true)
  await page.getByTestId('edit-model-button-mock-fast').click()
  await expect(page.getByTestId('model-form-id-input')).toHaveValue('mock-fast')
  await pendingRoute!.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ status: 'available', tested_at: '2026-07-14T12:02:00Z' }),
  })

  await expect(
    modelManagerRow(page, 'mock-fast').getByTestId('model-test-feedback-mock-fast'),
  ).toHaveCount(0)
})

test('deleting and recreating a model cannot inherit its pending connection-test result', async ({
  page,
}) => {
  const modelId = `e2e-stale-test-${Date.now()}`
  let pendingRoute: Route | undefined
  await page.route(`**/models/${modelId}/test`, async (route) => {
    pendingRoute = route
  })

  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('add-model-button').click()
  await page.getByTestId('model-form-id-input').fill(modelId)
  await page.getByTestId('model-form-save').click()
  await page.getByTestId(`test-model-button-${modelId}`).click()
  await expect.poll(() => Boolean(pendingRoute)).toBe(true)

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId(`delete-model-button-${modelId}`).click()
  await expect(modelManagerRow(page, modelId)).toHaveCount(0)
  await page.getByTestId('add-model-button').click()
  await page.getByTestId('model-form-id-input').fill(modelId)
  await page.getByTestId('model-form-save').click()
  await expect(modelManagerRow(page, modelId)).toBeVisible()

  await pendingRoute!.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ status: 'available', tested_at: '2026-07-14T12:03:00Z' }),
  })
  await expect(
    modelManagerRow(page, modelId).getByTestId(`model-test-feedback-${modelId}`),
  ).toHaveCount(0)

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId(`delete-model-button-${modelId}`).click()
  await expect(modelManagerRow(page, modelId)).toHaveCount(0)
})

test('model manager creates an OpenAI config through provider-guided preview discovery', async ({
  page,
}) => {
  let previewPayload: Record<string, unknown> | null = null
  await page.route('**/models/available-models', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    previewPayload = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ models: ['gpt-5.4', 'gpt-5.4-mini'] }),
    })
  })
  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('add-model-button').click()

  await expect(page.getByTestId('model-form-adapter-select')).toHaveCount(0)
  await page.getByTestId('model-form-provider-select').selectOption('openai')
  await expect(page.getByTestId('model-form-base-url-input')).toHaveValue('https://api.openai.com/v1')
  await expect(page.getByTestId('model-form-api-key-env-input')).toHaveValue('OPENAI_API_KEY')
  await expect(page.getByTestId('model-form-credential-hint')).toContainText('環境變數名稱')

  await page.getByTestId('model-form-discover-button').click()
  expect(previewPayload).toEqual({
    adapter: 'openai-compatible-http',
    base_url: 'https://api.openai.com/v1',
    api_key_env: 'OPENAI_API_KEY',
  })
  await expect(page.getByTestId('model-form-discovered-model-select')).toHaveValue('gpt-5.4')
  await page.getByTestId('model-form-discovered-model-select').selectOption('gpt-5.4-mini')

  const modelId = `e2e-provider-openai-${Date.now()}`
  await page.getByTestId('model-form-id-input').fill(modelId)
  await page.getByTestId('model-form-save').click()
  await expect(modelManagerRow(page, modelId)).toContainText('OpenAI · gpt-5.4-mini')

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId(`delete-model-button-${modelId}`).click()
  await closeSettings(page)
})

test('model manager discovers and saves exact Anthropic and Gemini model IDs', async ({ page }) => {
  const previewPayloads: Record<string, unknown>[] = []
  await page.route('**/models/available-models', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const payload = route.request().postDataJSON() as Record<string, unknown>
    previewPayloads.push(payload)
    const models = payload.adapter === 'anthropic-http'
      ? ['claude-opus-4-1', 'claude-sonnet-4-5']
      : ['gemini-2.5-flash', 'gemini-2.5-pro']
    await route.fulfill({ json: { models } })
  })
  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()

  const cases = [
    {
      provider: 'anthropic',
      adapter: 'anthropic-http',
      baseUrl: 'https://api.anthropic.com/v1',
      apiKeyEnv: 'ANTHROPIC_API_KEY',
      model: 'claude-sonnet-4-5',
      label: 'Anthropic · claude-sonnet-4-5',
    },
    {
      provider: 'gemini',
      adapter: 'gemini-http',
      baseUrl: 'https://generativelanguage.googleapis.com/v1beta',
      apiKeyEnv: 'GEMINI_API_KEY',
      model: 'gemini-2.5-pro',
      label: 'Gemini · gemini-2.5-pro',
    },
  ] as const

  for (const providerCase of cases) {
    await page.getByTestId('add-model-button').click()
    await page.getByTestId('model-form-provider-select').selectOption(providerCase.provider)
    await page.getByTestId('model-form-discover-button').click()
    await expect(page.getByTestId('model-form-discovered-model-select')).toBeVisible()
    await expect(page.getByTestId('model-form-discover-button')).toHaveText('重新整理可用模型')
    await page.getByTestId('model-form-discover-button').click()
    await page.getByTestId('model-form-discovered-model-select').selectOption(providerCase.model)

    const modelId = `e2e-${providerCase.provider}-discovery-${Date.now()}`
    await page.getByTestId('model-form-id-input').fill(modelId)
    await page.getByTestId('model-form-save').click()
    await expect(modelManagerRow(page, modelId)).toContainText(providerCase.label)

    page.once('dialog', (dialog) => dialog.accept())
    await page.getByTestId(`delete-model-button-${modelId}`).click()
  }

  expect(previewPayloads).toEqual(cases.flatMap((providerCase) => {
    const payload = {
      adapter: providerCase.adapter,
      base_url: providerCase.baseUrl,
      api_key_env: providerCase.apiKeyEnv,
    }
    return [payload, payload]
  }))
  await closeSettings(page)
})

test('model manager creates a subscription config from a guided CLI preset', async ({ page }) => {
  let createPayload: Record<string, unknown> | null = null
  await page.route('**/models', async (route) => {
    if (route.request().method() === 'POST') {
      createPayload = route.request().postDataJSON() as Record<string, unknown>
    }
    await route.continue()
  })
  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('add-model-button').click()
  await page.getByTestId('model-form-provider-select').selectOption('subscription-cli')

  await expect(page.getByTestId('model-form-cli-preset-select')).toHaveValue('claude')
  await expect(page.getByTestId('model-form-cli-model-default')).toContainText(
    '使用 CLI 自動選擇模型',
  )
  await expect(page.getByTestId('model-form-command-textarea')).toHaveCount(0)

  const modelId = `e2e-cli-preset-${Date.now()}`
  await page.getByTestId('model-form-id-input').fill(modelId)
  await page.getByTestId('model-form-cli-preset-select').selectOption('agy')
  await page.getByTestId('model-form-save').click()
  await expect(modelManagerRow(page, modelId)).toContainText('Subscription CLI')
  expect(createPayload).toMatchObject({
    adapter: 'subscription-cli',
    command: ['agy', '-p', '{prompt}'],
    extra_body: { cli_provider: 'agy' },
  })

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId(`delete-model-button-${modelId}`).click()
  await closeSettings(page)
})

test('model labels show Provider and exact model across model list and role selectors', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await expect(page.getByTestId('blue-model-select').locator('option[value="claude-api"]')).toHaveText(
    'Anthropic · claude-sonnet-4-5',
  )
  await page.getByTestId('model-manager-tab').click()
  await expect(modelManagerRow(page, 'qwen27')).toContainText(
    'Custom OpenAI-compatible · bartowski/Qwen_Qwen3.6-27B-GGUF',
  )
  await expect(modelManagerRow(page, 'claude-subscription')).toContainText(
    'Subscription CLI · 由 command 決定（claude-subscription）',
  )
  await closeSettings(page)

  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-red-blue')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await expect(
    page.getByTestId('new-case-blue-model-select').locator('option[value="gemini-api"]'),
  ).toHaveText('Gemini · gemini-2.5-pro')
  await page.getByTestId('new-case-close-button').click()
})

test('Anthropic failure and Gemini empty discovery retain manual exact model entry', async ({
  page,
}) => {
  let discoveryAttempt = 0
  await page.route('**/models/available-models', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    discoveryAttempt += 1
    if (discoveryAttempt === 1) {
      return route.fulfill({
        status: 502,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Provider unavailable' }),
      })
    }
    await route.fulfill({ json: { models: [] } })
  })
  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('add-model-button').click()

  await page.getByTestId('model-form-provider-select').selectOption('anthropic')
  await page.getByTestId('model-form-discover-button').click()
  await expect(page.getByTestId('model-form-discovery-message')).toContainText('Provider unavailable')
  await expect(page.getByTestId('model-form-model-input')).toBeVisible()

  await page.getByTestId('model-form-provider-select').selectOption('gemini')
  await page.getByTestId('model-form-discover-button').click()
  await expect(page.getByTestId('model-form-discovery-message')).toContainText('沒有回傳可用模型')
  await expect(page.getByTestId('model-form-model-input')).toBeVisible()

  await page.getByTestId('model-form-provider-select').selectOption('subscription-cli')
  await expect(page.getByTestId('model-form-cli-preset-select')).toHaveValue('claude')
  await expect(page.getByTestId('model-form-cli-model-default')).toContainText('CLI 自動選擇模型')
  await page.getByTestId('model-form-cancel').click()
  await closeSettings(page)
})

test('provider change and manual model edit discard late discovery responses', async ({ page }) => {
  const pendingRoutes: Route[] = []
  await page.route('**/models/available-models', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    pendingRoutes.push(route)
  })
  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('add-model-button').click()

  await page.getByTestId('model-form-provider-select').selectOption('anthropic')
  await page.getByTestId('model-form-discover-button').click()
  await expect.poll(() => pendingRoutes.length).toBe(1)
  await page.getByTestId('model-form-provider-select').selectOption('gemini')
  await pendingRoutes[0].fulfill({ json: { models: ['claude-late-result'] } })
  await expect(page.getByTestId('model-form-discovered-model-select')).toHaveCount(0)
  await expect(page.getByTestId('model-form-model-input')).toHaveValue('')

  await page.getByTestId('model-form-discover-button').click()
  await expect.poll(() => pendingRoutes.length).toBe(2)
  await page.getByTestId('model-form-model-input').fill('gemini-manual-exact')
  await pendingRoutes[1].fulfill({ json: { models: ['gemini-late-result'] } })
  await expect(page.getByTestId('model-form-discovered-model-select')).toHaveCount(0)
  await expect(page.getByTestId('model-form-model-input')).toHaveValue('gemini-manual-exact')

  await page.getByTestId('model-form-cancel').click()
  await closeSettings(page)
})

test('editing an existing config refreshes discovery through its saved-config endpoint', async ({
  page,
}) => {
  let existingDiscoveryRequests = 0
  await page.route('**/models/qwen27/available-models', async (route) => {
    existingDiscoveryRequests += 1
    await route.fulfill({ json: { models: ['qwen/existing', 'qwen/new'] } })
  })
  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('edit-model-button-qwen27').click()

  await expect(page.getByTestId('model-form-provider-select')).toHaveValue('custom-openai-compatible')
  await page.getByTestId('model-form-discover-button').click()
  await expect.poll(() => existingDiscoveryRequests).toBe(1)
  await expect(page.getByTestId('model-form-discovered-model-select')).toHaveValue('qwen/existing')
  await page.getByTestId('model-form-cancel').click()
  await closeSettings(page)
})

test('provider-guided edits preserve legacy extra body, pricing, and CLI command fields', async ({
  page,
}) => {
  const modelsResponsePromise = page.waitForResponse(
    (response) => response.request().method() === 'GET' && response.url().endsWith('/models'),
  )
  await page.goto('/')
  const apiOrigin = new URL((await modelsResponsePromise).url()).origin
  const modelId = `e2e-legacy-roundtrip-${Date.now()}`
  const pricing = { currency: 'USD', input_per_1m_tokens: 1.25, output_per_1m_tokens: 5 }
  expect((await page.request.post(`${apiOrigin}/models`, {
    data: {
      id: modelId,
      adapter: 'openai-compatible-http',
      base_url: 'http://legacy.example.test/v1',
      model: 'legacy/exact-id',
      api_key_env: 'LEGACY_API_KEY',
      extra_body: { chat_template_kwargs: { enable_thinking: false } },
      pricing,
    },
  })).ok()).toBeTruthy()
  await page.reload()
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()

  let httpUpdate: Record<string, unknown> | null = null
  await page.route(`**/models/${modelId}`, async (route) => {
    if (route.request().method() === 'PUT') {
      httpUpdate = route.request().postDataJSON() as Record<string, unknown>
    }
    await route.continue()
  })
  await page.getByTestId(`edit-model-button-${modelId}`).click()
  await expect(page.getByTestId('model-form-provider-select')).toHaveValue('custom-openai-compatible')
  await page.getByTestId('model-form-save').click()
  await expect(page.getByTestId('model-form')).not.toBeVisible()
  expect(httpUpdate).toMatchObject({
    extra_body: { chat_template_kwargs: { enable_thinking: false } },
    pricing,
  })

  let cliUpdate: Record<string, unknown> | null = null
  await page.route('**/models/codex-subscription', async (route) => {
    if (route.request().method() === 'PUT') {
      cliUpdate = route.request().postDataJSON() as Record<string, unknown>
    }
    await route.continue()
  })
  await page.getByTestId('edit-model-button-codex-subscription').click()
  await expect(page.getByTestId('model-form-provider-select')).toHaveValue('subscription-cli')
  await expect(page.getByTestId('model-form-cli-preset-select')).toHaveValue('codex')
  await expect(page.getByTestId('model-form-command-textarea')).toHaveCount(0)
  await page.getByTestId('model-form-save').click()
  expect(cliUpdate).toMatchObject({
    command: ['codex', 'exec', '{prompt}'],
    extra_body: { cli_provider: 'codex' },
  })

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId(`delete-model-button-${modelId}`).click()
  await closeSettings(page)
})

test('unknown legacy subscription commands stay custom and round-trip unchanged', async ({ page }) => {
  const modelsResponsePromise = page.waitForResponse(
    (response) => response.request().method() === 'GET' && response.url().endsWith('/models'),
  )
  await page.goto('/')
  const apiOrigin = new URL((await modelsResponsePromise).url()).origin
  const modelId = `e2e-custom-cli-${Date.now()}`
  const command = ['company-wrapper', '--profile', 'work', '{prompt}']
  const extraBody = { cli_provider: 'company-internal', preserve: { mode: 'safe' } }
  expect((await page.request.post(`${apiOrigin}/models`, {
    data: {
      id: modelId,
      adapter: 'subscription-cli',
      command,
      extra_body: extraBody,
      timeout_seconds: 77,
    },
  })).ok()).toBeTruthy()
  await page.reload()
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()

  let updatePayload: Record<string, unknown> | null = null
  await page.route(`**/models/${modelId}`, async (route) => {
    if (route.request().method() === 'PUT') {
      updatePayload = route.request().postDataJSON() as Record<string, unknown>
    }
    await route.continue()
  })
  await page.getByTestId(`edit-model-button-${modelId}`).click()
  await expect(page.getByTestId('model-form-cli-preset-select')).toHaveValue('custom')
  await expect(page.getByTestId('model-form-command-textarea')).toHaveValue(command.join('\n'))
  await page.getByTestId('model-form-save').click()
  expect(updatePayload).toMatchObject({
    command,
    extra_body: extraBody,
    timeout_seconds: 77,
  })

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId(`delete-model-button-${modelId}`).click()
  await closeSettings(page)
})

test('model manager form shows per-field validation errors and does not create the model', async ({
  page,
}) => {
  await page.goto('/')

  const modelId = 'e2e-invalid-http'
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()

  await page.getByTestId('add-model-button').click()
  await page.getByTestId('model-form-id-input').fill(modelId)
  await page.getByTestId('model-form-provider-select').selectOption('custom-openai-compatible')
  // base_url/model left empty on purpose - validate_model_config_fields (backend) requires
  // both for the http-family adapters.
  await page.getByTestId('model-form-save').click()

  await expect(page.getByTestId('model-form-error-base_url')).toBeVisible()
  await expect(page.getByTestId('model-form-error-model')).toBeVisible()
  // The save failed (422), so the form must still be open rather than having closed as if
  // it succeeded.
  await expect(page.getByTestId('model-form')).toBeVisible()

  await page.getByTestId('model-form-cancel').click()
  await expect(page.getByTestId('model-manager-list')).not.toContainText(modelId)

  await closeSettings(page)
})

test('deleting a model that a role has selected falls back to the first remaining model', async ({
  page,
}) => {
  await page.goto('/')

  // Role dropdowns exist from page load via the default mode's roster (councilRoles),
  // with no meeting required - capture the current first option before touching anything,
  // rather than hardcoding e.g. 'mock-fast', so this doesn't depend on models.yaml's
  // example content or on other tests' ordering.
  await page.getByTestId('settings-button').click()
  const blueSelect = page.getByTestId('blue-model-select')
  const firstModelId = await blueSelect.locator('option').first().getAttribute('value')
  expect(firstModelId).toBeTruthy()

  const modelId = 'e2e-fallback-mock'
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('add-model-button').click()
  await page.getByTestId('model-form-id-input').fill(modelId)
  await page.getByTestId('model-form-save').click()
  await expect(modelManagerRow(page, modelId)).toBeVisible()

  await page.getByTestId('general-tab').click()
  await blueSelect.selectOption(modelId)
  await expect(blueSelect).toHaveValue(modelId)

  await page.getByTestId('model-manager-tab').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId(`delete-model-button-${modelId}`).click()
  await expect(modelManagerRow(page, modelId)).toHaveCount(0)

  // useCouncil.ts's sanitize watch (Task 4) clears any role pointing at a now-deleted
  // model id and falls back to models.value[0] - assert Blue actually moved, not just that
  // the deleted id disappeared from the option list.
  await page.getByTestId('general-tab').click()
  await expect(blueSelect).toHaveValue(firstModelId!)

  await closeSettings(page)
})
