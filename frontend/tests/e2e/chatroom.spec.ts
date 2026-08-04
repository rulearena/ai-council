import { expect, test, type Page } from '@playwright/test'

/**
 * Chatroom e2e tests — backlog #91 task group 13.
 *
 * The chatroom mode has 4 roles (Advisor, Critic, Strategist, Analyst) defined in
 * config/modes.yaml.  The mock models (mock-fast, mock-slow) in config/models.yaml.example
 * make AI responses deterministic and fast.
 */

// ── helpers ──────────────────────────────────────────────────────────────────

async function createChatroomMeeting(
  page: Page,
  title: string,
  options: {
    goal?: string
    modelAssignments?: Record<string, string>
  } = {},
) {
  const modeId = 'chatroom'
  await page.getByTestId('new-case-button').click()
  await page
    .getByTestId(`mode-select-card-${modeId}`)
    .getByRole('button', { name: '選擇此模式' })
    .click()
  await page.getByLabel('會議名稱', { exact: true }).fill(title)
  // Only fill goal if explicitly provided — chatroom allows goal-less meetings.
  if (options.goal !== undefined) {
    await page.getByLabel('目標', { exact: true }).fill(options.goal)
  }
  for (const [role, modelId] of Object.entries(options.modelAssignments ?? {})) {
    await page.getByTestId(`new-case-${role.toLowerCase()}-model-select`).selectOption(modelId)
  }
  const createdResponse = page.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().endsWith('/meetings'),
  )
  await page.getByTestId('create-meeting-button').click()
  // Wait for the workspace to appear (more reliable than modal close transition)
  await expect(page.getByTestId('conversation-workspace')).toBeVisible({ timeout: 15_000 })
  return ((await createdResponse).json() as Promise<{ meeting_id: string }>).then(
    (meeting) => meeting.meeting_id,
  )
}

async function openChatroom(page: Page, title: string) {
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: title }).locator('.meeting-item').click()
  await expect(page.getByTestId('chatroom-composer')).toBeVisible()
}

async function sendChatMessage(page: Page, text: string) {
  await page.getByTestId('chat-message-input').fill(text)
  await page.getByTestId('send-chat-message-button').click()
}

/** Wait for a workspace-message with matching text to appear. */
async function waitForMessage(page: Page, text: string) {
  await expect(page.getByTestId('workspace-message-feed')).toContainText(text, { timeout: 10_000 })
}

/** Wait for a workspace-message from a specific role to appear. */
async function waitForRoleMessage(page: Page, roleText: string) {
  await expect(
    page.getByTestId('workspace-message').filter({ hasText: roleText }).first(),
  ).toBeVisible({ timeout: 15_000 })
}

// Default model assignments for chatroom creation (all mock-fast for speed).
const defaultModels = {
  Advisor: 'mock-fast',
  Critic: 'mock-fast',
  Strategist: 'mock-fast',
  Analyst: 'mock-fast',
}

// ── 13.1 ─────────────────────────────────────────────────────────────────────

