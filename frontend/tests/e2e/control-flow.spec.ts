import { expect, test, type Page, type Route } from '@playwright/test'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

// The whole UI is now a stage with modals/drawers layered on top of it, so most flows
// need a small amount of "open this surface, do the thing, close it" choreography.
// These helpers keep the actual test bodies readable.

async function createMeetingViaNewCase(
  page: Page,
  title: string,
  options: {
    goal?: string
    modeId?: string
    caseType?: 'civil' | 'criminal'
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
  await page.getByLabel('會議名稱', { exact: true }).fill(title)
  await page.getByLabel('目標', { exact: true }).fill(options?.goal ?? title)
  if (modeId === 'courtroom') {
    await page.getByTestId('courtroom-case-type-select').selectOption(options.caseType ?? 'civil')
  }
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
  const createdResponse = page.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().endsWith('/meetings'),
  )
  await page.getByTestId('create-meeting-button').click()
  // NewCaseModal closes itself once createNewMeeting() resolves.
  await expect(page.getByTestId('new-case-modal')).not.toBeVisible()
  return ((await createdResponse).json() as Promise<{ meeting_id: string }>).then(
    (meeting) => meeting.meeting_id,
  )
}

test('New Case requires separate title and goal fields before creation', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-red-blue')
    .getByRole('button', { name: '選擇此模式' })
    .click()

  const createButton = page.getByTestId('create-meeting-button')
  await expect(createButton).toBeDisabled()
  await page.getByLabel('會議名稱', { exact: true }).fill('土地糾紛案')
  await expect(createButton).toBeDisabled()
  await page.getByLabel('目標', { exact: true }).fill('判斷被告是否構成無權占有？')
  await expect(createButton).toBeEnabled()
})

test('legacy meeting requires explicit title and goal migration without rewriting events', async ({
  page,
}) => {
  const dataDir = process.env.E2E_DATA_DIR
  expect(dataDir, 'E2E_DATA_DIR must point at the isolated e2e backend data directory').toBeTruthy()
  const meetingId = `meeting-legacy-ui-${Date.now()}`
  const legacyTitle = `舊土地案 ${meetingId}`
  const migratedTitle = `土地返還案 ${meetingId}`
  const meetingDir = join(dataDir!, 'meetings', meetingId)
  mkdirSync(meetingDir, { recursive: true })
  writeFileSync(
    join(meetingDir, 'metadata.json'),
    JSON.stringify({
      meeting_id: meetingId,
      topic: legacyTitle,
      created_at: '2026-07-14T00:00:00+00:00',
      tags: [],
      pinned: false,
      mode_id: 'red-blue',
      participants: ['Blue', 'Red', 'Judge'].map((role_id) => ({
        role_id,
        model_config_id: 'mock-fast',
      })),
      inputs: {},
      case_files: [],
    }),
  )
  const eventsPath = join(meetingDir, 'events.jsonl')
  const originalEvents = `${JSON.stringify({
    event_id: `${meetingId}:human-message:historical`,
    meeting_id: meetingId,
    step_id: 'human-message',
    role: 'Human',
    attempt: 1,
    status: 'completed',
    content: '既有紀錄不得改寫',
    created_at: '2026-07-14T00:01:00+00:00',
  })}\n`
  writeFileSync(eventsPath, originalEvents)

  await page.goto('/')
  await page.getByTestId('past-topics-button').click()
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: legacyTitle })
    .locator('.meeting-item')
    .click()

  await expect(page.getByTestId('meeting-goal-migration')).toBeVisible()
  await expect(page.getByLabel('舊會議名稱')).toHaveValue(legacyTitle)
  await expect(page.getByLabel('舊會議目標')).toHaveValue('')
  await expect(page.getByTestId('start-meeting-button')).toBeDisabled()
  await page.getByTestId('advanced-options-button').click()
  await expect(page.getByTestId('run-sequence-button')).toBeDisabled()

  await page.getByLabel('舊會議名稱').fill(migratedTitle)
  await page.getByLabel('舊會議目標').fill('判斷被告是否應返還土地')
  const updated = page.waitForResponse(
    (response) =>
      response.request().method() === 'PUT' &&
      response.url().endsWith(`/meetings/${meetingId}/details`),
  )
  await page.getByTestId('save-meeting-goal-button').click()
  expect((await updated).status()).toBe(200)
  await expect(page.getByTestId('meeting-goal-migration')).not.toBeVisible()

  const storedMetadata = JSON.parse(readFileSync(join(meetingDir, 'metadata.json'), 'utf8')) as Record<
    string,
    unknown
  >
  expect(storedMetadata.title).toBe(migratedTitle)
  expect(storedMetadata.goal).toBe('判斷被告是否應返還土地')
  expect(storedMetadata).not.toHaveProperty('topic')
  expect(readFileSync(eventsPath, 'utf8')).toBe(originalEvents)

  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: migratedTitle })
    .locator('.meeting-item')
    .click()
  await expect(page.getByTestId('meeting-goal-migration')).not.toBeVisible()
  await expect(page.getByTestId('start-meeting-button')).toBeEnabled()
  expect(readFileSync(eventsPath, 'utf8')).toBe(originalEvents)
})

test('chairman asks everyone from the unified composer exactly once and reload preserves the request', async ({ page }) => {
  const dataDir = process.env.E2E_DATA_DIR
  expect(dataDir).toBeTruthy()
  await page.goto('/')
  const title = `E2E unified chairman ${Date.now()}`
  const message = '主席請全體：請針對成本與風險提出下一步。'
  const meetingId = await createMeetingViaNewCase(page, title, { goal: '提出可執行的交付建議' })

  await page.getByTestId('chairman-action-select').selectOption('all')
  await expect(page.getByTestId('send-chair-message-button')).toHaveText('請全體回應')
  await expect(page.getByTestId('chairman-action-select')).toContainText('下一步：開始審議')
  await page.getByTestId('chair-message-input').fill(message)
  await page.getByTestId('send-chair-message-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成', { timeout: 15000 })

  const eventsPath = join(dataDir!, 'meetings', meetingId, 'events.jsonl')
  const events = readFileSync(eventsPath, 'utf8').trim().split('\n').map((line) => JSON.parse(line))
  expect(events.filter((event) => event.role === 'Human' && event.content === message)).toHaveLength(1)
  expect(events.filter((event) => !['Human', 'System'].includes(event.role) && event.status === 'completed')).toHaveLength(4)

  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: title }).locator('.meeting-item').click()
  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('step-timeline')).toContainText(message)
  await expect(page.getByTestId('step-timeline').locator('.timeline-content', { hasText: message })).toHaveCount(1)
  await page.getByTestId('records-close-button').click()

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId('meeting-list-item').filter({ hasText: title }).getByTestId('delete-meeting-button').click()
})

test('legacy courtroom is gated by issue setup and rejected generic paths preserve old events', async ({ page }) => {
  const dataDir = process.env.E2E_DATA_DIR
  expect(dataDir).toBeTruthy()
  const meetingId = `meeting-legacy-courtroom-${Date.now()}`
  const title = `舊法院案件 ${meetingId}`
  const meetingDir = join(dataDir!, 'meetings', meetingId)
  mkdirSync(meetingDir, { recursive: true })
  writeFileSync(join(meetingDir, 'metadata.json'), JSON.stringify({
    meeting_id: meetingId,
    title,
    goal: '判斷舊案件責任歸屬',
    created_at: '2026-07-14T00:00:00+00:00',
    tags: [],
    pinned: false,
    mode_id: 'courtroom',
    participants: ['Prosecutor', 'Defense', 'Judge'].map((role_id) => ({ role_id, model_config_id: 'mock-fast' })),
    inputs: {},
    case_files: [],
    courtroom_docket: {
      schema_version: 1,
      revision: 1,
      confirmed: true,
      next_issue_number: 2,
      issues: [{ id: 'issue-1', title: '既有爭點不得遺失' }],
    },
  }))
  const oldSteps = [
    ['courtroom-charge', 'Prosecutor'],
    ['courtroom-defense', 'Defense'],
    ['courtroom-rebuttal', 'Prosecutor'],
    ['courtroom-verdict', 'Judge'],
  ]
  const originalEvents = `${oldSteps.map(([step_id, role], index) => JSON.stringify({
    event_id: `${meetingId}:${step_id}:attempt-1:completed`,
    meeting_id: meetingId,
    step_id,
    base_step_id: step_id,
    round: 1,
    role,
    attempt: 1,
    status: 'completed',
    content: `舊法院歷史發言 ${index + 1}`,
    created_at: `2026-07-14T00:0${index + 1}:00+00:00`,
  })).join('\n')}\n`
  const eventsPath = join(meetingDir, 'events.jsonl')
  writeFileSync(eventsPath, originalEvents)

  await page.goto('/')
  await page.getByTestId('past-topics-button').click()
  const meetingResponse = page.waitForResponse((response) => response.url().endsWith(`/meetings/${meetingId}`))
  await page.getByTestId('meeting-list-item').filter({ hasText: title }).locator('.meeting-item').click()
  const apiOrigin = new URL((await meetingResponse).url()).origin
  await expect(page.getByTestId('legacy-courtroom-case-type-gate')).toContainText('請先選擇案件類型')
  await page.getByTestId('legacy-courtroom-case-type-select').selectOption('civil')
  await page.getByTestId('save-courtroom-case-type-button').click()
  await expect(page.getByTestId('legacy-courtroom-case-type-gate')).toHaveCount(0)
  await expect(page.getByTestId('courtroom-docket-panel')).toContainText('既有爭點不得遺失')
  await expect(page.getByTestId('start-meeting-button')).toHaveCount(0)
  await page.getByTestId('advanced-options-button').click()
  await expect(page.getByTestId('role-sequence-controls')).toHaveCount(0)

  expect((await page.request.post(`${apiOrigin}/meetings/${meetingId}/start`, { data: {} })).status()).toBe(409)
  expect((await page.request.post(`${apiOrigin}/meetings/${meetingId}/sequences`, { data: { roles: ['Prosecutor', 'Defense', 'Judge'] } })).status()).toBe(409)
  expect(readFileSync(eventsPath, 'utf8')).toBe(originalEvents)
  await page.getByTestId('advanced-options-button').click()
  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('step-timeline').locator('.timeline-row')).toHaveCount(4)
  await expect(page.getByTestId('step-timeline')).toContainText('法官判決')
  await page.getByTestId('records-close-button').click()

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId('meeting-list-item').filter({ hasText: title }).getByTestId('delete-meeting-button').click()
})

