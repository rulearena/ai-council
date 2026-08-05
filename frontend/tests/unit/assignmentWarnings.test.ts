import assert from 'node:assert/strict'
import test from 'node:test'

import { projectAssignmentWarnings } from '../../src/assignmentWarnings.ts'

const roles = [
  { roleId: 'Advisor', name: '顧問' },
  { roleId: 'Critic', name: '評論者' },
]

const models = [
  {
    id: 'openai-gpt-4o',
    adapter: 'openai-compatible-http',
    base_url: 'https://api.openai.com/v1',
    model: 'gpt-4o',
    api_key_env: 'OPENAI_API_KEY',
    supports_json_mode: true,
    extra_body: {},
    pricing: null,
    command: null,
    timeout_seconds: 30,
    status: 'available' as const,
    health_checked_at: null,
    health_error: null,
  },
]

test('assignment warning projection filters, localizes, labels, and preserves order', () => {
  const warnings = projectAssignmentWarnings({
    participants: [
      { role_id: 'Ignored', model_assignment_warning: null },
      { role_id: 'Advisor', model_assignment_warning: 'No models are configured for this meeting.' },
      { role_id: 'Critic', model_assignment_warning: "No saved model assignment; using default model 'openai-gpt-4o'." },
      { role_id: 'Unknown', model_assignment_warning: "No saved model assignment; using default model 'missing-model'." },
      { role_id: 'Advisor', model_assignment_warning: "Assigned model 'old-model' is unavailable; using default model 'openai-gpt-4o'." },
      { role_id: 'Critic', model_assignment_warning: "Recovered model 'old-model' is unavailable; using default model 'openai-gpt-4o'." },
      { role_id: 'Unknown', model_assignment_warning: 'A backend warning that has no known projection.' },
    ],
    roles,
    models,
  })

  assert.deepEqual(warnings, [
    '顧問：模型登錄表目前沒有可用模型。',
    '評論者：未指派模型，已自動使用「OpenAI · gpt-4o」。',
    'Unknown：未指派模型，已自動使用「missing-model」。',
    '顧問：模型「old-model」已失效，目前使用「OpenAI · gpt-4o」。',
    '評論者：模型「old-model」已失效，目前使用「OpenAI · gpt-4o」。',
    'Unknown：A backend warning that has no known projection.',
  ])
})

test('assignment warning projection falls back to the participant role id', () => {
  assert.deepEqual(projectAssignmentWarnings({
    participants: [{ role_id: 'UnlistedRole', model_assignment_warning: 'unrecognized warning' }],
    roles,
    models: [],
  }), ['UnlistedRole：unrecognized warning'])
})