test('13.1 create chatroom meeting (title only, no goal)', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom create ${Date.now()}`
  const meetingId = await createChatroomMeeting(page, title, {
    modelAssignments: defaultModels,
  })
  expect(meetingId).toBeTruthy()
  await expect(page.getByTestId('conversation-workspace')).toBeVisible()
  await expect(page.getByTestId('chatroom-composer')).toBeVisible()
  await expect(page.getByTestId('workspace-mode-badge')).toContainText('聊天室')
})

// ── 13.2 ─────────────────────────────────────────────────────────────────────

test('13.2 send plain text message in chatroom', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom plain text ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  await sendChatMessage(page, '大家好，這是一個測試訊息。')
  await waitForMessage(page, '大家好，這是一個測試訊息。')

  // Plain text without @mention should show as a human message, no AI response
  const messages = page.getByTestId('workspace-message')
  const humanMsg = messages.filter({ hasText: '大家好，這是一個測試訊息。' })
  await expect(humanMsg).toBeVisible()
  // No AI role messages should appear for a plain text message
  await expect(messages).toHaveCount(1, { timeout: 3000 })
})

// ── 13.3 ─────────────────────────────────────────────────────────────────────

test('13.3 send @Advisor mention — verify AI response appears', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom mention single ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  await sendChatMessage(page, '@Advisor 看看這個')
  await waitForMessage(page, '@Advisor 看看這個')

  // Wait for Advisor's AI response
  await waitForRoleMessage(page, '顧問')
  const feed = page.getByTestId('workspace-message-feed')
  await expect(feed).toContainText('Mock chat response.')
  await expect(feed).not.toContainText('摘要')
  await expect(feed).not.toContainText('論點')
  await expect(feed).not.toContainText('風險')
  await expect(feed).not.toContainText('建議處置')
  // The message feed should contain at least 2 messages (human + AI)
  await expect(page.getByTestId('workspace-message')).toHaveCount(2, { timeout: 15_000 })
})

// ── 13.4 ─────────────────────────────────────────────────────────────────────

test('13.4 send @all — all roles respond', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom @all ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  await sendChatMessage(page, '@all 大家覺得呢？')
  await waitForMessage(page, '@all 大家覺得呢？')

  // All 4 roles should respond — wait for each
  await waitForRoleMessage(page, '顧問')
  await waitForRoleMessage(page, '評論者')
  await waitForRoleMessage(page, '策略師')
  await waitForRoleMessage(page, '分析師')

  // 1 human + 4 AI = 5 messages
  await expect(page.getByTestId('workspace-message')).toHaveCount(5, { timeout: 30_000 })
})

test('13.4a @all renders one round and all pending placeholders before the request is released', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom @all pending ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  let releaseRequest!: () => void
  const requestGate = new Promise<void>((resolve) => { releaseRequest = resolve })
  await page.route('**/meetings/*/chat/mention', async (route) => {
    await requestGate
    await route.continue()
  })

  await sendChatMessage(page, '@all 先同時想想看')
  await expect(page.getByTestId('fanout-round')).toHaveCount(1)
  await expect(page.getByTestId('fanout-round-header')).toContainText('0/4')
  await expect(page.getByTestId('fanout-round-placeholder')).toHaveCount(4)

  releaseRequest()
  await waitForRoleMessage(page, '顧問')
  await waitForRoleMessage(page, '評論者')
  await waitForRoleMessage(page, '策略師')
  await waitForRoleMessage(page, '分析師')
})

// ── 13.4b ────────────────────────────────────────────────────────────────────

test('13.4b send @Advisor @Critic — both respond in parallel', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom multi-mention ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  await sendChatMessage(page, '@Advisor @Critic 你們覺得呢？')
  await waitForMessage(page, '@Advisor @Critic 你們覺得呢？')

  await waitForRoleMessage(page, '顧問')
  await waitForRoleMessage(page, '評論者')

  // 1 human + 2 AI = 3 messages
  await expect(page.getByTestId('workspace-message')).toHaveCount(3, { timeout: 15_000 })
  await expect(page.getByTestId('fanout-round')).toHaveCount(0)
})

// ── 13.5 ─────────────────────────────────────────────────────────────────────

test('13.5 quote an existing message — verify quoted context in AI response', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom quote ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // First, send a plain message to have something to quote
  await sendChatMessage(page, '這是一條需要引用的訊息')
  await waitForMessage(page, '這是一條需要引用的訊息')

  // Click the quote button on the first AI response or human message
  // Quote buttons only appear on non-human, non-system messages in chatroom mode
  // Since no AI messages yet, we need to first trigger an AI response
  await sendChatMessage(page, '@Advisor 請回答')
  await waitForMessage(page, '@Advisor 請回答')
  await waitForRoleMessage(page, '顧問')

  // Now click the quote button on the Advisor's response
  const advisorMessage = page.getByTestId('workspace-message').filter({ hasText: '顧問' }).first()
  await advisorMessage.getByTestId('quote-message-button').click()
  await expect(page.getByTestId('quote-indicator')).toBeVisible()

  // Send a quoted message
  await sendChatMessage(page, '@Advisor 你剛才說了什麼？')
  await waitForMessage(page, '你剛才說了什麼？')

  // The quote indicator should be dismissed after sending
  await expect(page.getByTestId('quote-indicator')).not.toBeVisible()

  // Advisor should respond (with quoted context)
  await waitForRoleMessage(page, '顧問')
  // 1 plain human + 2 directed-message+response pairs = 5 events rendered as messages
  await expect(page.getByTestId('workspace-message')).toHaveCount(5, { timeout: 15_000 })
})

test('13.5a quote preview keeps the dark theme at desktop and responsive widths', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom quote theme ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  await sendChatMessage(page, '@Advisor 請回答')
  await waitForMessage(page, '@Advisor 請回答')
  await waitForRoleMessage(page, '顧問')

  const advisorMessage = page.getByTestId('workspace-message').filter({ hasText: '顧問' }).first()
  await advisorMessage.getByTestId('quote-message-button').click()
  const quote = page.getByTestId('quote-indicator')
  const preview = page.getByTestId('quote-indicator').locator('.chatroom-composer-quote-preview')
  const dismiss = page.getByTestId('dismiss-quote-button')

  await expect(quote).toBeVisible()
  await expect(quote).toHaveCSS('background-color', 'rgb(23, 28, 39)')
  await expect(quote).toHaveCSS('border-color', 'rgb(46, 56, 72)')
  await expect(preview).toHaveCSS('color', 'rgb(230, 234, 242)')
  await expect(dismiss).toHaveCSS('color', 'rgb(230, 234, 242)')

  await page.setViewportSize({ width: 375, height: 667 })
  await expect(quote).toBeVisible()
  // mock-fast returns a deliberately short deterministic response. Keep the
  // real 引用 seam above, then lengthen the visible preview to exercise the
  // responsive layout with the long content that caused the original bug.
  await preview.evaluate((element) => {
    element.textContent = `${element.textContent} ${'長引用內容 '.repeat(40)}`
  })
  const responsiveLayout = await quote.evaluate((element) => {
    const composer = element.parentElement
    const previewElement = element.querySelector('.chatroom-composer-quote-preview')
    if (!composer || !previewElement) throw new Error('quote preview seam is missing')
    return {
      quoteWidth: element.getBoundingClientRect().width,
      composerWidth: composer.getBoundingClientRect().width,
      previewWidth: previewElement.getBoundingClientRect().width,
      quoteScrollWidth: element.scrollWidth,
      quoteClientWidth: element.clientWidth,
      composerScrollWidth: composer.scrollWidth,
      composerClientWidth: composer.clientWidth,
    }
  })
  expect(responsiveLayout.quoteWidth).toBeLessThanOrEqual(responsiveLayout.composerWidth)
  expect(responsiveLayout.quoteScrollWidth).toBeLessThanOrEqual(responsiveLayout.quoteClientWidth)
  expect(responsiveLayout.composerScrollWidth).toBeLessThanOrEqual(responsiveLayout.composerClientWidth)
  expect(responsiveLayout.previewWidth).toBeGreaterThan(0)
  await expect(quote).toHaveCSS('background-color', 'rgb(23, 28, 39)')
  await expect(quote).toHaveCSS('border-color', 'rgb(46, 56, 72)')
  await expect(dismiss).toBeVisible()
  await expect(dismiss).toHaveCSS('color', 'rgb(230, 234, 242)')
})

// ── 13.6 ─────────────────────────────────────────────────────────────────────

test('13.6 reload chatroom — messages persist', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom persist ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  await sendChatMessage(page, '持久化測試訊息')
  await waitForMessage(page, '持久化測試訊息')

  await sendChatMessage(page, '@Advisor 第二條訊息')
  await waitForMessage(page, '@Advisor 第二條訊息')
  await waitForRoleMessage(page, '顧問')

  // Reload the page — no URL/localStorage persistence, must re-navigate
  await page.reload()
  await expect(page.getByTestId('past-topics-button')).toBeVisible()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: title }).locator('.meeting-item').click()
  await expect(page.getByTestId('chatroom-composer')).toBeVisible()

  // Messages should persist
  await expect(page.getByTestId('workspace-message-feed')).toContainText('持久化測試訊息')
  await expect(page.getByTestId('workspace-message-feed')).toContainText('第二條訊息')
})

// ── 13.7 ─────────────────────────────────────────────────────────────────────

test('13.7 @all with one role failing — partial success visible', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom partial fail ${Date.now()}`
  // Assign mock-broken to Advisor so it fails
  await createChatroomMeeting(page, title, {
    modelAssignments: {
      Advisor: 'mock-broken',
      Critic: 'mock-fast',
      Strategist: 'mock-fast',
      Analyst: 'mock-fast',
    },
  })

  await sendChatMessage(page, '@all 失敗測試')
  await waitForMessage(page, '@all 失敗測試')

  // Wait for at least some responses to arrive — the 3 working roles should complete
  await waitForRoleMessage(page, '評論者')
  await waitForRoleMessage(page, '策略師')
  await waitForRoleMessage(page, '分析師')

  // The failed role (Advisor) should show a failure indicator
  // In chatroom mode, failedRole (v-if="failedRole") never renders because chatroom has no steps.
  // Instead, the role seat gets data-status="failed" via projectRoles' generic failed-kind check,
  // and the failed message appears in the feed with '本次回應失敗。' text.
  await expect(page.getByTestId('role-seat-advisor')).toHaveAttribute('data-status', 'failed', { timeout: 15_000 })
})

// ── 13.8 ─────────────────────────────────────────────────────────────────────

test('13.8 responsive at 375px viewport', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom mobile ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // Set mobile viewport
  await page.setViewportSize({ width: 375, height: 812 })

  // Composer should still be visible and usable
  await expect(page.getByTestId('chatroom-composer')).toBeVisible()
  await expect(page.getByTestId('chat-message-input')).toBeVisible()
  await expect(page.getByTestId('send-chat-message-button')).toBeVisible()

  // Messages should still be readable
  await sendChatMessage(page, '手機版測試')
  await waitForMessage(page, '手機版測試')

  // Verify no horizontal overflow
  const composerBox = await page.getByTestId('chatroom-composer').boundingBox()
  expect(composerBox!.x).toBeGreaterThanOrEqual(0)
  expect(composerBox!.x + composerBox!.width).toBeLessThanOrEqual(375)
})

// ── 13.9 ─────────────────────────────────────────────────────────────────────

