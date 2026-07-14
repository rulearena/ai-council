import assert from 'node:assert/strict'
import test from 'node:test'

import {
  CLI_PRESETS,
  PROVIDERS,
  cliConfigPayload,
  projectCliConfig,
  modelConfigPayloadForProvider,
  modelDisplayLabel,
  providerIdForModel,
} from '../../src/providers.ts'

test('subscription CLI presets generate safe default argv without user-authored command parts', () => {
  assert.deepEqual(
    CLI_PRESETS.map(({ id, name }) => ({ id, name })),
    [
      { id: 'claude', name: 'Claude CLI' },
      { id: 'codex', name: 'Codex CLI' },
      { id: 'agy', name: 'AGY' },
      { id: 'custom', name: 'Custom CLI' },
    ],
  )
  assert.deepEqual(cliConfigPayload('claude'), {
    command: ['claude', '-p', '{prompt}'],
    extra_body: { cli_provider: 'claude' },
  })
  assert.deepEqual(cliConfigPayload('codex'), {
    command: ['codex', 'exec', '{prompt}'],
    extra_body: { cli_provider: 'codex' },
  })
  assert.deepEqual(cliConfigPayload('agy'), {
    command: ['agy', '-p', '{prompt}'],
    extra_body: { cli_provider: 'agy' },
  })
})

test('subscription CLI presets generate and project advanced exact model argv', () => {
  // Canonical argv literals are the Human Owner-approved backlog #85 / PRD contract.
  // They intentionally remain independent expected values rather than being derived from CLI_PRESETS.
  assert.deepEqual(
    cliConfigPayload('claude', [], {}, { modelMode: 'exact', exactModelId: ' claude-opus-x ' }),
    {
      command: ['claude', '--model', 'claude-opus-x', '-p', '{prompt}'],
      extra_body: { cli_provider: 'claude' },
    },
  )
  assert.deepEqual(
    cliConfigPayload('codex', [], {}, { modelMode: 'exact', exactModelId: 'gpt-x' }),
    {
      command: ['codex', 'exec', '--model', 'gpt-x', '{prompt}'],
      extra_body: { cli_provider: 'codex' },
    },
  )
  assert.deepEqual(
    cliConfigPayload('agy', [], {}, { modelMode: 'exact', exactModelId: 'agy-x' }),
    {
      command: ['agy', '--model', 'agy-x', '-p', '{prompt}'],
      extra_body: { cli_provider: 'agy' },
    },
  )
  assert.throws(
    () => cliConfigPayload('claude', [], {}, { modelMode: 'exact', exactModelId: '  ' }),
    /exact model ID is required/,
  )
  assert.deepEqual(
    projectCliConfig({
      command: ['claude', '--model', 'claude-opus-x', '-p', '{prompt}'],
      extra_body: {},
    }),
    {
      presetId: 'claude',
      modelMode: 'exact',
      exactModelId: 'claude-opus-x',
      command: ['claude', '--model', 'claude-opus-x', '-p', '{prompt}'],
      extraBody: {},
    },
  )
  assert.deepEqual(
    projectCliConfig({
      command: ['codex', 'exec', '--model', 'gpt-x', '{prompt}'],
      extra_body: { cli_provider: 'codex' },
    }),
    {
      presetId: 'codex',
      modelMode: 'exact',
      exactModelId: 'gpt-x',
      command: ['codex', 'exec', '--model', 'gpt-x', '{prompt}'],
      extraBody: { cli_provider: 'codex' },
    },
  )
  assert.deepEqual(
    projectCliConfig({
      command: ['agy', '--model', 'agy-x', '-p', '{prompt}'],
      extra_body: { cli_provider: 'agy' },
    }),
    {
      presetId: 'agy',
      modelMode: 'exact',
      exactModelId: 'agy-x',
      command: ['agy', '--model', 'agy-x', '-p', '{prompt}'],
      extraBody: { cli_provider: 'agy' },
    },
  )
})