test('editing an established goal confirms and audits old/new values while title-only edits stay quiet', async ({ page }) => {
  const dataDir = process.env.E2E_DATA_DIR
  expect(dataDir).toBeTruthy()
  await page.goto('/')
  const title = `E2E goal audit ${Date.now()}`
  const originalGoal = '提出原始交付建議'
  const revisedGoal = '提出包含風險緩解的交付建議'
  const meetingId = await createMeetingViaNewCase(page, title, { goal: originalGoal })
  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成', { timeout: 15000 })

  await page.getByTestId('meeting-settings-button').click()
  await page.getByTestId('meeting-goal-input').fill(revisedGoal)
  page.once('dialog', async (dialog) => {
    expect(dialog.type()).toBe('confirm')
    expect(dialog.message()).toContain('既有發言不會重新產生')
    await dialog.accept()
  })
  await page.getByTestId('save-meeting-settings-button').click()
  await expect(page.getByTestId('meeting-settings-drawer')).not.toBeVisible()
  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('step-timeline')).toContainText('主席修改會議目標')
  await expect(page.getByTestId('step-timeline')).toContainText(`舊目標：${originalGoal}`)
  await expect(page.getByTestId('step-timeline')).toContainText(`新目標：${revisedGoal}`)
  await page.getByTestId('records-tab-transcript').click()
  await expect(page.getByTestId('transcript-preview')).toContainText('主席修改會議目標')
  await expect(page.getByTestId('transcript-preview')).toContainText(`舊目標：${originalGoal}`)
  await expect(page.getByTestId('transcript-preview')).toContainText(`新目標：${revisedGoal}`)
  await page.getByTestId('records-close-button').click()

  const eventsPath = join(dataDir!, 'meetings', meetingId, 'events.jsonl')
  const beforeTitleOnly = readFileSync(eventsPath, 'utf8').trim().split('\n').length
  await page.getByTestId('meeting-settings-button').click()
  await expect(page.getByTestId('meeting-title-input')).toBeEnabled()
  await page.getByTestId('meeting-title-input').fill(`${title}（改名）`)
  await page.getByTestId('save-meeting-settings-button').click()
  expect(readFileSync(eventsPath, 'utf8').trim().split('\n')).toHaveLength(beforeTitleOnly)

  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: `${title}（改名）` }).locator('.meeting-item').click()
  await page.getByTestId('meeting-settings-button').click()
  await expect(page.getByTestId('meeting-goal-input')).toHaveValue(revisedGoal)
  await page.getByTestId('meeting-settings-close-button').click()

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId('meeting-list-item').filter({ hasText: `${title}（改名）` }).getByTestId('delete-meeting-button').click()
})

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
  await page.route('**/meetings/*/settings', async (route) => {
    replacementPayloads.push((route.request().postDataJSON() as { participant_models: Record<string, string> }).participant_models)
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
  await page.getByTestId('meeting-settings-button').click()
  await expect(page.getByTestId('blue-model-select')).toHaveValue('mock-fast')
  await page.route(/\/meetings\/[^/]+\/settings$/, (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Assignment save failed' }),
    }),
  )

  await page.getByTestId('blue-model-select').selectOption('mock-slow')
  await page.getByTestId('save-meeting-settings-button').click()
  await expect(page.getByRole('alert')).toContainText('Assignment save failed')
  await expect(page.getByTestId('blue-model-select')).toHaveValue('mock-slow')
  page.once('dialog', (dialog) => dialog.accept())
  await closeSettings(page)
  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-fast')
})

test('a delayed assignment save blocks leaving and remains scoped to its meeting', async ({
  page,
}) => {
  await page.goto('/')
  const topicA = `E2E delayed assignment A ${Date.now()}`
  const topicB = `E2E delayed assignment B ${Date.now()}`
  const meetingAId = await createMeetingViaNewCase(page, topicA)
  const meetingBId = await createMeetingViaNewCase(page, topicB, {
    modelAssignments: { Blue: 'mock-broken' },
  })

  const openTopic = async (topic: string) => {
    await page.getByTestId('past-topics-button').click()
    await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()
  }
  const assignmentUrl = new RegExp(`/meetings/${meetingAId}/settings$`)

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
  await page.getByTestId('meeting-settings-button').click()
  const successResponse = page.waitForResponse(assignmentUrl)
  await page.getByTestId('blue-model-select').selectOption('mock-slow')
  await page.getByTestId('save-meeting-settings-button').click()
  await expect.poll(() => successIntercepted).toBe(true)
  let savingAlertMessage = ''
  page.once('dialog', async (dialog) => {
    savingAlertMessage = dialog.message()
    await dialog.accept()
  })
  await page.getByTestId('meeting-settings-close-button').click()
  expect(savingAlertMessage).toContain('正在儲存')
  await expect(page.getByTestId('meeting-settings-drawer')).toBeVisible()

  releaseSuccess()
  await successResponse
  await expect(page.getByTestId('seat-model-label-blue')).toContainText('mock-slow')
  await openTopic(topicB)

  await expect(page.getByTestId('meeting-title-display')).toHaveText(topicB)
  await expect(page.getByTestId('seat-model-label-blue')).toContainText('mock-broken')

  await openTopic(topicA)
  await expect(page.getByTestId('seat-model-label-blue')).toContainText('mock-slow')
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
  const meetingId = await createMeetingViaNewCase(page, topic, {
    modelAssignments: { Blue: deletedModelId },
  })
  expect((await page.request.delete(`${apiOrigin}/models/${deletedModelId}`)).ok()).toBeTruthy()

  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()
  await page.getByTestId('meeting-settings-button').click()
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
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')
  await openRoleDrawer(page, 'blue')
  await page.getByTestId('role-instruction-input').fill('請說明目前最小可行方案')
  await page.getByTestId('request-blue-response-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')
  await closeRoleDrawer(page)
  await openAdvancedOptions(page)
  await page.getByTestId('run-sequence-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')

  expect(runBodies.map(({ url, body }) => ({ path: new URL(url as string).pathname, body }))).toEqual([
    { path: expect.stringMatching(/\/start$/), body: {} },
    {
      path: expect.stringMatching(/\/roles\/Blue\/respond$/),
      body: { instruction: '請說明目前最小可行方案' },
    },
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
  const meetingId = await createMeetingViaNewCase(page, topic)
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
// just red-blue's Blue/Red/Judge). Leaves the meeting-settings drawer open.
async function setRoleModelsInSettings(page: Page, assignments: Record<string, string>) {
  await page.getByTestId('meeting-settings-button').click()
  for (const [role, model] of Object.entries(assignments)) {
    const select = page.getByTestId(`${role.toLowerCase()}-model-select`)
    if ((await select.inputValue()) === model) continue
    await select.selectOption(model)
  }
  const saveButton = page.getByTestId('save-meeting-settings-button')
  if (await saveButton.isDisabled()) return
  const response = page.waitForResponse(
    (candidate) => candidate.request().method() === 'PUT' && candidate.url().endsWith('/settings'),
  )
  await saveButton.click()
  await response
}

async function setModelsInSettings(
  page: Page,
  models: { blue: string; red: string; judge: string },
) {
  await setRoleModelsInSettings(page, { Blue: models.blue, Red: models.red, Judge: models.judge })
}

async function closeSettings(page: Page) {
  if (await page.getByTestId('meeting-settings-drawer').isVisible().catch(() => false)) {
    await page.getByTestId('meeting-settings-close-button').click()
    await expect(page.getByTestId('meeting-settings-drawer')).not.toBeVisible()
  } else {
    await page.getByTestId('settings-close-button').click()
    await expect(page.getByTestId('settings-modal')).not.toBeVisible()
  }
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

test('shows the meeting title and copies title plus ID to the clipboard', async ({
  page,
  context,
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/')

  const topic = `E2E meeting id ${Date.now()}`
  const meetingId = await createMeetingViaNewCase(page, topic)
  expect(meetingId).toMatch(/^meeting-/)
  await expect(page.getByTestId('meeting-title-display')).toHaveText(topic)
  await expect(page.getByText(meetingId, { exact: true })).toHaveCount(0)

  // The meeting list is title-first and does not permanently expose the internal ID.
  await page.getByTestId('past-topics-button').click()
  await expect(page.getByTestId('meeting-list-item').filter({ hasText: topic })).not.toContainText(meetingId)
  await page.getByTestId('meetings-close-button').click()

  const copyButton = page.getByTestId('copy-meeting-id-button')
  await expect(copyButton).toContainText('複製')
  await copyButton.click()
  await expect(copyButton).toContainText('已複製')

  const clipboardText = await page.evaluate(() => navigator.clipboard.readText())
  expect(clipboardText).toBe(`${topic}\n會議 ID：${meetingId}`)

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
  const meetingId = await createMeetingViaNewCase(page, topic, {
    caseFiles: [
      {
        title: '上線檢查表',
        content: '驗收測試已完成，回滾演練待確認。',
        visibleRoles: ['Judge'],
      },
    ],
  })

  await expect(page.getByTestId('operation-status')).toContainText('狀態：尚未開始')
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'waiting')
  await expect(page.getByTestId('role-seat-blue')).toHaveClass(/role-blue/)

  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  await page.getByTestId('start-meeting-button').click()

  // The role queue is pushed synchronously before the network call, so the Blue seat
  // flips to "thinking" the instant the button is clicked - not racy.
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'thinking')
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'waiting')

  await expect(page.getByTestId('operation-status')).toContainText('狀態：執行中')
  await expect(page.getByTestId('start-meeting-button')).toContainText('執行中…')

  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')
  await expect(page.getByTestId('operation-status')).toContainText('最後步驟：裁判裁決')
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-judge')).toHaveAttribute('data-status', 'completed')

  await openRoleDrawer(page, 'judge')
  await expect(page.getByTestId('role-output-panel')).toContainText('角色回應')
  await expect(page.getByTestId('role-output-panel')).toContainText('裁判裁決')
  await expect(page.getByTestId('role-output-panel')).toContainText('建議處置')
  await expect(page.getByTestId('rich-verdict-decision')).toContainText(
    '有條件核准',
  )
  await expect(page.getByTestId('rich-verdict-findings')).toContainText('Mock finding')
  await expect(page.getByTestId('rich-verdict-findings')).toContainText('[證物一]')
  await expect(page.getByTestId('rich-verdict-conditions')).toContainText('Verify the result.')
  await expect(page.getByTestId('rich-verdict-unresolved')).toContainText(
    'Is more evidence available?',
  )
  const outputRoleBadge = page.getByTestId('role-output-panel').getByTestId('role-badge')
  await expect(outputRoleBadge.locator('img')).toHaveAttribute('alt', '裁判')
  await expect(outputRoleBadge).toHaveClass(/role-judge/)
  await closeRoleDrawer(page)

  await expect(page.getByTestId('start-meeting-button')).toContainText('開始新回合')

  await page.getByTestId('chair-message-input').fill('主席補充：請先限制在一週可以完成的方案。')
  await page.getByTestId('send-chair-message-button').click()

  await expect(page.getByTestId('operation-status')).toContainText('狀態：等待中')
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
  await expect(page.getByTestId('request-blue-response-button')).toBeDisabled()
  await page
    .getByTestId('role-instruction-input')
    .fill('請針對一週內可完成的最小可行方案補充說明')
  await page.getByTestId('request-blue-response-button').click()
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'thinking')
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')
  await expect(page.getByTestId('role-output-panel')).toContainText('藍軍回應主席追問')
  await expect(page.getByTestId('role-output-panel')).toContainText('論點')
  await expect(page.getByTestId('role-output-panel')).toContainText('Mock argument')
  await expect(page.getByTestId('rich-verdict-decision')).toHaveCount(0)
  await closeRoleDrawer(page)

  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()

  await openAdvancedOptions(page)
  await expect(page.getByTestId('role-sequence-controls')).toBeVisible()
  // Preset ids are now generic (mode-system slice B task 9): 'members-reversed-adj' is
  // red-blue's [Red, Blue, Judge] preset, same roles/label as the old 'red-blue-judge' id.
  await page.getByTestId('sequence-preset-select').selectOption('members-reversed-adj')
  await page.getByTestId('run-sequence-button').click()

  // Sequence roles are also pushed synchronously before the network call.
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'thinking')
  await closeAdvancedOptions(page)
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')

  await openRoleDrawer(page, 'judge')
  await expect(page.getByTestId('role-output-panel')).toContainText('裁判依序回應')
  await closeRoleDrawer(page)

  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')

  await openRoleDrawer(page, 'blue')
  await expect(page.getByTestId('role-history-toggle')).toBeVisible()
  await page.getByTestId('role-history-toggle').click()
  await expect(page.getByTestId('role-history-list')).toContainText('藍軍修訂')
  await closeRoleDrawer(page)

  // Full audit trail lives in the records drawer.
  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('step-timeline')).toContainText('藍軍提案')
  await expect(page.getByTestId('step-timeline')).toContainText('紅軍質詢')
  await expect(page.getByTestId('step-timeline')).toContainText('裁判裁決')
  await expect(page.getByTestId('step-timeline')).toContainText('主席追問藍軍')
  await expect(page.getByTestId('step-timeline')).toContainText(
    '請針對一週內可完成的最小可行方案補充說明',
  )
  await expect(page.getByTestId('step-timeline')).toContainText('藍軍回應主席追問')
  await expect(page.getByTestId('step-timeline')).toContainText('紅軍依序回應')
  const timelinePresentation = (
    await page.getByTestId('step-timeline').locator('.timeline-main').allTextContents()
  ).join('\n')
  expect(timelinePresentation).not.toContain('round-2-blue-propose')
  expect(timelinePresentation).not.toContain('round-2-judge-decide')
  await expect(
    page.getByTestId('step-timeline').locator('.role-badge', { hasText: '紅軍' }).first(),
  ).toHaveClass(/role-red/)

  await page.getByTestId('records-tab-transcript').click()
  await expect(page.getByTestId('transcript-preview')).toContainText('## 藍軍 - 藍軍提案')
  await expect(page.getByTestId('transcript-preview')).toContainText('## 裁判 - 裁判裁決')
  await expect(page.getByTestId('transcript-preview')).toContainText(
    '主席補充：請先限制在一週可以完成的方案。',
  )
  await expect(page.getByTestId('transcript-preview')).toContainText('主席修正：限制放寬到兩週。')
  await expect(page.getByTestId('transcript-preview')).not.toContainText('round-2-blue-propose')

  // Debug tab only exists once developer mode is on (toggled earlier is not the case here,
  // so it should be absent by default).
  await expect(page.getByTestId('records-tab-debug')).toHaveCount(0)
  await page.getByTestId('records-close-button').click()

  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)
  await page.getByTestId('settings-button').click()
  await page.getByTestId('advanced-settings-tab').click()
  await page.getByTestId('dev-mode-toggle').check()
  await closeSettings(page)

  await page.getByTestId('records-button').click()

  // Selecting a timeline row feeds its raw event into the Debug tab - use that to verify
  // directed vs. sequence responses are actually typed differently, not just visually similar.
  await page.getByTestId('records-tab-timeline').click()
  await page
    .getByTestId('step-timeline')
    .locator('.timeline-main', { hasText: '藍軍回應主席追問' })
    .click()
  await page.getByTestId('records-tab-debug').click()
  await expect(page.getByTestId('debug-panel')).toContainText('"interaction_type": "directed-role-response"')
  await expect(page.getByTestId('debug-panel')).toContainText('"in_response_to_event_id"')
  await expect(page.getByTestId('debug-panel')).toContainText('"status": "completed"')

  await page.getByTestId('records-tab-timeline').click()
  await page
    .getByTestId('step-timeline')
    .locator('.timeline-main', { hasText: '紅軍依序回應' })
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
  await expect(page.getByTestId('meeting-list')).toContainText('已結案')
  await page.getByTestId('meetings-close-button').click()

  await expect(page.getByTestId('operation-status')).toContainText('狀態：已結案')
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

  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-judge')).toHaveAttribute('data-status', 'completed')

  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('step-timeline')).toContainText('裁判裁決')
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