test('13.9 no court CTA, no step progress bar, no 開始新回合 in chatroom', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom no-court ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // chatroom-composer should be visible (replaces ActionBar)
  await expect(page.getByTestId('chatroom-composer')).toBeVisible()

  // ActionBar elements should NOT be present
  await expect(page.getByTestId('step-progress-indicator')).not.toBeVisible()
  await expect(page.getByTestId('start-meeting-button')).not.toBeVisible()

  // workspace-mode-badge should show 聊天室
  await expect(page.getByTestId('workspace-mode-badge')).toContainText('聊天室')
})

// ── 13.10 ────────────────────────────────────────────────────────────────────

test('13.10 mention autocomplete — @ shows participant list', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom autocomplete ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // Type @ in the chat input
  await page.getByTestId('chat-message-input').fill('@')

  // The mention autocomplete menu should appear
  await expect(page.getByTestId('mention-autocomplete')).toBeVisible()
  await expect(page.getByTestId('mention-menu')).toBeVisible()

  // Should list all 4 roles plus the "all members" option = 5 total
  const options = page.getByTestId('mention-option')
  await expect(options).toHaveCount(5)

  // Verify role names are present
  await expect(page.getByTestId('mention-menu')).toContainText('顧問')
  await expect(page.getByTestId('mention-menu')).toContainText('評論者')
  await expect(page.getByTestId('mention-menu')).toContainText('策略師')
  await expect(page.getByTestId('mention-menu')).toContainText('分析師')

  // Click on the second option (first role = Advisor; first item is "all members")
  await options.nth(1).click()

  // The input should now contain the selected mention
  const inputValue = await page.getByTestId('chat-message-input').inputValue()
  expect(inputValue).toContain('@Advisor')

  // Menu should close after selection
  await expect(page.getByTestId('mention-menu')).not.toBeVisible()
})

// ── 13.11 ────────────────────────────────────────────────────────────────────

test('13.11 seat click filters feed — identical for Chairman and role seats', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom seat filter ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // Send a chairman message
  await sendChatMessage(page, '主席測試訊息')
  await waitForMessage(page, '主席測試訊息')

  // Send an Advisor message via @mention
  await sendChatMessage(page, '@Advisor 請回覆')
  await waitForRoleMessage(page, '顧問')

  // Click Chairman seat → feed filters to Chairman messages only
  await page.getByTestId('role-seat-chairman').click()
  await expect(page.getByTestId('workspace-clear-role-filter')).toBeVisible()
  const chairmanMessages = page.getByTestId('workspace-message')
  await expect(chairmanMessages.first()).toHaveAttribute('data-role', 'Human')

  // Click Chairman seat again → filter clears
  await page.getByTestId('role-seat-chairman').click()
  await expect(page.getByTestId('workspace-clear-role-filter')).not.toBeVisible()

  // Click Advisor seat → feed filters to Advisor messages only
  await page.getByTestId('role-seat-advisor').click()
  await expect(page.getByTestId('workspace-clear-role-filter')).toBeVisible()
  const advisorMessages = page.getByTestId('workspace-message')
  await expect(advisorMessages.first()).toHaveAttribute('data-role', 'Advisor')

  // Click Advisor seat again → filter clears
  await page.getByTestId('role-seat-advisor').click()
  await expect(page.getByTestId('workspace-clear-role-filter')).not.toBeVisible()

  // Secondary detail control (ℹ) opens the RoleDrawer without filtering
  await page.getByTestId('role-seat-chairman-info').click()
  await expect(page.getByTestId('role-drawer')).toBeVisible()
  await page.getByTestId('role-drawer-close-button').click()
  await expect(page.getByTestId('role-drawer')).not.toBeVisible()
  // Feed should still show all messages (no filter applied)
  await expect(page.getByTestId('workspace-clear-role-filter')).not.toBeVisible()
})

// ── 13.12 ────────────────────────────────────────────────────────────────────

test('13.12 message cards display role avatars', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom avatars ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // Send an Advisor message via @mention
  await sendChatMessage(page, '@Advisor 請回覆')
  await waitForRoleMessage(page, '顧問')

  // The message card should contain an avatar element
  const advisorMessage = page.getByTestId('workspace-message').filter({ hasText: '顧問' }).first()
  await expect(advisorMessage.getByTestId('workspace-message-avatar')).toBeVisible()
})

// ── 13.13 ────────────────────────────────────────────────────────────────────

test('13.13 chatroom is the first mode in the mode picker', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('new-case-button').click()
  await expect(page.getByTestId('new-case-modal')).toBeVisible()

  // The first mode card should be chatroom
  const firstCard = page.getByTestId('new-case-modal').locator('.mode-card').first()
  await expect(firstCard).toContainText('聊天室')
})

// ── 13.14 ────────────────────────────────────────────────────────────────────

test('13.14 clicking scene image opens enlarged lightbox modal', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom lightbox ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })
  await expect(page.getByTestId('conversation-workspace')).toBeVisible()
  await expect(page.getByTestId('workspace-message-feed')).toBeVisible()

  // Expand scene details and click the scene image
  const sceneDetails = page.getByTestId('workspace-scene-details')
  await sceneDetails.locator('summary').click()
  const sceneImage = sceneDetails.getByTestId('scene-enlarge-trigger')
  await expect(sceneImage).toBeVisible()
  await sceneImage.click()

  // Lightbox modal should appear with enlarged scene
  const lightbox = page.getByTestId('scene-lightbox-modal')
  await expect(lightbox).toBeVisible()
  await expect(lightbox.locator('.stage-scene')).toBeVisible()

  // Close via Escape
  await page.keyboard.press('Escape')
  await expect(lightbox).not.toBeVisible()
})

// ── 13.15 ────────────────────────────────────────────────────────────────────

test('13.15 switch role model directly from the role rail', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom model switch ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })
  await expect(page.getByTestId('conversation-workspace')).toBeVisible()
  await expect(page.getByTestId('workspace-message-feed')).toBeVisible()

  // The Advisor seat should have a model label
  const advisorModelLabel = page.getByTestId('seat-model-label-advisor')
  await expect(advisorModelLabel).toBeVisible()
  const initialLabel = await advisorModelLabel.textContent()

  // Click the model label to open the inline model select
  await advisorModelLabel.click()
  const modelSelect = page.getByTestId('seat-model-select-advisor')
  await expect(modelSelect).toBeVisible()

  // No `if (optionCount > 1)` guard: a catalogue too small to switch within is a
  // broken fixture, not a reason to silently skip. The previous guarded version
  // reported green while a chatroom model switch was 500-ing on the backend,
  // because switchSeatModel closes the select even when the save fails.
  const options = modelSelect.locator('option')
  expect(await options.count(), '模型目錄至少需要兩個模型才能測換模型').toBeGreaterThan(1)
  const secondValue = await options.nth(1).getAttribute('value')
  expect(secondValue).toBeTruthy()
  await modelSelect.selectOption(secondValue!)

  // Assert the switch actually took effect — closing the select proves nothing.
  await expect(advisorModelLabel).toBeVisible()
  await expect(advisorModelLabel).not.toHaveText(initialLabel ?? '')
  await expect(page.getByTestId('assignment-update-error')).toHaveCount(0)
})

// ── 13.16 ────────────────────────────────────────────────────────────────────

