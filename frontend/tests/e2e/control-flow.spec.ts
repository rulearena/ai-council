import { expect, test } from '@playwright/test'

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

  await expect(page.getByTestId('operation-status')).toContainText('狀態：running')
  await expect(page.getByTestId('start-meeting-button')).toContainText('執行中...')
  await expect(page.getByTestId('step-timeline')).toContainText('blue-propose')
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

  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('無法復原')
    await dialog.accept()
  })
  const meetingRow = page.getByTestId('meeting-list-item').filter({ hasText: topic })
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