test('a completed fixed round stays on the explicit new-round action after a Human note', async ({
  page,
}) => {
  await page.goto('/')

  const topic = `E2E smart continue ${Date.now()}`
  await createMeetingViaNewCase(page, topic)

  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')

  await expect(page.getByTestId('start-meeting-button')).toContainText('開始新回合')
  await page.getByTestId('chair-message-input').fill('主席補充：請議會針對成本做更仔細的討論。')
  const noteSaved = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/messages'))
  await page.getByTestId('send-chair-message-button').click()
  await noteSaved
  await expect(page.getByTestId('operation-status')).toContainText('狀態：等待中')
  await expect(page.getByTestId('start-meeting-button')).toContainText('開始新回合')

  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'thinking')
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成', { timeout: 15000 })

  await page.getByTestId('records-button').click()
  await expect(
    page.getByTestId('step-timeline').locator('.timeline-row strong', { hasText: '藍軍提案' }),
  ).toHaveCount(2)
  await page.getByTestId('records-close-button').click()

  await openAdvancedOptions(page)
  await expect(page.getByTestId('role-sequence-controls')).toBeVisible()
  await expect(page.getByTestId('run-sequence-button')).toBeVisible()
  await closeAdvancedOptions(page)

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
  const topic = `E2E persisted meeting scene ${Date.now()}`
  await createMeetingViaNewCase(page, topic)

  const stageScene = page.getByTestId('council-stage').locator('.stage-scene')
  await expect(stageScene).toHaveAttribute('data-scene', 'meeting-room')

  await page.getByTestId('meeting-settings-button').click()
  await page.getByTestId('scene-select').selectOption('courtroom')
  await page.getByTestId('save-meeting-settings-button').click()
  await expect(stageScene).toHaveAttribute('data-scene', 'courtroom')

  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()
  await expect(stageScene).toHaveAttribute('data-scene', 'courtroom')
})

test('switching to the courtroom scene renders its own seat positions', async ({ page }) => {
  await page.goto('/')
  await createMeetingViaNewCase(page, `E2E courtroom scene ${Date.now()}`)

  await page.getByTestId('meeting-settings-button').click()
  await page.getByTestId('scene-select').selectOption('courtroom')
  await page.getByTestId('save-meeting-settings-button').click()

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

test('meeting scene selection is isolated when switching meetings', async ({
  page,
}) => {
  await page.goto('/')
  const topicA = `E2E isolated scene A ${Date.now()}`
  const topicB = `E2E isolated scene B ${Date.now()}`
  await createMeetingViaNewCase(page, topicA)
  await page.getByTestId('meeting-settings-button').click()
  await page.getByTestId('scene-select').selectOption('courtroom')
  await page.getByTestId('save-meeting-settings-button').click()
  await createMeetingViaNewCase(page, topicB)
  await expect(page.getByTestId('council-stage').locator('.stage-scene')).toHaveAttribute('data-scene', 'meeting-room')
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topicA }).locator('.meeting-item').click()
  await expect(page.getByTestId('council-stage').locator('.stage-scene')).toHaveAttribute('data-scene', 'courtroom')
})