test('13.16 records tab in context panel shows meeting records', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom records ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })
  await expect(page.getByTestId('conversation-workspace')).toBeVisible()
  await expect(page.getByTestId('workspace-message-feed')).toBeVisible()

  // Context panel should have a records tab toggle
  const recordsTab = page.getByTestId('context-tab-records')
  await expect(recordsTab).toBeVisible()
  await recordsTab.click()

  // Records content should be visible in the context panel
  const recordsSection = page.getByTestId('context-records-section')
  await expect(recordsSection).toBeVisible()
})

// ── 13.17 ────────────────────────────────────────────────────────────────────

test('13.17 records accessible from courtroom context panel without modal', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('new-case-button').click()
  await expect(page.getByTestId('new-case-modal')).toBeVisible()
  await page.getByTestId('mode-select-card-courtroom').getByRole('button', { name: '選擇此模式' }).click()
  await page.getByLabel('會議名稱', { exact: true }).fill(`E2E courtroom records ${Date.now()}`)
  await page.getByLabel('目標', { exact: true }).fill('測試法院紀錄分頁')
  await page.getByTestId('courtroom-case-type-select').selectOption('civil')
  await page.getByTestId('create-meeting-button').click()
  await expect(page.getByTestId('new-case-modal')).not.toBeVisible()
  await expect(page.getByTestId('court-hearing-workspace')).toBeVisible()

  // Courtroom context panel should have a records section
  const recordsTab = page.getByTestId('court-context-tab-records')
  await expect(recordsTab).toBeVisible()
  await recordsTab.click()

  const recordsSection = page.getByTestId('court-context-records-section')
  await expect(recordsSection).toBeVisible()
})

// ── 13.18 ────────────────────────────────────────────────────────────────────

test('13.18 no meeting-subnav row renders when a meeting is open', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom no-subnav ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })
  await expect(page.getByTestId('conversation-workspace')).toBeVisible()
  await expect(page.getByTestId('workspace-message-feed')).toBeVisible()

  // The old meeting-subnav row should NOT exist
  await expect(page.getByRole('navigation', { name: '會議工作區' })).not.toBeVisible()
})

// ── 13.19 ────────────────────────────────────────────────────────────────────

test('13.19 message feed scrolls via real browser wheel and auto-scrolls during streaming', async ({ page }) => {
  test.setTimeout(60_000)
  await page.setViewportSize({ width: 1024, height: 600 })
  await page.goto('/')
  const title = `E2E chatroom scroll ${Date.now()}`
  const meetingId = await createChatroomMeeting(page, title, { modelAssignments: defaultModels })
  await expect(page.getByTestId('conversation-workspace')).toBeVisible()
  await expect(page.getByTestId('workspace-message-feed')).toBeVisible()

  const feed = page.getByTestId('workspace-message-feed')

  // Verify feed has proper overflow for scrolling
  const overflowY = await feed.evaluate((el) => getComputedStyle(el).overflowY)
  expect(overflowY).toBe('auto')

  // Verify feed has a constrained height (not unbounded)
  const height = await feed.evaluate((el) => el.clientHeight)
  expect(height).toBeGreaterThan(0)
  expect(height).toBeLessThan(5000)

  // Send enough messages to make feed scrollable.  We use the Playwright
  // request context to POST directly to the backend, bypassing the
  // composer UI.  This avoids the `sending` ref getting stuck when the
  // backend is under load from prior tests.
  const apiOrigin = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:5009'
  for (let i = 0; i < 20; i++) {
    const posted = await page.request.post(`${apiOrigin}/meetings/${meetingId}/messages`, {
      data: { content: `測試訊息 ${i}` },
    })
    // Without this the injection silently 404s when E2E_API_BASE_URL is unset and the
    // default port holds a different backend, and the real cause surfaces ten seconds
    // later as an unexplained empty feed.
    expect(posted.ok(), `injecting 測試訊息 ${i} returned ${posted.status()}`).toBeTruthy()
    await expect(feed).toContainText(`測試訊息 ${i}`)
  }

  // The shell is capped at the viewport, so the page itself must never scroll and
  // the feed must overflow internally — with NO injected height. A previous version
  // of this test set `el.style.maxHeight = '400px'` here, which manufactured the very
  // constraint the product CSS was missing and therefore passed against a broken build.
  const pageScrolls = await page.evaluate(
    () => document.documentElement.scrollHeight > window.innerHeight,
  )
  expect(pageScrolls, 'Page itself must not scroll — only the message feed may').toBe(false)

  const scrollable = await feed.evaluate((el) => el.scrollHeight > el.clientHeight)
  expect(scrollable, 'Feed must overflow internally after 20 messages, unaided').toBe(true)

  // The composer and the role rail are part of the fixed frame: scrolling the feed
  // must not move them. This is the symptom the Human Owner originally reported.
  const composer = page.getByTestId('chat-message-input')
  const rail = page.getByTestId('workspace-role-rail')
  const composerTopBefore = (await composer.boundingBox())?.y
  const railTopBefore = (await rail.boundingBox())?.y

  // Wait for any pending AI responses from the loop to settle so that the
  // next single message arrives alone (gap < 80px threshold).
  const stabilizeCount = await feed.evaluate(
    (el) => el.querySelectorAll('[data-testid="workspace-message"]').length,
  )
  await page.waitForTimeout(2000)
  const stabilizedCount = await feed.evaluate(
    (el) => el.querySelectorAll('[data-testid="workspace-message"]').length,
  )
  // If more messages arrived, wait once more for full settling.
  if (stabilizedCount > stabilizeCount) {
    await page.waitForTimeout(2000)
  }

  // Scroll to top using real browser method
  await feed.evaluate((el) => { el.scrollTop = 0 })
  await expect.poll(() => feed.evaluate((el) => el.scrollTop)).toBe(0)

  // Use Playwright's mouse.wheel for real browser-level scrolling
  const feedBox = await feed.boundingBox()
  if (feedBox) {
    await page.mouse.move(feedBox.x + feedBox.width / 2, feedBox.y + feedBox.height / 2)
    await page.mouse.wheel(0, 300)
  }

  // Feed should have scrolled away from top
  await expect.poll(() => feed.evaluate((el) => el.scrollTop), { timeout: 2000 }).toBeGreaterThan(0)

  // …and the fixed frame must have stayed put while it did.
  expect((await composer.boundingBox())?.y, '輸入框必須固定，不得隨捲動移動').toBe(composerTopBefore)
  expect((await rail.boundingBox())?.y, '角色列必須固定，不得隨捲動移動').toBe(railTopBefore)

  // ── Auto-scroll assertion ──────────────────────────────────────────────────
  // Verify the auto-scroll watch (ConversationWorkspace.vue:120-133) keeps
  // the feed scrolled to the bottom when a new message arrives.
  //
  // The correct invariant: after a message appears while the feed is at the
  // bottom, scrollTop must increase to the new scrollHeight − clientHeight.
  // Without the watch, scrollTop stays at its old (clamped) value while
  // scrollHeight grows — a gap opens and scrollTop does not change.
  // A simple "gap < N" check is unreliable because the browser-clamped
  // scrollTop already sits at the maximum, producing a small gap even
  // without auto-scroll.
  await feed.evaluate((el) => { el.scrollTop = el.scrollHeight })
  const scrollTopBefore = await feed.evaluate((el) => el.scrollTop)
  expect(scrollTopBefore).toBeGreaterThan(0) // feed is scrolled to bottom

  await page.getByTestId('chat-message-input').fill('auto-scroll 驗證')
  await page.getByTestId('send-chat-message-button').click()

  // Poll until scrollTop increases — this can only happen when the
  // auto-scroll watch fires scrollToBottom() after the new message
  // grows scrollHeight.  Without the watch, scrollTop never changes.
  await expect.poll(
    () => feed.evaluate((el) => el.scrollTop),
    { timeout: 5000 },
  ).toBeGreaterThan(scrollTopBefore)
})

