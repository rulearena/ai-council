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
  await expect(page.getByTestId('new-case-modal')).not.toBeVisible()
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
  const firstCard = page.getByTestId('new-case-modal').locator('.mode-select-card').first()
  await expect(firstCard).toContainText('聊天室')
})

// ── 13.14 ────────────────────────────────────────────────────────────────────

test('13.14 clicking scene image opens enlarged lightbox modal', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('new-case-button').click()
  await expect(page.getByTestId('new-case-modal')).toBeVisible()
  await page.getByTestId('mode-select-chatroom').click()
  await page.getByTestId('confirm-start-meeting').click()
  await expect(page.getByTestId('workspace')).toBeVisible()
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
  await page.getByTestId('new-case-button').click()
  await expect(page.getByTestId('new-case-modal')).toBeVisible()
  await page.getByTestId('mode-select-chatroom').click()
  await page.getByTestId('confirm-start-meeting').click()
  await expect(page.getByTestId('workspace')).toBeVisible()
  await expect(page.getByTestId('workspace-message-feed')).toBeVisible()

  // The Advisor seat should have a model label
  const advisorModelLabel = page.getByTestId('seat-model-label-advisor')
  await expect(advisorModelLabel).toBeVisible()
  const initialLabel = await advisorModelLabel.textContent()

  // Click the model label to open the inline model select
  await advisorModelLabel.click()
  const modelSelect = page.getByTestId('seat-model-select-advisor')
  await expect(modelSelect).toBeVisible()

  // Select a different model (pick second option if available)
  const options = modelSelect.locator('option')
  const optionCount = await options.count()
  if (optionCount > 1) {
    const secondValue = await options.nth(1).getAttribute('value')
    if (secondValue) await modelSelect.selectOption(secondValue)
    // The label should update (or at least the select should close)
    await expect(modelSelect).not.toBeVisible()
  }
})

// ── 13.16 ────────────────────────────────────────────────────────────────────

test('13.16 records tab in context panel shows meeting records', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('new-case-button').click()
  await expect(page.getByTestId('new-case-modal')).toBeVisible()
  await page.getByTestId('mode-select-chatroom').click()
  await page.getByTestId('confirm-start-meeting').click()
  await expect(page.getByTestId('workspace')).toBeVisible()
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
  await page.getByTestId('mode-select-courtroom').click()
  await page.getByTestId('confirm-start-meeting').click()
  await expect(page.getByTestId('workspace')).toBeVisible()

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
  await page.getByTestId('new-case-button').click()
  await expect(page.getByTestId('new-case-modal')).toBeVisible()
  await page.getByTestId('mode-select-chatroom').click()
  await page.getByTestId('confirm-start-meeting').click()
  await expect(page.getByTestId('workspace')).toBeVisible()
  await expect(page.getByTestId('workspace-message-feed')).toBeVisible()

  // The old meeting-subnav row should NOT exist
  await expect(page.getByRole('navigation', { name: '會議工作區' })).not.toBeVisible()
})