test('the main "開始新回合" action always starts a fresh fixed round', async ({ page }) => {
  await page.goto('/')

  const topic = `E2E explicit new round ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  await setModelsInSettings(page, { blue: 'mock-slow', red: 'mock-slow', judge: 'mock-slow' })
  await closeSettings(page)

  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')

  await expect(page.getByTestId('start-meeting-button')).toContainText('開始新回合')
  await page.getByTestId('start-meeting-button').click()

  // startSelectedMeeting pushes the fixed-round queue synchronously before the network
  // call, same as the main CTA - Blue flips to "thinking" immediately.
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'thinking')
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成', {
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
  await expect(
    page.getByTestId('step-timeline').locator('.timeline-row strong', { hasText: '藍軍提案' }),
  ).toHaveCount(2)
  await expect(
    page.getByTestId('step-timeline').locator('.timeline-row strong', { hasText: '裁判裁決' }),
  ).toHaveCount(2)
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
  await expect(page.getByTestId('operation-status')).toContainText('狀態：執行中')

  // The backend keeps running the synchronous /start call regardless of the client, so
  // reloading here throws away every bit of in-memory state (pendingRoles, the
  // seenEventIds bookkeeping in useCouncil.ts) - the reopened meeting has to reconstruct
  // status purely from the reconnect's snapshot, with nothing left in the pending queue
  // to (correctly or incorrectly) reconcile against.
  await page.reload()
  await expect(page.getByTestId('council-stage')).toContainText('尚未選擇會議')

  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()

  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成', { timeout: 15000 })
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-judge')).toHaveAttribute('data-status', 'completed')

  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('step-timeline')).toContainText('裁判裁決')
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
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')

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

  await expect(page.getByTestId('start-meeting-button')).toContainText('開始新回合')
  await page.getByTestId('start-meeting-button').click()

  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成', { timeout: 15000 })

  // The queue must actually drain, not just fill and stall - see the identical note in
  // the "開始新回合" test above for why this needs its own assertion on the seats.
  await expect(page.getByTestId('role-seat-blue')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-red')).toHaveAttribute('data-status', 'completed')
  await expect(page.getByTestId('role-seat-judge')).toHaveAttribute('data-status', 'completed')

  await page.getByTestId('records-button').click()
  await expect(
    page.getByTestId('step-timeline').locator('.timeline-row strong', { hasText: '藍軍提案' }),
  ).toHaveCount(2)
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
    '藍軍的回應失敗了，點擊席位可重試',
  )

  // Confirmed against the real backend: calling /start (or /sequences) again once a step
  // has failed is a silent no-op - 200 response, zero new events, activity_status stuck
  // on "failed" forever. Both round-level actions must stay disabled until the step is
  // retried, rather than let the user hit that trap.
  await expect(page.getByTestId('start-meeting-button')).toBeDisabled()
  await expect(page.getByTestId('start-meeting-button')).toHaveAttribute(
    'title',
    '藍軍的回應失敗了，請點擊席位重試該步驟',
  )

  await openAdvancedOptions(page)
  await expect(page.getByTestId('run-sequence-button')).toBeDisabled()
  await expect(page.getByTestId('run-sequence-button')).toHaveAttribute(
    'title',
    '藍軍的回應失敗了，請點擊席位重試該步驟',
  )
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

  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')
  await expect(page.getByTestId('start-meeting-button')).toBeEnabled()
  await openAdvancedOptions(page)
  await expect(page.getByTestId('run-sequence-button')).toBeEnabled()
  await closeAdvancedOptions(page)

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
  await expect(page.getByTestId('advanced-options-panel')).toBeVisible()
  await expect(page.getByTestId('role-sequence-controls')).toBeVisible()

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
  await expect(page.getByTestId('operation-status')).not.toContainText('狀態：已取消')

  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('無法從介面復原')
    await dialog.accept()
  })
  await page.getByTestId('cancel-meeting-button').click()
  await closeAdvancedOptions(page)
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已取消')

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
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已結案')
  await expect(page.getByTestId('start-meeting-button')).toBeDisabled()

  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('重新開啟')
    await dialog.accept()
  })
  await page.getByTestId('reopen-meeting-button').click()

  await expect(page.getByTestId('operation-status')).toContainText('狀態：等待中')
  await expect(page.getByTestId('start-meeting-button')).toBeEnabled()
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

  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成')
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
  await page.getByLabel('會議名稱', { exact: true }).fill('保留這個輸入')
  await page.getByLabel('目標', { exact: true }).fill('保留這個輸入')
  await page.getByTestId('add-case-file-button').click()
  await page.getByTestId('case-file-1-upload').setInputFiles({
    name: '保留案卷.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('失敗後不應清空這段內容'),
  })
  await page.getByTestId('case-file-1-role-Blue').check()
  await page.getByTestId('create-meeting-button').click()

  await expect(page.getByTestId('new-case-modal')).toBeVisible()
  await expect(page.getByLabel('會議名稱', { exact: true })).toHaveValue('保留這個輸入')
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
  await page.getByLabel('會議名稱', { exact: true }).fill('編輯主題後清除舊錯誤')
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
  await page.getByLabel('會議名稱', { exact: true }).fill('容量預檢')
  await page.getByLabel('目標', { exact: true }).fill('容量預檢')
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
  await page.getByLabel('會議名稱', { exact: true }).fill('limits unavailable')
  await page.getByLabel('目標', { exact: true }).fill('limits unavailable')
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
  await page.getByLabel('會議名稱', { exact: true }).fill('emoji boundary')
  await page.getByLabel('目標', { exact: true }).fill('emoji boundary')
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
  await page.getByLabel('會議名稱', { exact: true }).fill('parallel stale error')
  await page.getByLabel('目標', { exact: true }).fill('parallel stale error')
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
  const createdMeeting = (await createResponse.json()) as {
    meeting_id: string
    case_files: Array<{ evidence_index: number; citation_anchor: string }>
  }
  const meetingId = createdMeeting.meeting_id

  expect(createPayload).toMatchObject({
    title: topic,
    goal: topic,
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
  expect(createdMeeting.case_files).toMatchObject([
    { evidence_index: 1, citation_anchor: '[證物一]' },
    { evidence_index: 2, citation_anchor: '[證物二]' },
  ])
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
  await page.getByLabel('會議名稱', { exact: true }).fill(topic)
  await page.getByLabel('目標', { exact: true }).fill(topic)
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

  // Changing the model again in meeting settings is staged and saved atomically.
  await page.getByTestId('meeting-settings-button').click()
  const saved = page.waitForResponse(
    (response) => response.request().method() === 'PUT' && response.url().endsWith('/settings'),
  )
  await page.getByTestId('blue-model-select').selectOption('mock-fast')
  await page.getByTestId('save-meeting-settings-button').click()
  await saved
  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-fast')

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: topic })
    .getByTestId('delete-meeting-button')
    .click()
})

test('courtroom handles two confirmed issues one at a time before the final verdict', async ({
  page,
}) => {
  await page.goto('/')

  const topic = `E2E courtroom issue flow ${Date.now()}`
  await createMeetingViaNewCase(page, topic, {
    modeId: 'courtroom',
    goal: '判斷被告是否應返還土地並賠償損害？',
  })

  await expect(page.getByTestId('role-seat-prosecutor')).toBeVisible()
  await expect(page.getByTestId('role-seat-defense')).toBeVisible()
  await expect(page.getByTestId('role-seat-judge')).toBeVisible()
  await expect(page.getByTestId('courtroom-docket-panel')).toContainText('草稿，尚未開始審理')
  await expect(page.getByTestId('start-meeting-button')).toHaveCount(0)
  await expect(page.getByTestId('settings-button')).toHaveText('系統設定')
  await expect(page.getByTestId('advanced-options-button')).toContainText('流程操作')
  await page.getByTestId('advanced-options-button').click()
  await expect(page.getByTestId('role-sequence-controls')).toHaveCount(0)
  await expect(page.getByText('回合流程：')).toHaveCount(0)
  await page.getByTestId('advanced-options-button').click()

  await page.getByTestId('meeting-settings-button').click()
  await page.getByTestId('meeting-title-input').fill(`${topic}（修訂）`)
  await page.getByTestId('meeting-goal-input').fill('判斷被告是否應返還土地及孳息？')
  await page.getByTestId('save-meeting-settings-button').click()
  await expect(page.getByTestId('meeting-title-display')).toHaveText(`${topic}（修訂）`)

  await page.getByTestId('add-courtroom-issue-button').click()
  await page.getByTestId('courtroom-issue-title-0').fill('被告是否具有合法占有權源？')
  await page.getByTestId('add-courtroom-issue-button').click()
  await page.getByTestId('courtroom-issue-title-1').fill('被告是否應返還土地及孳息？')
  await page.getByRole('button', { name: '上移爭點 2' }).click()
  await expect(page.getByTestId('courtroom-issue-title-0')).toHaveValue('被告是否應返還土地及孳息？')
  await page.getByTestId('save-courtroom-issues-button').click()
  await expect(page.getByTestId('courtroom-workspace-feedback')).toContainText('爭點草稿已儲存')

  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: `${topic}（修訂）` }).locator('.meeting-item').click()
  await expect(page.getByTestId('courtroom-issue-title-0')).toHaveValue('被告是否應返還土地及孳息？')
  await expect(page.getByTestId('courtroom-issue-title-1')).toHaveValue('被告是否具有合法占有權源？')
  await page.getByTestId('confirm-courtroom-issues-button').click()
  await expect(page.getByTestId('courtroom-docket-status')).toHaveText('已確認')

  await page.getByTestId('meeting-settings-button').click()
  await expect(page.getByTestId('meeting-goal-input')).toHaveAttribute('readonly', '')
  await expect(page.getByTestId('meeting-settings-drawer')).toContainText('爭點已確認')
  await page.getByTestId('meeting-settings-close-button').click()

  const primary = page.getByTestId('courtroom-primary-action')
  await expect(primary).toContainText('開始此爭點')
  await expect(primary).toContainText('下一位是原告代理人')
  await primary.click()
  await expect(page.locator('[data-issue-id="issue-1"]')).toContainText('等待主席送交法官', { timeout: 15000 })
  await expect(page.getByTestId('courtroom-awaiting-ruling-issue-1')).toHaveText(
    '攻防已完成，等待主席送交法官；不會自動判斷。',
  )
  await expect(page.locator('[data-issue-id="issue-2"]')).toContainText('待審')
  await expect(primary).toContainText('請法官判斷此爭點')
  await expect(page.getByTestId('courtroom-sticky-primary-action')).toHaveCSS('position', 'sticky')

  await page.getByTestId('chairman-action-select').selectOption('role:Defense')
  await expect(page.getByTestId('send-chair-message-button')).toHaveText('請被告代理人回答')
  await page.getByTestId('chair-message-input').fill('請說明返還孳息的主要抗辯。')
  await page.getByTestId('send-chair-message-button').click()
  await expect(page.getByTestId('operation-status')).not.toContainText('執行中', { timeout: 15000 })

  await primary.click()
  await expect(page.getByTestId('courtroom-ruling-issue-1')).toContainText('部分成立', { timeout: 15000 })
  await expect(page.getByTestId('courtroom-ruling-issue-1')).toContainText('理由：Mock issue ruling')
  await expect(primary).toContainText('進入下一爭點')
  await expect(page.locator('[data-issue-id="issue-2"]')).toContainText('待審')

  await primary.click()
  await expect(page.locator('[data-issue-id="issue-2"]')).toContainText('等待主席送交法官', { timeout: 15000 })
  await expect(page.getByTestId('courtroom-final-verdict')).toHaveCount(0)
  await primary.click()
  await expect(page.getByTestId('courtroom-ruling-issue-2')).toContainText('部分成立', { timeout: 15000 })
  await expect(primary).toContainText('最終判決')
  await primary.click()
  await expect(page.getByTestId('courtroom-final-verdict')).toContainText('Mock verdict', { timeout: 15000 })
  await expect(page.getByTestId('courtroom-final-verdict')).not.toContainText('upheld')

  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: `${topic}（修訂）` }).locator('.meeting-item').click()
  await expect(page.getByTestId('courtroom-docket-status')).toHaveText('已確認')
  await expect(page.getByTestId('courtroom-ruling-issue-1')).toContainText('部分成立')
  await expect(page.getByTestId('courtroom-ruling-issue-2')).toContainText('部分成立')
  await expect(page.getByTestId('courtroom-final-verdict')).toContainText('最終判決')

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByTestId('meeting-list-item')
    .filter({ hasText: `${topic}（修訂）` })
    .getByTestId('delete-meeting-button')
    .click()
})

test('courtroom exposes a failed final verdict retry and restores completion after reload', async ({
  page,
}) => {
  await page.goto('/')
  const topic = `E2E courtroom final retry ${Date.now()}`
  await createMeetingViaNewCase(page, topic, { modeId: 'courtroom' })

  await page.getByTestId('add-courtroom-issue-button').click()
  await page.getByTestId('courtroom-issue-title-0').fill('被告是否負返還責任？')
  await page.getByTestId('save-courtroom-issues-button').click()
  await page.getByTestId('confirm-courtroom-issues-button').click()

  const primary = page.getByTestId('courtroom-primary-action')
  await primary.click()
  await expect(page.locator('[data-issue-id="issue-1"]')).toContainText('等待主席送交法官', {
    timeout: 15000,
  })
  await primary.click()
  await expect(primary).toContainText('最終判決', { timeout: 15000 })

  await setRoleModelsInSettings(page, { Judge: 'mock-broken' })
  await closeSettings(page)
  await primary.click()
  await expect(primary).toContainText('重試最終判決', { timeout: 15000 })
  await expect(page.getByTestId('courtroom-final-verdict')).toHaveCount(0)

  await setRoleModelsInSettings(page, { Judge: 'mock-fast' })
  await closeSettings(page)
  await primary.click()
  await expect(page.getByTestId('courtroom-final-verdict')).toContainText('Mock verdict', {
    timeout: 15000,
  })

  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()
  await expect(page.getByTestId('courtroom-final-verdict')).toContainText('最終判決')
  await expect(page.getByTestId('courtroom-primary-action')).toHaveCount(0)

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).getByTestId('delete-meeting-button').click()
})

test('courtroom AI draft shows progress and keeps manual editing available after failure', async ({ page }) => {
  await page.goto('/')
  const topic = `E2E courtroom draft fallback ${Date.now()}`
  await createMeetingViaNewCase(page, topic, { modeId: 'courtroom' })
  await setRoleModelsInSettings(page, { Prosecutor: 'mock-fast', Defense: 'mock-fast', Judge: 'mock-broken' })
  await closeSettings(page)

  await page.getByTestId('generate-courtroom-draft-button').click()
  await expect(page.getByTestId('generate-courtroom-draft-button')).toContainText('正在產生爭點草稿')
  await expect(page.getByTestId('courtroom-draft-error')).toContainText('AI 草稿產生失敗', { timeout: 15000 })
  await expect(page.getByTestId('retry-courtroom-draft-button')).toBeVisible()
  await expect(page.getByTestId('add-courtroom-issue-button')).toBeEnabled()

  await page.getByTestId('add-courtroom-issue-button').click()
  await page.getByTestId('courtroom-issue-title-0').fill('主席手動建立的爭點')
  await expect(page.getByTestId('save-courtroom-issues-button')).toBeEnabled()
  await page.getByRole('button', { name: '刪除爭點 1' }).click()

  await setRoleModelsInSettings(page, { Judge: 'mock-fast' })
  await closeSettings(page)
  await page.getByTestId('retry-courtroom-draft-button').click()
  await expect(page.getByTestId('courtroom-issue-title-0')).toHaveValue('Mock generated issue', { timeout: 15000 })
  await expect(page.getByTestId('courtroom-draft-error')).toHaveCount(0)

  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).getByTestId('delete-meeting-button').click()
})

test('courtroom retry rejection rolls back pending roles and never reports false success', async ({ page }) => {
  await page.goto('/')
  const topic = `E2E courtroom retry rejection ${Date.now()}`
  await createMeetingViaNewCase(page, topic, { modeId: 'courtroom' })
  await setRoleModelsInSettings(page, { Prosecutor: 'mock-broken', Defense: 'mock-fast', Judge: 'mock-fast' })
  await closeSettings(page)

  await page.getByTestId('add-courtroom-issue-button').click()
  await page.getByTestId('courtroom-issue-title-0').fill('檢察官主張是否成立？')
  await page.getByTestId('save-courtroom-issues-button').click()
  await page.getByTestId('confirm-courtroom-issues-button').click()
  await page.getByTestId('courtroom-primary-action').click()

  const failure = page.getByTestId('courtroom-issue-failure-issue-1')
  await expect(failure).toContainText('主張方陳述執行失敗，請重試', { timeout: 15000 })
  await page.route('**/meetings/**/steps/**/retry', async (route) => {
    await route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({ detail: '重試狀態已改變，請重新操作。' }),
    })
  })

  await page.getByTestId('retry-courtroom-issue-issue-1').click()

  await expect(page.getByTestId('app-error')).toContainText('重試狀態已改變，請重新操作。')
  await expect(failure).toContainText('主張方陳述執行失敗，請重試')
  await expect(page.getByTestId('retry-courtroom-issue-issue-1')).toBeEnabled()
  await expect(page.getByTestId('courtroom-workspace-feedback')).toHaveCount(0)

  await page.unroute('**/meetings/**/steps/**/retry')
  await page.getByTestId('past-topics-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).getByTestId('delete-meeting-button').click()
})

test('brainstorm mode creates member instances and runs fanout plus synthesis', async ({ page }) => {
  await page.goto('/')

  const topic = `E2E brainstorm happy path ${Date.now()}`
  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId('mode-select-card-brainstorm')
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await page.getByLabel('會議名稱', { exact: true }).fill(topic)
  await page.getByLabel('目標', { exact: true }).fill(topic)
  await expect(page.getByTestId('parallel-member-count')).toHaveText('2')
  await expect(page.getByTestId('parallel-member-editor')).toContainText('委員 1')
  await expect(page.getByTestId('parallel-member-editor')).toContainText('委員 2')
  await expect(page.getByTestId('parallel-member-editor')).not.toContainText('Member-1')
  await expect(page.getByTestId('parallel-member-editor')).not.toContainText('Member-2')
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
  // The local mock fanout can complete before Playwright samples the transient queue;
  // either state proves the member left its initial waiting state, while the assertions
  // below still require the complete fanout and synthesis result.
  await expect(page.getByTestId('role-seat-member-1')).toHaveAttribute('data-status', /thinking|completed/)
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成', { timeout: 15000 })
  await expect(page.getByTestId('operation-status')).toContainText('最後步驟：主持人彙整')
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
  await page.getByLabel('會議名稱', { exact: true }).fill(topic)
  await page.getByLabel('目標', { exact: true }).fill(topic)
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
  await page.getByLabel('會議名稱', { exact: true }).fill(topic)
  await page.getByLabel('目標', { exact: true }).fill(topic)

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

test('ordinary restart archives the prior epoch without duplicating evidence', async ({ page }) => {
  await page.goto('/')
  const topic = `E2E ordinary restart ${Date.now()}`
  await createMeetingViaNewCase(page, topic, {
    caseFiles: [{ title: '原始證據', content: '唯一一份證據內容', visibleRoles: ['Blue', 'Red', 'Judge'] }],
  })
  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成', { timeout: 15000 })

  await openAdvancedOptions(page)
  await expect(page.getByTestId('restart-deliberation-button')).toBeDisabled()
  await page.getByTestId('restart-reason-input').fill('改用新的評估方向')
  await page.getByTestId('restart-deliberation-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：尚未開始')
  await expect(page.getByTestId('case-materials-button')).toContainText('（1）')

  await page.getByTestId('records-button').click()
  const epochSelect = page.getByTestId('records-epoch-select')
  await expect(epochSelect.locator('option')).toHaveCount(2)
  await expect(epochSelect.locator('option').last()).toContainText('第 2 輪（目前）')
  await page.getByTestId('records-tab-transcript').click()
  await expect(page.getByTestId('transcript-preview')).not.toContainText('Mock response')
  const archivedEpoch = await epochSelect.locator('option').first().getAttribute('value')
  await epochSelect.selectOption(archivedEpoch!)
  await expect(page.getByTestId('transcript-preview')).toContainText('Mock response')
  await expect(page.getByText('正在查看封存輪次。')).toBeVisible()
  await expect(page.getByRole('link', { name: '下載 Markdown' })).toHaveAttribute('href', new RegExp(`epoch=${archivedEpoch}`))
  await expect(page.getByTestId('download-all-epochs')).toHaveAttribute('href', /epoch=all/)
  await page.getByTestId('records-close-button').click()

  await page.getByTestId('case-materials-button').click()
  await expect(page.getByTestId('case-evidence-card')).toHaveCount(1)
  await expect(page.getByTestId('case-evidence-card')).toContainText('[證物一]')
  await expect(page.getByTestId('case-evidence-card')).toContainText('v1')
})

test('archived records show their historical case-material revision without replacing live materials', async ({ page }) => {
  await page.goto('/')
  const meetingId = await createMeetingViaNewCase(page, `E2E archived materials ${Date.now()}`, {
    caseFiles: [{ title: '原始證據', content: '第一版內容', visibleRoles: ['Blue', 'Judge'] }],
  })
  const apiOrigin = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:5009'
  const initialMaterials = await (await page.request.get(`${apiOrigin}/meetings/${meetingId}/materials`)).json()
  const evidenceId = initialMaterials.evidence[0].id as string
  const noted = await page.request.post(`${apiOrigin}/meetings/${meetingId}/materials/notes`, {
    data: {
      revision: initialMaterials.revision,
      title: '封存輪次備註',
      content: '只應顯示在當時快照的備註內容',
      visible_roles: ['Red', 'Judge'],
    },
  })
  expect(noted.ok()).toBeTruthy()

  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成', { timeout: 15000 })
  await openAdvancedOptions(page)
  await page.getByTestId('restart-reason-input').fill('建立可查閱的封存輪次')
  await page.getByTestId('restart-deliberation-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：尚未開始')

  const versioned = await page.request.post(`${apiOrigin}/meetings/${meetingId}/materials/evidence/${evidenceId}/versions`, {
    data: {
      revision: (await noted.json()).revision,
      title: '目前證據',
      content: '第二版目前內容',
      visible_roles: ['Blue', 'Red', 'Judge'],
    },
  })
  expect(versioned.ok()).toBeTruthy()

  let archivedMaterialAttempts = 0
  await page.route(/\/materials\?revision=1$/, async (route) => {
    archivedMaterialAttempts += 1
    if (archivedMaterialAttempts === 1) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '歷史案卷暫時無法載入' }) })
      return
    }
    await route.continue()
  })
  await page.getByTestId('records-button').click()
  const epochSelect = page.getByTestId('records-epoch-select')
  const archivedEpoch = await epochSelect.locator('option').first().getAttribute('value')
  await epochSelect.selectOption(archivedEpoch!)
  await expect(page.getByTestId('records-load-error')).toContainText('歷史案卷暫時無法載入')
  await expect(page.getByTestId('archived-materials-unavailable')).toHaveCount(0)
  await page.getByTestId('retry-records-load-button').click()
  const snapshot = page.getByTestId('archived-materials-snapshot')
  await expect(snapshot).toContainText('本輪使用的案卷（修訂 1）')
  await expect(page.getByTestId('archived-evidence-card')).toContainText('原始證據')
  await expect(page.getByTestId('archived-evidence-card')).toContainText('v1 · 使用中')
  await expect(page.getByTestId('archived-evidence-card')).toContainText('可見：藍軍、裁判')
  await expect(page.getByTestId('archived-note-card')).toContainText('封存輪次備註')
  await expect(page.getByTestId('archived-note-card')).toContainText('可見：紅軍、裁判')
  await page.getByTestId('records-close-button').click()

  await page.getByTestId('case-materials-button').click()
  await expect(page.getByTestId('case-evidence-card')).toContainText('目前證據')
  await expect(page.getByTestId('case-evidence-card')).toContainText('v2')
  await expect(page.getByTestId('case-evidence-card')).toContainText('第二版目前內容')
})

test('archived records explain when a legacy epoch has no recoverable material revision', async ({ page }) => {
  await page.goto('/')
  const meetingId = await createMeetingViaNewCase(page, `E2E legacy archived materials ${Date.now()}`)
  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成', { timeout: 15000 })
  await openAdvancedOptions(page)
  await page.getByTestId('restart-reason-input').fill('建立舊輪次示例')
  const restarted = page.waitForResponse((response) => response.url().endsWith('/deliberations/restart'))
  await page.getByTestId('restart-deliberation-button').click()
  expect((await restarted).ok()).toBe(true)
  await expect(page.getByTestId('advanced-options-panel')).toHaveCount(0)

  await page.route(new RegExp(`/meetings/${meetingId}/deliberations$`), async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    delete body.epochs[0].materials_revision
    await route.fulfill({ response, json: body })
  })
  await page.getByTestId('records-button').click()
  const epochSelect = page.getByTestId('records-epoch-select')
  const archivedEpoch = await epochSelect.locator('option').first().getAttribute('value')
  await epochSelect.selectOption(archivedEpoch!)
  await expect(page.getByTestId('archived-materials-unavailable')).toContainText('無法還原當時的證據與備註')
  await expect(page.getByTestId('archived-materials-unavailable')).toContainText('目前案卷不受影響')
})

test('versioned evidence and promoted notes trigger a visible restart gate', async ({ page }) => {
  await page.goto('/')
  const topic = `E2E material impact ${Date.now()}`
  await createMeetingViaNewCase(page, topic, {
    caseFiles: [{ title: '初始卷證', content: '初始內容', visibleRoles: ['Blue', 'Red', 'Judge'] }],
  })
  await page.getByTestId('chair-message-input').fill('跨輪都應知道的重要事實')
  await page.getByTestId('send-chair-message-button').click()
  await page.getByTestId('records-button').click()
  await page.getByTestId('promote-case-note-button').last().click()
  const promotionForm = page.getByTestId('promote-case-note-form')
  await promotionForm.getByTestId('promote-case-note-title').fill('固定案件事實')
  await promotionForm.locator('input[type="checkbox"]').last().uncheck()
  const promoted = page.waitForResponse((response) => response.url().includes('/promote-to-note'))
  await promotionForm.getByTestId('confirm-promote-case-note').click()
  await promoted
  await page.getByTestId('records-close-button').click()
  await page.getByTestId('case-materials-button').click()
  await expect(page.getByTestId('case-note-card')).toContainText('固定案件事實')
  await expect(page.getByTestId('case-note-card')).toContainText('可見：藍軍、紅軍')
  await page.getByTestId('deactivate-note-button').click()
  await expect(page.getByTestId('case-note-card')).toContainText('已停用')
  await page.getByTestId('reactivate-note-button').click()
  await expect(page.getByTestId('case-note-card')).toContainText('使用中')
  await page.getByTestId('case-materials-close-button').click()

  await page.getByTestId('start-meeting-button').click()
  await expect(page.getByTestId('operation-status')).toContainText('狀態：已完成', { timeout: 15000 })
  await page.getByTestId('case-materials-button').click()
  await page.getByTestId('case-evidence-card').getByRole('button', { name: '建立新版本' }).click()
  const form = page.getByTestId('case-material-form')
  await form.getByLabel('內容').fill('補充後的第二版內容')
  await form.getByRole('button', { name: '保存新版本' }).click()
  await expect(page.getByTestId('case-evidence-card')).toContainText('v2')
  await page.getByTestId('deactivate-evidence-button').click()
  await expect(page.getByTestId('case-evidence-card')).toContainText('已停用')
  await page.getByTestId('reactivate-evidence-button').click()
  await expect(page.getByTestId('case-evidence-card')).toContainText('使用中')
  await expect(page.getByTestId('materials-impact-warning')).toContainText('輸入原因並重開全部審議')
  await page.getByTestId('case-materials-close-button').click()

  await openAdvancedOptions(page)
  await expect(page.getByText('案卷已變更，必須完成其中一種重開才能繼續 AI。')).toBeVisible()
  await page.getByTestId('restart-reason-input').fill('納入新版證據')
  const restarted = page.waitForResponse((response) => response.url().endsWith('/deliberations/restart'))
  await page.getByTestId('restart-deliberation-button').click()
  await restarted
  await expect(page.getByTestId('advanced-options-panel')).toHaveCount(0)
  await page.getByTestId('case-materials-button').click()
  await expect(page.getByTestId('materials-impact-warning')).toHaveCount(0)
  await expect(page.getByTestId('case-evidence-card')).toContainText('[證物一]')
  await expect(page.getByTestId('case-evidence-card')).toContainText('v2')
  await expect(page.getByTestId('case-note-card')).toContainText('固定案件事實')
})

test('courtroom exposes current issue, all deliberation, and rebuild restart scopes', async ({ page }) => {
  await page.goto('/')
  const topic = `E2E courtroom restart scopes ${Date.now()}`
  await createMeetingViaNewCase(page, topic, { modeId: 'courtroom', caseType: 'civil' })
  await page.getByTestId('add-courtroom-issue-button').click()
  await page.getByTestId('courtroom-issue-title-0').fill('第一爭點')
  await page.getByTestId('save-courtroom-issues-button').click()
  await page.getByTestId('confirm-courtroom-issues-button').click()
  await page.getByTestId('courtroom-primary-action').click()
  await expect(page.getByTestId('courtroom-primary-action')).toContainText('請法官判斷此爭點', { timeout: 15000 })

  await openAdvancedOptions(page)
  await page.getByTestId('restart-scope-select').selectOption('current_issue')
  await page.getByTestId('restart-reason-input').fill('重新攻防目前爭點')
  const currentRestart = page.waitForResponse((response) => response.url().endsWith('/deliberations/restart'))
  await page.getByTestId('restart-deliberation-button').click()
  await currentRestart
  await expect(page.getByTestId('advanced-options-panel')).toHaveCount(0)
  await expect(page.locator('[data-issue-id="issue-1"]')).toContainText('待審')

  await openAdvancedOptions(page)
  await page.getByTestId('restart-scope-select').selectOption('all_deliberation')
  await page.getByTestId('restart-reason-input').fill('全部重新審議')
  const allRestart = page.waitForResponse((response) => response.url().endsWith('/deliberations/restart'))
  await page.getByTestId('restart-deliberation-button').click()
  await allRestart
  await expect(page.getByTestId('advanced-options-panel')).toHaveCount(0)
  await expect(page.getByTestId('courtroom-docket-status')).toHaveText('已確認')

  await openAdvancedOptions(page)
  await page.getByTestId('restart-scope-select').selectOption('rebuild_issues')
  await page.getByTestId('restart-reason-input').fill('重新整理爭點與目標')
  const rebuildRestart = page.waitForResponse((response) => response.url().endsWith('/deliberations/restart'))
  await page.getByTestId('restart-deliberation-button').click()
  await rebuildRestart
  await expect(page.getByTestId('courtroom-docket-status')).toContainText('草稿')
  await page.getByTestId('meeting-settings-button').click()
  await expect(page.getByTestId('meeting-goal-input')).toBeEditable()
  await expect(page.getByTestId('meeting-case-type-select')).toBeEnabled()
})

test('courtroom can restart a selected ruled issue after the final verdict without losing other rulings', async ({ page }) => {
  await page.goto('/')
  await createMeetingViaNewCase(page, `E2E restart ruled issue ${Date.now()}`, {
    modeId: 'courtroom',
    caseType: 'civil',
  })
  await page.getByTestId('add-courtroom-issue-button').click()
  await page.getByTestId('courtroom-issue-title-0').fill('第一爭點')
  await page.getByTestId('add-courtroom-issue-button').click()
  await page.getByTestId('courtroom-issue-title-1').fill('第二爭點')
  await page.getByTestId('save-courtroom-issues-button').click()
  await page.getByTestId('confirm-courtroom-issues-button').click()

  const primary = page.getByTestId('courtroom-primary-action')
  for (const nextLabel of ['請法官判斷此爭點', '進入下一爭點：第二爭點', '請法官判斷此爭點', '最終判決']) {
    await primary.click()
    await expect(primary).toContainText(nextLabel, { timeout: 15000 })
  }
  await primary.click()
  await expect(page.getByTestId('courtroom-final-verdict')).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('courtroom-ruling-issue-1')).toBeVisible()
  await expect(page.getByTestId('courtroom-ruling-issue-2')).toBeVisible()

  await openAdvancedOptions(page)
  await page.getByTestId('restart-scope-select').selectOption('current_issue')
  await expect(page.getByTestId('restart-issue-select')).toBeVisible()
  await page.getByTestId('restart-issue-select').selectOption('issue-1')
  await page.getByTestId('restart-reason-input').fill('補充第一爭點的攻防')
  const restarted = page.waitForResponse((response) => response.url().endsWith('/deliberations/restart'))
  await page.getByTestId('restart-deliberation-button').click()
  expect((await restarted).ok()).toBe(true)

  await expect(page.getByTestId('courtroom-final-verdict')).toHaveCount(0)
  await expect(page.locator('[data-issue-id="issue-1"]')).toContainText('待審')
  await expect(page.getByTestId('courtroom-ruling-issue-1')).toHaveCount(0)
  await expect(page.getByTestId('courtroom-ruling-issue-2')).toBeVisible()
})

test('criminal courtroom uses criminal roles and reaches a penalty-safe final verdict', async ({ page }) => {
  await page.goto('/')
  await createMeetingViaNewCase(page, `E2E criminal final ${Date.now()}`, {
    modeId: 'courtroom',
    caseType: 'criminal',
  })
  await expect(page.getByTestId('role-seat-prosecutor')).toContainText('檢察官')
  await expect(page.getByTestId('role-seat-defense')).toContainText('辯護人')
  await page.getByTestId('add-courtroom-issue-button').click()
  await page.getByTestId('courtroom-issue-title-0').fill('被告是否成立本項罪責？')
  await page.getByTestId('save-courtroom-issues-button').click()
  await page.getByTestId('confirm-courtroom-issues-button').click()
  const primary = page.getByTestId('courtroom-primary-action')
  await primary.click()
  await expect(primary).toContainText('請法官判斷此爭點', { timeout: 15000 })
  await primary.click()
  await expect(primary).toContainText('最終判決', { timeout: 15000 })
  await primary.click()
  const finalVerdict = page.getByTestId('courtroom-final-verdict')
  await expect(finalVerdict).toContainText('量刑考量', { timeout: 15000 })
  await expect(finalVerdict).toContainText('Mock factor')
  await expect(finalVerdict).not.toContainText(/有期徒刑|拘役|罰金\s*[0-9一二三四五六七八九十百千萬]/)
})

test('meeting drawers remain usable at 375px and dirty close requires confirmation', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/')
  const topic = `E2E narrow meeting drawer ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  await page.getByTestId('meeting-settings-button').click()
  const drawer = page.getByTestId('meeting-settings-drawer')
  await expect.poll(async () => {
    const box = await drawer.boundingBox()
    return box ? box.x + box.width : Number.POSITIVE_INFINITY
  }).toBeLessThanOrEqual(375)
  await page.getByTestId('meeting-title-input').fill(`${topic} 未儲存`)
  page.once('dialog', (dialog) => dialog.dismiss())
  await page.getByTestId('meeting-settings-close-button').click()
  await expect(drawer).toBeVisible()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId('meeting-settings-close-button').click()
  await expect(drawer).not.toBeVisible()
  await expect(page.getByTestId('meeting-title-display')).toHaveText(topic)

  await page.getByTestId('case-materials-button').click()
  await expect.poll(async () => {
    const box = await page.getByTestId('case-materials-drawer').boundingBox()
    return box ? box.x + box.width : Number.POSITIVE_INFINITY
  }).toBeLessThanOrEqual(375)
  await page.getByTestId('case-materials-close-button').click()

  await createMeetingViaNewCase(page, `E2E narrow courtroom ${Date.now()}`, { modeId: 'courtroom', caseType: 'civil' })
  await page.getByTestId('add-courtroom-issue-button').click()
  await page.getByTestId('courtroom-issue-title-0').fill('行動版粘性按鈕爭點')
  await page.getByTestId('save-courtroom-issues-button').click()
  await page.getByTestId('confirm-courtroom-issues-button').click()
  const stickyAction = page.getByTestId('courtroom-sticky-primary-action')
  await expect(stickyAction).toBeVisible()
  await expect.poll(async () => {
    const box = await stickyAction.boundingBox()
    return box ? box.y + box.height : Number.POSITIVE_INFINITY
  }).toBeLessThanOrEqual(812)
})