// ── 13.21 ────────────────────────────────────────────────────────────────────

test('13.21 feed opens on the newest message and a sent message is always visible', async ({ page }) => {
  test.setTimeout(60_000)
  await page.setViewportSize({ width: 1024, height: 600 })
  await page.goto('/')
  const title = `E2E chatroom open-at-bottom ${Date.now()}`
  const meetingId = await createChatroomMeeting(page, title, { modelAssignments: defaultModels })
  const feed = page.getByTestId('workspace-message-feed')
  await expect(feed).toBeVisible()

  // Seed enough history to overflow, straight through the API.
  const apiOrigin = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:5009'
  for (let i = 0; i < 20; i++) {
    const posted = await page.request.post(`${apiOrigin}/meetings/${meetingId}/messages`, {
      data: { content: `歷史訊息 ${i}` },
    })
    expect(posted.ok(), `injecting 歷史訊息 ${i} returned ${posted.status()}`).toBeTruthy()
  }
  await expect(feed).toContainText('歷史訊息 19')
  expect(await feed.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)

  // Reopen the meeting: a chat must land on its newest message, not its oldest.
  await page.reload()
  await page.getByTestId('past-topics-button').click()
  await page.getByTestId('meeting-list-item').filter({ hasText: title }).locator('.meeting-item').click()
  await expect(feed).toBeVisible()
  await expect(feed).toContainText('歷史訊息 19')
  await expect
    .poll(() => feed.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight), { timeout: 5000 })
    .toBeLessThan(80)

  // Scroll away, then send: the Chairman's own message must be brought into view.
  // Without this the composer cleared while the feed stayed put, which reads as
  // "the message never sent".
  await feed.evaluate((el) => { el.scrollTop = 0 })
  await expect.poll(() => feed.evaluate((el) => el.scrollTop)).toBe(0)
  await page.getByTestId('chat-message-input').fill('送出後必須看得到')
  await page.getByTestId('send-chat-message-button').click()
  await expect(feed).toContainText('送出後必須看得到')
  await expect
    .poll(() => feed.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight), { timeout: 5000 })
    .toBeLessThan(80)
})

// ── 13.22 ────────────────────────────────────────────────────────────────────

test('13.22 a mentioned role shows a thinking indicator until it answers', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  const title = `E2E chatroom thinking ${Date.now()}`
  // mock-slow leaves a window in which the in-progress state is observable.
  await createChatroomMeeting(page, title, {
    modelAssignments: { ...defaultModels, Advisor: 'mock-slow' },
  })
  await expect(page.getByTestId('conversation-workspace')).toBeVisible()

  await sendChatMessage(page, '@Advisor 請回覆')

  // Without this the Chairman had no way to tell whether a mentioned role was working:
  // the chatroom composer bypassed the store, so pendingRoles was never populated and
  // neither the feed bubble nor the seat pulse ever appeared.
  const thinking = page.getByTestId('workspace-thinking-message')
  await expect(thinking).toBeVisible({ timeout: 10_000 })
  await expect(thinking).toContainText('顧問')
  await expect(page.getByTestId('role-seat-advisor')).toHaveAttribute('data-status', 'thinking')

  // …and it must clear once the answer lands.
  await waitForRoleMessage(page, '顧問')
  await expect(thinking).toHaveCount(0, { timeout: 20_000 })
})

// ── 13.23 ────────────────────────────────────────────────────────────────────

test('13.23 confirming an IME candidate with Enter does not send the half-typed line', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom ime ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })
  const feed = page.getByTestId('workspace-message-feed')
  await expect(feed).toBeVisible()

  const input = page.getByTestId('chat-message-input')
  await input.fill('hello')

  // Typing Chinese means composing: the pre-edit text is not committed to the model
  // until compositionend, and the Enter that confirms the candidate belongs to the
  // input method. Sending on it shipped only the already-committed 'hello' and threw
  // the Chinese away — exactly what the Chairman saw.
  await input.evaluate((el: HTMLTextAreaElement) => {
    el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))
    el.value = 'hello 你好'
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true }))
  })

  // Committing the candidate, then a genuine Enter, sends the whole line.
  await input.evaluate((el: HTMLTextAreaElement) => {
    el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true }))
  })
  await input.press('Enter')

  // Waiting for the complete line first makes the count assertion sound: a send fired
  // by the composing Enter would have been queued earlier, so it would already be here.
  await expect(feed).toContainText('hello 你好')
  await expect(page.getByTestId('workspace-message')).toHaveCount(1)
  await expect(input).toHaveValue('')
})

// ── 13.24 ────────────────────────────────────────────────────────────────────

test('13.24 the mention menu is fully operable from the keyboard', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom mention keys ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  const input = page.getByTestId('chat-message-input')
  const options = page.getByTestId('mention-option')
  const menu = page.getByTestId('mention-menu')

  await input.fill('@')
  await expect(menu).toBeVisible()

  // The menu opens on the first option — 全體成員 — and says so where a screen reader
  // following the textarea will hear it.
  await expect(options.nth(0)).toHaveAttribute('aria-selected', 'true')
  await expect(input).toHaveAttribute('aria-activedescendant', /-option-0$/)
  await expect(input).toHaveAttribute('aria-expanded', 'true')

  await input.press('ArrowDown')
  await expect(options.nth(1)).toHaveAttribute('aria-selected', 'true')
  await expect(options.nth(0)).toHaveAttribute('aria-selected', 'false')
  await expect(input).toHaveAttribute('aria-activedescendant', /-option-1$/)

  // ArrowUp wraps back past the top rather than sticking.
  await input.press('ArrowUp')
  await input.press('ArrowUp')
  await expect(options.nth(4)).toHaveAttribute('aria-selected', 'true')

  // Escape dismisses without touching the draft and without sending.
  await input.press('Escape')
  await expect(menu).not.toBeVisible()
  await expect(input).toHaveValue('@')
  await expect(page.getByTestId('workspace-message')).toHaveCount(0)

  // Enter picks the highlighted option instead of sending the draft — the menu owns
  // the key while it is open, which is the whole point of it being reachable at all.
  await input.fill('@Advis')
  await expect(menu).toBeVisible()
  await input.press('ArrowDown')
  await input.press('Enter')
  await expect(menu).not.toBeVisible()
  await expect(input).toHaveValue('@Advisor ')
  await expect(page.getByTestId('workspace-message')).toHaveCount(0)

  // With the menu closed, Enter goes back to meaning send.
  await input.press('Enter')
  await expect(page.getByTestId('workspace-message-feed')).toContainText('@Advisor')
  await expect(input).toHaveValue('')
})

// ── 13.25 ────────────────────────────────────────────────────────────────────