test('saving an unchanged recognized legacy preset preserves provider marker absence or value', () => {
  const withoutMarker = projectCliConfig({ command: ['claude', '-p', '{prompt}'], extra_body: {} })
  assert.deepEqual(
    cliConfigPayload(
      withoutMarker.presetId,
      withoutMarker.command,
      withoutMarker.extraBody,
      {
        modelMode: withoutMarker.modelMode,
        exactModelId: withoutMarker.exactModelId,
        preserveProviderMarker: true,
      },
    ),
    { command: ['claude', '-p', '{prompt}'], extra_body: {} },
  )

  const existingExtraBody = { cli_provider: 'codex', profile: 'work' }
  assert.deepEqual(
    cliConfigPayload('codex', [], existingExtraBody, { preserveProviderMarker: true }),
    {
      command: ['codex', 'exec', '{prompt}'],
      extra_body: existingExtraBody,
    },
  )
})

test('subscription CLI projection recognizes presets and preserves unknown legacy commands as custom', () => {
  assert.deepEqual(
    projectCliConfig({
      command: ['codex', 'exec', '{prompt}'],
      extra_body: { cli_provider: 'codex', profile: 'work' },
    }),
    {
      presetId: 'codex',
      modelMode: 'default',
      exactModelId: '',
      command: ['codex', 'exec', '{prompt}'],
      extraBody: { cli_provider: 'codex', profile: 'work' },
    },
  )

  const legacy = {
    command: ['company-wrapper', '--stdin', '{prompt}'],
    extra_body: { cli_provider: 'company-internal', keep: true },
  }
  const projected = projectCliConfig(legacy)
  assert.deepEqual(projected, {
    presetId: 'custom',
    modelMode: 'default',
    exactModelId: '',
    command: ['company-wrapper', '--stdin', '{prompt}'],
    extraBody: { cli_provider: 'company-internal', keep: true },
  })
  assert.deepEqual(
    cliConfigPayload(projected.presetId, projected.command, projected.extraBody),
    {
      command: ['company-wrapper', '--stdin', '{prompt}'],
      extra_body: { cli_provider: 'company-internal', keep: true },
    },
  )
})

test('provider catalog exposes product concepts and transport presets', () => {
  assert.deepEqual(
    PROVIDERS.map(({ id, name, adapter, defaultBaseUrl, defaultApiKeyEnv, discovery }) => ({
      id,
      name,
      adapter,
      defaultBaseUrl,
      defaultApiKeyEnv,
      discovery,
    })),
    [
      {
        id: 'openai',
        name: 'OpenAI',
        adapter: 'openai-compatible-http',
        defaultBaseUrl: 'https://api.openai.com/v1',
        defaultApiKeyEnv: 'OPENAI_API_KEY',
        discovery: 'openai-compatible',
      },
      {
        id: 'anthropic',
        name: 'Anthropic',
        adapter: 'anthropic-http',
        defaultBaseUrl: 'https://api.anthropic.com/v1',
        defaultApiKeyEnv: 'ANTHROPIC_API_KEY',
        discovery: 'provider-specific',
      },
      {
        id: 'gemini',
        name: 'Gemini',
        adapter: 'gemini-http',
        defaultBaseUrl: 'https://generativelanguage.googleapis.com/v1beta',
        defaultApiKeyEnv: 'GEMINI_API_KEY',
        discovery: 'provider-specific',
      },
      {
        id: 'custom-openai-compatible',
        name: 'Custom OpenAI-compatible',
        adapter: 'openai-compatible-http',
        defaultBaseUrl: null,
        defaultApiKeyEnv: null,
        discovery: 'openai-compatible',
      },
      {
        id: 'subscription-cli',
        name: 'Subscription CLI',
        adapter: 'subscription-cli',
        defaultBaseUrl: null,
        defaultApiKeyEnv: null,
        discovery: 'manual-only',
      },
      {
        id: 'mock',
        name: 'Mock',
        adapter: 'mock',
        defaultBaseUrl: null,
        defaultApiKeyEnv: null,
        discovery: 'manual-only',
      },
    ],
  )
})