test('running meeting settings are read-only with an explicit explanation', async ({ page }) => {
  await page.goto('/')
  await createMeetingViaNewCase(page, `E2E running settings lock ${Date.now()}`, {
    modelAssignments: { Blue: 'mock-slow', Red: 'mock-slow', Judge: 'mock-slow' },
  })
  await page.getByTestId('start-meeting-button').click()
  await page.getByTestId('meeting-settings-button').click()
  await expect(page.getByTestId('meeting-settings-running-notice')).toContainText('完成前無法編輯或儲存')
  await expect(page.getByTestId('meeting-title-input')).toBeDisabled()
  await expect(page.getByTestId('meeting-goal-input')).toBeDisabled()
  await expect(page.getByTestId('scene-select')).toBeDisabled()
  await expect(page.getByTestId('blue-model-select')).toBeDisabled()
  await expect(page.getByTestId('save-meeting-settings-button')).toBeDisabled()
})

test('dirty meeting settings centrally block navigation and a slow save cannot be closed', async ({ page }) => {
  await page.goto('/')
  const topic = `E2E guarded settings ${Date.now()}`
  await createMeetingViaNewCase(page, topic)
  await page.getByTestId('meeting-settings-button').click()
  await page.getByTestId('meeting-title-input').fill(`${topic} draft`)

  page.once('dialog', (dialog) => dialog.dismiss())
  await page.getByTestId('meeting-settings-close-button').click()
  await expect(page.getByTestId('meeting-settings-drawer')).toBeVisible()
  await expect(page.getByTestId('meeting-title-input')).toHaveValue(`${topic} draft`)

  await page.route(/\/meetings\/[^/]+\/settings$/, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500))
    await route.continue()
  })
  const saved = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/settings'))
  await page.getByTestId('save-meeting-settings-button').click()
  page.once('dialog', (dialog) => {
    expect(dialog.type()).toBe('alert')
    expect(dialog.message()).toContain('正在儲存')
    void dialog.accept()
  })
  await page.getByTestId('meeting-settings-close-button').click()
  await expect(page.getByTestId('meeting-settings-drawer')).toBeVisible()
  expect((await saved).ok()).toBe(true)
  await expect(page.getByTestId('meeting-settings-drawer')).not.toBeVisible({ timeout: 5000 })
  await expect(page.getByTestId('meeting-title-display')).toHaveText(`${topic} draft`)
})