test('13.25 an open mention menu ignores keys that belong to the input method', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom mention ime ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  const input = page.getByTestId('chat-message-input')
  const options = page.getByTestId('mention-option')

  await input.fill('@')
  await expect(page.getByTestId('mention-menu')).toBeVisible()

  // An IME uses the arrows to walk its candidate list and Enter to accept one. With the
  // mention menu open those keystrokes must still reach the input method untouched,
  // otherwise wiring up the menu just recreates the bug fixed in 13.23 one layer up.
  await input.evaluate((el: HTMLTextAreaElement) => {
    el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))
    for (const key of ['ArrowDown', 'ArrowDown', 'Enter']) {
      el.dispatchEvent(new KeyboardEvent('keydown', { key, isComposing: true, bubbles: true }))
    }
  })

  await expect(options.nth(0)).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('mention-menu')).toBeVisible()
  await expect(input).toHaveValue('@')
  await expect(page.getByTestId('workspace-message')).toHaveCount(0)

  // Once composition ends the menu answers to the keyboard again.
  await input.evaluate((el: HTMLTextAreaElement) => {
    el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true }))
  })
  await input.press('ArrowDown')
  await expect(options.nth(1)).toHaveAttribute('aria-selected', 'true')
})

// ── 13.26 ────────────────────────────────────────────────────────────────────

test('13.26 the composer plus button opens the file picker directly, no quick menu; the materials tab manages data', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom materials menu ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // The ＋ button no longer opens a menu: it maps straight to the native picker,
  // so the old quick-menu elements are gone and nothing appears on click.
  await page.getByTestId('chatroom-attachment-button').click()
  await expect(page.getByTestId('materials-menu')).toHaveCount(0)
  await expect(page.getByTestId('materials-menu-upload')).toHaveCount(0)
  await expect(page.getByTestId('materials-menu-manage')).toHaveCount(0)

  // Data management lives on the sidebar materials tab, still a panel not a modal.
  await page.getByTestId('context-tab-materials').click()
  await expect(page.getByTestId('context-tab-materials')).toHaveClass(/active/)
  await expect(page.getByTestId('context-tab-materials')).toContainText('資料')
  await expect(page.getByTestId('case-materials-modal')).toHaveCount(0)
})

// ── 13.20 ──────────────────────────────────────────────────────────────────

test('13.20 switch role model at 375px viewport', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom mobile model switch ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })
  await expect(page.getByTestId('conversation-workspace')).toBeVisible()

  await page.setViewportSize({ width: 375, height: 812 })

  const advisorModelLabel = page.getByTestId('seat-model-label-advisor')
  await expect(advisorModelLabel).toBeVisible()
  const initialLabel = await advisorModelLabel.textContent()

  await advisorModelLabel.click()
  const modelSelect = page.getByTestId('seat-model-select-advisor')
  await expect(modelSelect).toBeVisible()

  // Unguarded, and asserting the switch persisted rather than that the select closed
  // — see 13.15 for why the old guarded form could not detect a failing save.
  const options = modelSelect.locator('option')
  expect(await options.count(), '模型目錄至少需要兩個模型才能測換模型').toBeGreaterThan(1)
  const secondValue = await options.nth(1).getAttribute('value')
  expect(secondValue).toBeTruthy()
  await modelSelect.selectOption(secondValue!)

  await expect(advisorModelLabel).toBeVisible()
  await expect(advisorModelLabel).not.toHaveText(initialLabel ?? '')
  await expect(page.getByTestId('assignment-update-error')).toHaveCount(0)
})

// ── chatroom binary attachments (backlog #96) ────────────────────────────────
// The ＋ button lives in the composer; the always-mounted file input accepts
// uploads directly. Binary files upload immediately; .txt/.md prefill the
// sidebar panel's case-file form.

test('binary attachment uploads immediately and renders as an image bubble with lightbox', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom attachment ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // A fresh meeting has neither evidence nor attachments, so the ＋ button shows no count.
  await expect(page.getByTestId('chatroom-attachment-button')).not.toContainText('（')

  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
    'base64',
  )
  await page.getByTestId('attachment-upload-input').setInputFiles({
    name: '現場照片.png',
    mimeType: 'image/png',
    buffer: png,
  })

  // The bubble appears in the feed once the upload completes (immediate upload, no text).
  const bubble = page.getByTestId('attachment-image')
  await expect(bubble).toBeVisible({ timeout: 15_000 })

  // The ＋ count now totals binary attachments (1) plus active case-files (0).
  await expect(page.getByTestId('context-tab-materials')).toContainText('（1）')

  // Clicking the thumbnail opens a full-size lightbox.
  await bubble.click()
  const lightbox = page.getByTestId('attachment-lightbox')
  await expect(lightbox).toBeVisible()
  await page.getByTestId('attachment-lightbox-close').click()
  await expect(lightbox).not.toBeVisible()
})

test('pdf attachment renders as a download card with the file_id download endpoint', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom pdf ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  await page.getByTestId('attachment-upload-input').setInputFiles({
    name: '報告.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 fake pdf content'),
  })

  await expect(page.getByTestId('attachment-filename')).toHaveText('報告.pdf', { timeout: 15_000 })
  const card = page.locator('[data-testid^="attachment-download-"]').first()
  await expect(card).toBeVisible()
  await expect
    .poll(() =>
      card.evaluate((element) => {
        const styles = getComputedStyle(element)
        const icon = element.querySelector('.attachment-card-icon')
        return {
          backgroundColor: styles.backgroundColor,
          borderColor: styles.borderColor,
          iconBackgroundColor: icon ? getComputedStyle(icon).backgroundColor : '',
          iconColor: icon ? getComputedStyle(icon).color : '',
        }
      }),
    )
    .toEqual({
      backgroundColor: 'rgb(23, 28, 39)',
      borderColor: 'rgb(35, 43, 56)',
      iconBackgroundColor: 'rgb(26, 32, 41)',
      iconColor: 'rgb(154, 165, 181)',
    })
  const href = await card.getAttribute('href')
  expect(href).toMatch(/\/meetings\/[^/]+\/attachments\/attachment-[a-f0-9]+$/)
  await expect(card).toHaveAttribute('download', '')

  // Downloading through the card hits the backend's file_id download endpoint.
  const response = await page.request.get(href!)
  expect(response.status()).toBe(200)
  expect(await response.body()).toEqual(Buffer.from('%PDF-1.4 fake pdf content'))
})

test('generic binary upload (zip) renders a download card with size and file_id endpoint', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom zip ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  const zipBytes = Buffer.from('PK\x03\x04 fake zip bytes for the generic card')
  await page.getByTestId('attachment-upload-input').setInputFiles({
    name: '素材包.zip',
    mimeType: 'application/zip',
    buffer: zipBytes,
  })

  await expect(page.getByTestId('attachment-filename')).toHaveText('素材包.zip', { timeout: 15_000 })
  await expect(page.getByTestId('attachment-size')).toHaveText(`${zipBytes.length} B`)
  const card = page.locator('[data-testid^="attachment-download-"]').first()
  await expect(card).toBeVisible()
  const href = await card.getAttribute('href')
  expect(href).toMatch(/\/meetings\/[^/]+\/attachments\/attachment-[a-f0-9]+$/)
  await expect(card).toHaveAttribute('download', '')

  // A generic (non-image, non-PDF) card still resolves through the file_id endpoint.
  const response = await page.request.get(href!)
  expect(response.status()).toBe(200)
  expect(await response.body()).toEqual(zipBytes)
})

