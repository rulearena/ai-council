import { expect, test } from '@playwright/test'

test('user can run a mock meeting and add chair feedback', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByTestId('meeting-list')).toBeVisible()
  await expect(page.getByTestId('blue-model-select')).toBeVisible()
  await expect(page.getByTestId('red-model-select')).toBeVisible()
  await expect(page.getByTestId('judge-model-select')).toBeVisible()

  await page.getByLabel('會議主題').fill(`E2E mock meeting ${Date.now()}`)
  await page.getByTestId('create-meeting-button').click()

  await expect(page.getByTestId('transcript-preview')).toContainText('No transcript yet')
  await expect(page.getByTestId('step-timeline')).toContainText('open')

  await page.getByTestId('blue-model-select').selectOption('mock-fast')
  await page.getByTestId('red-model-select').selectOption('mock-fast')
  await page.getByTestId('judge-model-select').selectOption('mock-fast')
  await page.getByTestId('test-blue-model-button').click()
  await expect(page.getByTestId('model-test-status')).toContainText('Blue: available')
  await page.getByTestId('start-meeting-button').click()

  await expect(page.getByTestId('step-timeline')).toContainText('blue-propose')
  await expect(page.getByTestId('step-timeline')).toContainText('red-critique')
  await expect(page.getByTestId('step-timeline')).toContainText('blue-revise')
  await expect(page.getByTestId('step-timeline')).toContainText('judge-decide')
  await expect(page.getByTestId('debug-panel')).toContainText('"status": "completed"')
  await expect(page.getByTestId('transcript-preview')).toContainText('## Blue - blue-propose')
  await expect(page.getByTestId('transcript-preview')).toContainText('## Judge - judge-decide')

  await expect(page.getByTestId('start-meeting-button')).toContainText('繼續討論')

  await page.getByTestId('chair-message-input').fill('主席補充：請先限制在一週可以完成的方案。')
  await page.getByTestId('send-chair-message-button').click()

  await expect(page.getByTestId('step-timeline')).toContainText('human-message')
  await expect(page.getByTestId('debug-panel')).toContainText('"role": "Human"')
  await expect(page.getByTestId('transcript-preview')).toContainText(
    '主席補充：請先限制在一週可以完成的方案。',
  )
  await expect(page.getByTestId('chair-message-input')).toHaveValue('')

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

  await expect(page.getByTestId('step-timeline')).toContainText('closed')
  await expect(page.getByTestId('meeting-list')).toContainText('closed')
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
})