test('late records and case-material responses from another meeting are discarded', async ({ page }) => {
  await page.goto('/')
  const topicA = `E2E late drawer A ${Date.now()}`
  const topicB = `E2E late drawer B ${Date.now()}`
  const meetingAId = await createMeetingViaNewCase(page, topicA, {
    caseFiles: [{ title: '只屬於 A', content: 'A 案證據', visibleRoles: ['Blue', 'Red', 'Judge'] }],
  })
  await createMeetingViaNewCase(page, topicB)
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topicA }).locator('.meeting-item').click()
  await expect(page.getByTestId('meetings-modal')).not.toBeVisible()

  let releaseMaterials!: () => void
  const materialsGate = new Promise<void>((resolve) => { releaseMaterials = resolve })
  await page.route(new RegExp(`/meetings/${meetingAId}/materials$`), async (route) => {
    const response = await route.fetch()
    await materialsGate
    await route.fulfill({ response })
  })
  const requestedMaterials = page.waitForRequest((request) => request.url().endsWith(`/meetings/${meetingAId}/materials`))
  await page.getByTestId('case-materials-button').click()
  await requestedMaterials
  await page.getByTestId('case-materials-close-button').click()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topicB }).locator('.meeting-item').click()
  await page.getByTestId('case-materials-button').click()
  releaseMaterials()
  await expect(page.getByTestId('case-evidence-card')).toHaveCount(0)
  await page.getByTestId('case-materials-close-button').click()

  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topicA }).locator('.meeting-item').click()
  let releaseHistory!: () => void
  const historyGate = new Promise<void>((resolve) => { releaseHistory = resolve })
  await page.route(new RegExp(`/meetings/${meetingAId}/deliberations$`), async (route) => {
    await historyGate
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        active_epoch_id: 'late-a-2',
        active_epoch_number: 2,
        epochs: [
          { id: 'late-a-1', number: 1, event_count: 3 },
          { id: 'late-a-2', number: 2, event_count: 0 },
        ],
      }),
    })
  })
  const requestedHistory = page.waitForRequest((request) => request.url().endsWith(`/meetings/${meetingAId}/deliberations`))
  await page.getByTestId('records-button').click()
  await requestedHistory
  await page.getByTestId('records-close-button').click()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topicB }).locator('.meeting-item').click()
  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('records-epoch-select').locator('option')).toHaveCount(1)
  releaseHistory()
  await expect(page.getByTestId('records-epoch-select').locator('option')).toHaveCount(1)
  await expect(page.getByTestId('step-timeline')).toContainText(topicB)
})