test('the materials page lists uploaded attachments with their download links', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom attachment list ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // Upload a binary file to produce an attachment event (immediate upload, no text).
  const zipBytes = Buffer.from('PK\x03\x04 fake zip bytes for the sidebar list')
  await page.getByTestId('attachment-upload-input').setInputFiles({
    name: '素材包.zip',
    mimeType: 'application/zip',
    buffer: zipBytes,
  })
  await expect(page.getByTestId('attachment-filename')).toHaveText('素材包.zip', { timeout: 15_000 })

  // Open the sidebar materials page while it is active (the section is gated on
  // `active && attachments.length`) and assert the attachment event is listed.
  await page.getByTestId('context-tab-materials').click()
  await expect(page.getByTestId('context-tab-materials')).toHaveClass(/active/)
  await expect(page.getByTestId('materials-attachment-list')).toBeVisible()
  const row = page.getByTestId('materials-attachment-row')
  await expect(row).toHaveCount(1)
  await expect(row).toContainText('素材包.zip')

  // The row's download link points at the file_id endpoint and serves the blob.
  const download = row.locator('[data-testid^="materials-attachment-download-"]')
  await expect(download).toBeVisible()
  const href = await download.getAttribute('href')
  expect(href).toMatch(/\/meetings\/[^/]+\/attachments\/attachment-[a-f0-9]+$/)
  await expect(download).toHaveAttribute('download', '')
  const response = await page.request.get(href!)
  expect(response.status()).toBe(200)
  expect(await response.body()).toEqual(zipBytes)
})

test('the composer attachment upload is locked while the meeting runs', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom running lock ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // The mock backend settles too quickly for isMeetingRunning to stay true.
  // Directly set activity_status='running' on the Vue reactive store via
  // page.evaluate (councilKey is a Symbol, so search provides via getOwnPropertySymbols).
  // Wait for the events WebSocket's initial snapshot to be applied first: if we mutate
  // before that snapshot lands, the snapshot reassigns selectedMeeting with the real
  // backend status ('idle') and silently undoes the mutation.
  await page.waitForTimeout(500)
  const setActivityStatus = (status: 'running' | 'idle') =>
    page.evaluate((nextStatus) => {
      const el = document.querySelector('[data-testid="conversation-workspace"]')
      if (!el) return false
      const vnode = (el as any).__vueParentComponent
      if (!vnode) return false
      const provides = vnode.provides
      if (!provides) return false
      const symbols = Object.getOwnPropertySymbols(provides)
      for (const sym of symbols) {
        const candidate = provides[sym]
        if (candidate?.selectedMeeting?.value?.activity_status !== undefined) {
          candidate.selectedMeeting.value = {
            ...candidate.selectedMeeting.value,
            activity_status: nextStatus,
          }
          return true
        }
      }
      return false
    }, status)

  expect(await setActivityStatus('running')).toBe(true)

  // Upload is locked while running: the ＋ button and its file input are disabled.
  await expect(page.getByTestId('chatroom-attachment-button')).toBeDisabled()
  await expect(page.getByTestId('attachment-upload-input')).toBeDisabled()

  // The upload lock must not leak into the composer itself: the input, mentions and
  // send stay usable while a meeting runs — only attachment upload is locked.
  await expect(page.getByTestId('chat-message-input')).toBeEnabled()

  // Restore normal state so the meeting is not left half-mutated.
  expect(await setActivityStatus('idle')).toBe(true)
})

test('.txt upload becomes a reader card in the feed and is ingested into case-files', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom txt ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  const textContent = '這是文字摘要內容'
  await page.getByTestId('attachment-upload-input').setInputFiles({
    name: '摘要.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from(textContent, 'utf-8'),
  })

  // Chatroom text files upload straight through the attachment boundary: no case-file
  // form prefill, and the feed shows a text card (not a binary bubble).
  await expect(page.getByTestId('case-material-form')).toHaveCount(0)
  const textCard = page.getByTestId('attachment-text')
  await expect(textCard).toBeVisible({ timeout: 15_000 })
  await expect(textCard).toContainText('摘要.txt')

  // Opening the card shows the full text in the reader modal.
  await textCard.click()
  const reader = page.getByTestId('attachment-reader')
  await expect(reader).toBeVisible()
  await expect(page.getByTestId('attachment-reader-content')).toHaveText(textContent, { timeout: 15_000 })

  // The reader carries a download link to the blob.
  const download = reader.locator('[data-testid^="attachment-download-"]')
  const href = await download.getAttribute('href')
  expect(href).toMatch(/\/meetings\/[^/]+\/attachments\/attachment-[a-f0-9]+$/)
  const response = await page.request.get(href!)
  expect(response.status()).toBe(200)
  expect(await response.text()).toEqual(textContent)

  await page.getByTestId('attachment-reader-close').click()
  await expect(reader).not.toBeVisible()

  // The text is mirrored into case-files: the sidebar shows one active evidence card
  // and the tab counts it once (the mirrored attachment event is not double-counted).
  await page.getByTestId('context-tab-materials').click()
  await expect(page.getByTestId('case-evidence-card')).toBeVisible()
  await expect(page.getByTestId('case-evidence-card')).toContainText('摘要')
  await expect(page.getByTestId('context-tab-materials')).toContainText('（1）')
})

test('uploading .txt after the AI has spoken does not gate it: no impact banner, AI keeps answering', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom post-ai txt ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // The AI has already spoken before any upload.
  await sendChatMessage(page, '@Advisor 你怎麼看？')
  await waitForRoleMessage(page, '顧問')

  // Upload a text file after that output — chatroom must not flag a pending impact.
  await page.getByTestId('attachment-upload-input').setInputFiles({
    name: '補充.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('AI 發言後補充', 'utf-8'),
  })
  await expect(page.getByTestId('attachment-text')).toBeVisible({ timeout: 15_000 })

  // The materials tab reloads server state: the evidence is mirrored in, but no
  // materials-impact-warning banner appears.
  await page.getByTestId('context-tab-materials').click()
  await expect(page.getByTestId('case-evidence-card')).toBeVisible()
  await expect(page.getByTestId('materials-impact-warning')).toHaveCount(0)

  // A follow-up @mention is accepted (202) and answered, so the AI is not gated.
  const followUp = page.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().endsWith('/chat/mention'),
  )
  await sendChatMessage(page, '@Advisor 再看一次？')
  expect((await followUp).status()).toBe(202)
  const advisorMessages = page.getByTestId('workspace-message').filter({ hasText: '顧問' })
  await expect(advisorMessages).toHaveCount(2, { timeout: 15_000 })
})

test('chatroom materials page is read-only: no notes, no add form, no version buttons', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom simple materials ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // Ingest one text file so the materials page has content to render.
  await page.getByTestId('attachment-upload-input').setInputFiles({
    name: '補充說明.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('# 補充說明', 'utf-8'),
  })
  await expect(page.getByTestId('attachment-text')).toBeVisible({ timeout: 15_000 })

  await page.getByTestId('context-tab-materials').click()
  await expect(page.getByTestId('case-evidence-card')).toBeVisible()

  // Chatroom is a simplified, read-only materials surface.
  await expect(page.getByTestId('case-material-form')).toHaveCount(0)
  await expect(page.getByTestId('case-note-card')).toHaveCount(0)
  await expect(page.getByTestId('deactivate-evidence-button')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '建立新版本' })).toHaveCount(0)
})