test('legacy model configs project deterministically to providers', () => {
  assert.equal(
    providerIdForModel({ adapter: 'openai-compatible-http', base_url: 'https://api.openai.com/v1/' }),
    'openai',
  )
  assert.equal(
    providerIdForModel({ adapter: 'openai-compatible-http', base_url: 'http://localhost:1234/v1' }),
    'custom-openai-compatible',
  )
  assert.equal(providerIdForModel({ adapter: 'anthropic-http', base_url: 'https://proxy.test/v1' }), 'anthropic')
  assert.equal(providerIdForModel({ adapter: 'gemini-http', base_url: null }), 'gemini')
  assert.equal(providerIdForModel({ adapter: 'subscription-cli', base_url: null }), 'subscription-cli')
  assert.equal(providerIdForModel({ adapter: 'mock', base_url: null }), 'mock')
  assert.equal(providerIdForModel({ adapter: 'unknown', base_url: null }), null)
})

test('provider payload mapping applies presets and removes incompatible fields', () => {
  assert.deepEqual(
    modelConfigPayloadForProvider('openai', {
      model: 'gpt-5.4',
      supports_json_mode: true,
      command: ['must-not-survive'],
    }),
    {
      adapter: 'openai-compatible-http',
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-5.4',
      api_key_env: 'OPENAI_API_KEY',
      supports_json_mode: true,
      extra_body: {},
      pricing: null,
      timeout_seconds: 120,
    },
  )
  assert.deepEqual(
    modelConfigPayloadForProvider('custom-openai-compatible', {
      base_url: ' http://localhost:1234/v1/ ',
      model: ' local-model ',
      api_key_env: ' LOCAL_KEY ',
    }),
    {
      adapter: 'openai-compatible-http',
      base_url: 'http://localhost:1234/v1/',
      model: 'local-model',
      api_key_env: 'LOCAL_KEY',
      supports_json_mode: false,
      extra_body: {},
      pricing: null,
      timeout_seconds: 120,
    },
  )
  assert.deepEqual(
    modelConfigPayloadForProvider('subscription-cli', {
      base_url: 'must-not-survive',
      model: 'must-not-survive',
      command: ['claude', '-p', '{prompt}'],
      timeout_seconds: 300,
    }),
    {
      adapter: 'subscription-cli',
      command: ['claude', '-p', '{prompt}'],
      extra_body: {},
      pricing: null,
      timeout_seconds: 300,
    },
  )
})

test('provider payload mapping preserves explicit legacy proxy settings', () => {
  assert.deepEqual(
    modelConfigPayloadForProvider('anthropic', {
      base_url: ' https://anthropic-proxy.example.test/v1 ',
      model: 'claude-proxy-model',
      api_key_env: null,
    }),
    {
      adapter: 'anthropic-http',
      base_url: 'https://anthropic-proxy.example.test/v1',
      model: 'claude-proxy-model',
      api_key_env: null,
      supports_json_mode: false,
      extra_body: {},
      pricing: null,
      timeout_seconds: 120,
    },
  )
})

test('model labels use provider and exact model id without exposing adapters', () => {
  assert.equal(
    modelDisplayLabel({
      id: 'primary',
      adapter: 'openai-compatible-http',
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-5.4',
    }),
    'OpenAI · gpt-5.4',
  )
  assert.equal(
    modelDisplayLabel({ id: 'claude-subscription', adapter: 'subscription-cli', base_url: null, model: null }),
    'Subscription CLI · 由 command 決定（claude-subscription）',
  )
  assert.equal(
    modelDisplayLabel({
      id: 'claude-exact',
      adapter: 'subscription-cli',
      base_url: null,
      model: null,
      command: ['claude', '--model', 'claude-opus-4-1', '-p', '{prompt}'],
      extra_body: { cli_provider: 'claude' },
    }),
    'Subscription CLI · Claude CLI · claude-opus-4-1',
  )
  assert.equal(
    modelDisplayLabel({
      id: 'legacy-subscription',
      adapter: 'subscription-cli',
      base_url: null,
      model: null,
      command: ['company-wrapper', '--stdin', '{prompt}'],
      extra_body: {},
    }),
    'Subscription CLI · 由 command 決定（legacy-subscription）',
  )
  assert.equal(
    modelDisplayLabel({ id: 'mock-fast', adapter: 'mock', base_url: null, model: null }),
    'Mock · mock-fast',
  )
})