test('late transcript refresh from a previous meeting cannot overwrite the active meeting', async ({ page }) => {
  await page.goto('/')
  const topicA = `E2E late transcript A ${Date.now()}`
  const topicB = `E2E late transcript B ${Date.now()}`
  const meetingAId = await createMeetingViaNewCase(page, topicA)
  await createMeetingViaNewCase(page, topicB)
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topicA }).locator('.meeting-item').click()
  await expect(page.getByTestId('meetings-modal')).not.toBeVisible()

  let releaseTranscript!: () => void
  const transcriptGate = new Promise<void>((resolve) => { releaseTranscript = resolve })
  await page.route(new RegExp(`/meetings/${meetingAId}/transcript\\.md`), async (route) => {
    await transcriptGate
    await route.fulfill({ status: 200, contentType: 'text/markdown', body: '# LATE A TRANSCRIPT MUST NOT LEAK' })
  })
  const requestedTranscript = page.waitForRequest((request) => request.url().includes(`/meetings/${meetingAId}/transcript.md`))
  await page.getByTestId('start-meeting-button').click()
  await requestedTranscript
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topicB }).locator('.meeting-item').click()
  const lateTranscriptResponse = page.waitForResponse((response) => response.url().includes(`/meetings/${meetingAId}/transcript.md`))
  releaseTranscript()
  await lateTranscriptResponse

  await page.getByTestId('records-button').click()
  await page.getByTestId('records-tab-transcript').click()
  await expect(page.getByTestId('transcript-preview')).not.toContainText('LATE A TRANSCRIPT MUST NOT LEAK')
  await expect(page.getByTestId('step-timeline')).toHaveCount(0)
})

test('records and case-material initial load errors stay local and can be retried', async ({ page }) => {
  await page.goto('/')
  const meetingId = await createMeetingViaNewCase(page, `E2E drawer retry ${Date.now()}`)
  let recordsAttempts = 0
  await page.route(new RegExp(`/meetings/${meetingId}/deliberations$`), async (route) => {
    recordsAttempts += 1
    if (recordsAttempts === 1) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '紀錄暫時無法載入' }) })
      return
    }
    await route.continue()
  })
  await page.getByTestId('records-button').click()
  await expect(page.getByTestId('records-load-error')).toContainText('紀錄暫時無法載入')
  await page.getByTestId('retry-records-load-button').click()
  await expect(page.getByTestId('records-epoch-select')).toBeVisible()
  await expect(page.getByTestId('records-load-error')).toHaveCount(0)
  await page.getByTestId('records-close-button').click()

  let materialsAttempts = 0
  await page.route(new RegExp(`/meetings/${meetingId}/materials$`), async (route) => {
    materialsAttempts += 1
    if (materialsAttempts === 1) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '案卷暫時無法載入' }) })
      return
    }
    await route.continue()
  })
  await page.getByTestId('case-materials-button').click()
  await expect(page.getByTestId('materials-load-error')).toContainText('案卷暫時無法載入')
  await page.getByTestId('retry-materials-load-button').click()
  await expect(page.getByTestId('case-material-form')).toBeVisible()
  await expect(page.getByTestId('materials-load-error')).toHaveCount(0)
})

test('model manager tab supports create, test, edit, and delete for a model config', async ({
  page,
}) => {
  await page.goto('/')

  const modelId = `e2e-added-mock-${Date.now()}`
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

  await closeSettings(page)
  await page.getByTestId('new-case-button').click()
  await page.getByTestId('mode-select-card-red-blue').getByRole('button', { name: '選擇此模式' }).click()
  await expect(page.getByTestId('new-case-blue-model-select').locator(`option[value="${modelId}"]`)).toHaveCount(0)
  await page.getByTestId('new-case-close-button').click()
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
  await page.getByTestId('advanced-settings-tab').click()
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
  await page.getByTestId('advanced-settings-tab').click()
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

test('editing another model invalidates every pending connection test', async ({ page }) => {
  let pendingTestRoute: Route | undefined
  let modelRefreshCount = 0
  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  const testedRow = modelManagerRow(page, 'mock-fast')
  const initialStatus = await testedRow.locator('.status-dot').getAttribute('data-status')

  await page.route('**/models', async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    modelRefreshCount += 1
    const response = await route.fetch()
    const models = (await response.json()) as Array<Record<string, unknown>>
    const staleStatus = initialStatus === 'unavailable' ? 'available' : 'unavailable'
    await route.fulfill({
      response,
      json: models.map((model) =>
        model.id === 'mock-fast'
          ? { ...model, status: staleStatus, health_error: 'stale test result' }
          : model,
      ),
    })
  })
  await page.route('**/models/mock-fast/test', async (route) => {
    pendingTestRoute = route
  })

  await page.getByTestId('test-model-button-mock-fast').click()
  await expect.poll(() => Boolean(pendingTestRoute)).toBe(true)
  await page.getByTestId('edit-model-button-mock-slow').click()
  await expect(page.getByTestId('model-form-id-input')).toHaveValue('mock-slow')
  await pendingTestRoute!.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ status: 'available', tested_at: '2026-07-14T12:04:00Z' }),
  })

  await expect(testedRow.getByTestId('model-test-feedback-mock-fast')).toHaveCount(0)
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  )
  expect(modelRefreshCount).toBe(0)
  await expect(testedRow.locator('.status-dot')).toHaveAttribute('data-status', initialStatus!)
})