// ── chatroom attachment delete (backlog #96 round-7) ───────────────────────────
// 附件刪除所有模式都有；聊天串氣泡保留並標「已刪除」且不可點開（LINE 回收概念）。

test('binary attachment delete removes the sidebar row, drops the count, and turns the feed bubble into a non-clickable 已刪除 card', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom binary delete ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  const zipBytes = Buffer.from('PK\x03\x04 fake zip for the delete flow')
  await page.getByTestId('attachment-upload-input').setInputFiles({
    name: '刪除測試.zip',
    mimeType: 'application/zip',
    buffer: zipBytes,
  })
  await expect(page.getByTestId('attachment-filename')).toHaveText('刪除測試.zip', { timeout: 15_000 })
  await expect(page.getByTestId('context-tab-materials')).toContainText('（1）')

  // The sidebar lists the attachment with a delete button and a live download link.
  await page.getByTestId('context-tab-materials').click()
  await expect(page.getByTestId('context-tab-materials')).toHaveClass(/active/)
  const row = page.getByTestId('materials-attachment-row')
  await expect(row).toHaveCount(1)
  const download = row.locator('[data-testid^="materials-attachment-download-"]')
  await expect(download).toBeVisible()
  const href = await download.getAttribute('href')
  expect(href).toMatch(/\/meetings\/[^/]+\/attachments\/attachment-[a-f0-9]+$/)

  // Confirming the delete removes the row and frees the quota-counted attachment.
  await page.once('dialog', (dialog) => dialog.accept())
  await row.locator('[data-testid^="attachment-delete-"]').click()
  await expect(page.getByTestId('materials-attachment-row')).toHaveCount(0)
  await expect(page.getByTestId('context-tab-materials')).toContainText('（0）')

  // The blob is gone: the download endpoint now 404s.
  const after = await page.request.get(href!)
  expect(after.status()).toBe(404)

  // The feed bubble stays but becomes the non-clickable 已刪除 card (no reader/lightbox).
  await expect(page.getByTestId('attachment-removed')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('attachment-removed')).toContainText('刪除測試.zip')
  await expect(page.getByTestId('attachment-removed')).toContainText('已刪除')
  await expect(page.getByTestId('attachment-removed').locator('a, button')).toHaveCount(0)
  await page.getByTestId('attachment-removed').click()
  await expect(page.getByTestId('attachment-lightbox')).toHaveCount(0)
  await expect(page.getByTestId('attachment-reader')).toHaveCount(0)
})

test('cancelling the delete confirm keeps the attachment and its sidebar row', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom cancel delete ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  const zipBytes = Buffer.from('PK\x03\x04 fake zip for the cancel flow')
  await page.getByTestId('attachment-upload-input').setInputFiles({
    name: '保留.zip',
    mimeType: 'application/zip',
    buffer: zipBytes,
  })
  await expect(page.getByTestId('attachment-filename')).toHaveText('保留.zip', { timeout: 15_000 })

  await page.getByTestId('context-tab-materials').click()
  await expect(page.getByTestId('materials-attachment-row')).toHaveCount(1)

  // Dismissing the confirm leaves everything in place.
  await page.once('dialog', (dialog) => dialog.dismiss())
  await page.getByTestId('materials-attachment-row').locator('[data-testid^="attachment-delete-"]').click()
  await expect(page.getByTestId('materials-attachment-row')).toHaveCount(1)
  await expect(page.getByTestId('context-tab-materials')).toContainText('（1）')
  await expect(page.getByTestId('attachment-removed')).toHaveCount(0)
})

test('.txt delete removes the mirrored evidence card and the sidebar row, and marks the feed bubble 已刪除', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom txt delete ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  const textContent = '這是會被刪除的文字摘要'
  await page.getByTestId('attachment-upload-input').setInputFiles({
    name: '案情摘要.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from(textContent, 'utf-8'),
  })
  await expect(page.getByTestId('attachment-text')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('context-tab-materials')).toContainText('（1）')

  await page.getByTestId('context-tab-materials').click()
  await expect(page.getByTestId('case-evidence-card')).toBeVisible()
  await expect(page.getByTestId('case-evidence-card')).toContainText('案情摘要')
  await expect(page.getByTestId('materials-attachment-row')).toHaveCount(1)

  // Deleting the text attachment also removes its AI-visible evidence mirror.
  await page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId('materials-attachment-row').locator('[data-testid^="attachment-delete-"]').click()
  await expect(page.getByTestId('case-evidence-card')).toHaveCount(0)
  await expect(page.getByTestId('materials-attachment-row')).toHaveCount(0)
  await expect(page.getByTestId('context-tab-materials')).toContainText('（0）')

  // The feed keeps the bubble but marks it deleted.
  await expect(page.getByTestId('attachment-removed')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('attachment-removed')).toContainText('案情摘要.txt')
  await expect(page.getByTestId('attachment-removed')).toContainText('已刪除')
})

test('deleting an attachment after the AI has spoken shows no impact banner and the AI keeps answering', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom post-ai delete ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  // The AI has already spoken before any upload or delete.
  await sendChatMessage(page, '@Advisor 你怎麼看？')
  await waitForRoleMessage(page, '顧問')

  await page.getByTestId('attachment-upload-input').setInputFiles({
    name: '補充.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('AI 發言後上傳又刪除', 'utf-8'),
  })
  await expect(page.getByTestId('attachment-text')).toBeVisible({ timeout: 15_000 })

  await page.getByTestId('context-tab-materials').click()
  await expect(page.getByTestId('case-evidence-card')).toBeVisible()
  await expect(page.getByTestId('materials-impact-warning')).toHaveCount(0)

  // Deleting in chatroom must not set a pending impact either.
  await page.once('dialog', (dialog) => dialog.accept())
  await page.getByTestId('materials-attachment-row').locator('[data-testid^="attachment-delete-"]').click()
  await expect(page.getByTestId('materials-attachment-row')).toHaveCount(0)
  await expect(page.getByTestId('materials-impact-warning')).toHaveCount(0)

  // A follow-up @mention is accepted and answered, so the AI is not gated.
  const followUp = page.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().endsWith('/chat/mention'),
  )
  await sendChatMessage(page, '@Advisor 再看一次？')
  expect((await followUp).status()).toBe(202)
  const advisorMessages = page.getByTestId('workspace-message').filter({ hasText: '顧問' })
  await expect(advisorMessages).toHaveCount(2, { timeout: 15_000 })
})

test('chatroom evidence card header shows no 使用中/已停用 status text (simple mode)', async ({ page }) => {
  await page.goto('/')
  const title = `E2E chatroom status text ${Date.now()}`
  await createChatroomMeeting(page, title, { modelAssignments: defaultModels })

  await page.getByTestId('attachment-upload-input').setInputFiles({
    name: '狀態文字.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('# 無狀態文字', 'utf-8'),
  })
  await expect(page.getByTestId('attachment-text')).toBeVisible({ timeout: 15_000 })

  await page.getByTestId('context-tab-materials').click()
  await expect(page.getByTestId('case-evidence-card')).toBeVisible()
  await expect(page.getByTestId('case-evidence-card')).toContainText('狀態文字')
  // Chatroom has no status toggle buttons, so the inert status text must not render.
  await expect(page.getByTestId('case-evidence-card')).not.toContainText('使用中')
  await expect(page.getByTestId('case-evidence-card')).not.toContainText('已停用')
})