test('an invalidated model refresh cannot overwrite a newer shared health projection', async ({
  page,
}) => {
  let modelGetCount = 0
  let oldGetRoute: Route | undefined
  let oldGetResponse: Awaited<ReturnType<Route['fetch']>> | undefined
  let oldModels: Array<Record<string, unknown>> = []
  let markOldGetStarted!: () => void
  const oldGetStarted = new Promise<void>((resolve) => {
    markOldGetStarted = resolve
  })

  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.route('**/models/mock-fast/test', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ status: 'available', tested_at: '2026-07-14T12:05:00Z' }),
    })
  })
  await page.route('**/models', async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    modelGetCount += 1
    const response = await route.fetch()
    const models = (await response.json()) as Array<Record<string, unknown>>
    if (modelGetCount === 1) {
      oldGetRoute = route
      oldGetResponse = response
      oldModels = models.map((model) =>
        model.id === 'mock-fast'
          ? { ...model, status: 'unavailable', health_error: 'stale health projection' }
          : model,
      )
      markOldGetStarted()
      return
    }
    await route.fulfill({
      response,
      json: models.map((model) =>
        model.id === 'mock-fast'
          ? { ...model, status: 'available', health_error: null }
          : model,
      ),
    })
  })

  await page.getByTestId('test-model-button-mock-fast').click()
  await oldGetStarted
  await closeSettings(page)
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('test-model-button-mock-fast').click()
  await expect.poll(() => modelGetCount).toBe(2)
  await expect(
    modelManagerRow(page, 'mock-fast').getByTestId('model-test-feedback-mock-fast'),
  ).toHaveText('連線成功')

  await oldGetRoute!.fulfill({ response: oldGetResponse!, json: oldModels })
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  )
  await page.getByTestId('advanced-settings-tab').click()
  await page.getByTestId('model-manager-tab').click()
  const row = modelManagerRow(page, 'mock-fast')
  await expect(row.locator('.status-dot')).toHaveAttribute('data-status', 'available')
  await expect(row).not.toContainText('stale health projection')
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

test('model discovery search filters a large list and preserves exact model selection', async ({
  page,
}) => {
  let createRequests = 0
  await page.route('**/models/available-models', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    await route.fulfill({
      json: {
        models: [
          'gemini-2.0-flash',
          'gemini-2.5-flash',
          'gemini-2.5-pro',
          'gemini-exp-1206',
        ],
      },
    })
  })
  await page.route('**/models', async (route) => {
    if (route.request().method() === 'POST') createRequests += 1
    await route.continue()
  })
  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('add-model-button').click()
  await page.getByTestId('model-form-provider-select').selectOption('gemini')
  await page.getByTestId('model-form-discover-button').click()

  const search = page.getByRole('searchbox', { name: '搜尋已載入模型' })
  const modelSelect = page.getByTestId('model-form-discovered-model-select')
  await expect(modelSelect.locator('option')).toHaveCount(4)
  await search.fill('2.5')
  await expect(modelSelect.locator('option')).toHaveCount(2)
  await expect(modelSelect).toHaveValue('gemini-2.5-flash')
  await search.fill('not-a-provider-model')
  const noMatch = page.getByTestId('model-form-discovery-no-match')
  await expect(noMatch).toHaveText('找不到符合的模型。')
  await expect(noMatch).toHaveAttribute('role', 'status')
  await expect(page.getByTestId('model-form-save')).toBeDisabled()
  await search.press('Enter')
  expect(createRequests).toBe(0)
  await expect(page.getByTestId('model-form')).toBeVisible()
  await search.clear()
  await expect(modelSelect.locator('option')).toHaveCount(4)
  await expect(modelSelect).toHaveValue('gemini-2.0-flash')
  await expect(page.getByTestId('model-form-save')).toBeEnabled()
  await search.fill('2.5-pro')
  await expect(modelSelect.locator('option')).toHaveCount(1)
  await expect(modelSelect).toHaveValue('gemini-2.5-pro')

  const modelId = `e2e-gemini-search-${Date.now()}`
  await page.getByTestId('model-form-id-input').fill(modelId)
  await page.getByTestId('model-form-save').click()
  expect(createRequests).toBe(1)
  await expect(modelManagerRow(page, modelId)).toContainText('Gemini · gemini-2.5-pro')

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId(`delete-model-button-${modelId}`).click()
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
  await expect(page.getByTestId('model-form-cli-model-mode-select')).toHaveValue('default')
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

test('guided CLI preset validates and saves an advanced exact model ID', async ({ page }) => {
  let createRequests = 0
  let createPayload: Record<string, unknown> | null = null
  await page.route('**/models', async (route) => {
    if (route.request().method() === 'POST') {
      createRequests += 1
      createPayload = route.request().postDataJSON() as Record<string, unknown>
    }
    await route.continue()
  })
  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('add-model-button').click()
  await page.getByTestId('model-form-provider-select').selectOption('subscription-cli')
  const modelId = `e2e-cli-exact-${Date.now()}`
  await page.getByTestId('model-form-id-input').fill(modelId)
  await page.getByTestId('model-form-cli-preset-select').selectOption('agy')
  await page.getByTestId('model-form-cli-model-mode-select').selectOption('exact')

  await page.getByTestId('model-form-save').click()
  await expect(page.getByTestId('model-form-cli-exact-model-error')).toContainText(
    '請輸入 exact model ID',
  )
  expect(createRequests).toBe(0)

  await page.getByTestId('model-form-cli-exact-model-input').fill('agy-exact-x')
  await page.getByTestId('model-form-save').click()
  expect(createRequests).toBe(1)
  expect(createPayload).toMatchObject({
    adapter: 'subscription-cli',
    command: ['agy', '--model', 'agy-exact-x', '-p', '{prompt}'],
    extra_body: { cli_provider: 'agy' },
  })
  await expect(modelManagerRow(page, modelId)).toContainText(
    'Subscription CLI · AGY · agy-exact-x',
  )
  await closeSettings(page)
  await page.getByTestId('new-case-button').click()
  await page.getByTestId('mode-select-card-red-blue').getByRole('button', { name: '選擇此模式' }).click()
  await expect(page.getByTestId('new-case-blue-model-select').locator(`option[value="${modelId}"]`)).toHaveText(
    'Subscription CLI · AGY · agy-exact-x',
  )
  await page.getByTestId('new-case-close-button').click()
  await page.getByTestId('settings-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId(`delete-model-button-${modelId}`).click()
  await closeSettings(page)
})

test('model labels show Provider and exact model across model list and role selectors', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByTestId('settings-button').click()
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
    page.getByTestId('new-case-blue-model-select').locator('option[value="claude-api"]'),
  ).toHaveText('Anthropic · claude-sonnet-4-5')
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

test('editing with changed connection fields previews the current draft instead of saved config', async ({
  page,
}) => {
  let savedConfigRequests = 0
  const previewPayloads: Record<string, unknown>[] = []
  await page.route('**/models/qwen27/available-models', async (route) => {
    savedConfigRequests += 1
    await route.fulfill({ json: { models: ['must-not-use-saved-connection'] } })
  })
  await page.route('**/models/available-models', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    previewPayloads.push(route.request().postDataJSON() as Record<string, unknown>)
    await route.fulfill({ json: { models: ['claude-current-draft'] } })
  })

  await page.goto('/')
  await page.getByTestId('settings-button').click()
  await page.getByTestId('model-manager-tab').click()
  await page.getByTestId('edit-model-button-qwen27').click()
  await page.getByTestId('model-form-provider-select').selectOption('anthropic')
  await page.getByTestId('model-form-base-url-input').fill('https://anthropic-proxy.example.test/v1')
  await page.getByTestId('model-form-api-key-env-input').fill('ANTHROPIC_PROXY_KEY')
  await page.getByTestId('model-form-discover-button').click()

  await expect(page.getByTestId('model-form-discovered-model-select')).toHaveValue(
    'claude-current-draft',
  )
  expect(previewPayloads).toEqual([{
    adapter: 'anthropic-http',
    base_url: 'https://anthropic-proxy.example.test/v1',
    api_key_env: 'ANTHROPIC_PROXY_KEY',
  }])
  expect(savedConfigRequests).toBe(0)
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

test('saving a recognized markerless CLI preset does not inject cli_provider', async ({ page }) => {
  const modelsResponsePromise = page.waitForResponse(
    (response) => response.request().method() === 'GET' && response.url().endsWith('/models'),
  )
  await page.goto('/')
  const apiOrigin = new URL((await modelsResponsePromise).url()).origin
  const modelId = `e2e-markerless-cli-${Date.now()}`
  expect((await page.request.post(`${apiOrigin}/models`, {
    data: {
      id: modelId,
      adapter: 'subscription-cli',
      command: ['claude', '-p', '{prompt}'],
      extra_body: {},
      timeout_seconds: 300,
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
  await expect(page.getByTestId('model-form-cli-preset-select')).toHaveValue('claude')
  await expect(page.getByTestId('model-form-cli-model-mode-select')).toHaveValue('default')
  const defaultUpdate = page.waitForResponse((response) =>
    response.request().method() === 'PUT' && response.url().endsWith(`/models/${modelId}`),
  )
  await page.getByTestId('model-form-save').click()
  expect((await defaultUpdate).ok()).toBe(true)
  expect(updatePayload).toMatchObject({
    command: ['claude', '-p', '{prompt}'],
    extra_body: {},
  })
  await expect(page.getByTestId('model-form')).not.toBeVisible()

  updatePayload = null
  await page.getByTestId(`edit-model-button-${modelId}`).click()
  await page.getByTestId('model-form-cli-model-mode-select').selectOption('exact')
  await page.getByTestId('model-form-cli-exact-model-input').fill('claude-exact-x')
  const exactUpdate = page.waitForResponse((response) =>
    response.request().method() === 'PUT' && response.url().endsWith(`/models/${modelId}`),
  )
  await page.getByTestId('model-form-save').click()
  expect((await exactUpdate).ok()).toBe(true)
  expect(updatePayload).toMatchObject({
    command: ['claude', '--model', 'claude-exact-x', '-p', '{prompt}'],
    extra_body: { cli_provider: 'claude' },
  })
  await expect(page.getByTestId('model-form')).not.toBeVisible()
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
  await page.getByTestId('settings-button').click()
  const modelId = 'e2e-fallback-mock'
  await page.getByTestId('add-model-button').click()
  await page.getByTestId('model-form-id-input').fill(modelId)
  await page.getByTestId('model-form-save').click()
  await expect(modelManagerRow(page, modelId)).toBeVisible()
  await closeSettings(page)
  const topic = `E2E deleted assigned model ${Date.now()}`
  await createMeetingViaNewCase(page, topic, { modelAssignments: { Blue: modelId } })
  await expect(page.getByTestId('seat-model-label-blue')).toContainText(modelId)
  await page.getByTestId('settings-button').click()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId(`delete-model-button-${modelId}`).click()
  await expect(modelManagerRow(page, modelId)).toHaveCount(0)
  await closeSettings(page)
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: topic }).locator('.meeting-item').click()
  await expect(page.getByTestId('seat-model-label-blue')).toHaveText('Mock · mock-fast')
  await page.getByTestId('meeting-settings-button').click()
  await expect(page.getByTestId('assignment-fallback-warning')).toContainText(modelId)
})
