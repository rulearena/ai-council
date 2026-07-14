import type { ModelConfigPayload, ModelPricing } from './api'

export type ProviderId =
  | 'openai'
  | 'anthropic'
  | 'gemini'
  | 'custom-openai-compatible'
  | 'subscription-cli'
  | 'mock'

export type ProviderDiscovery = 'openai-compatible' | 'provider-specific' | 'manual-only'

export type ProviderDefinition = {
  id: ProviderId
  name: string
  adapter: string
  defaultBaseUrl: string | null
  defaultApiKeyEnv: string | null
  discovery: ProviderDiscovery
}

export const PROVIDERS: readonly ProviderDefinition[] = [
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
]

export type ProviderModelProjection = {
  id?: string
  adapter: string
  base_url: string | null
  model?: string | null
  command?: readonly string[] | null
  extra_body?: Record<string, unknown> | null
}

export type ProviderModelDraft = {
  base_url?: string | null
  model?: string | null
  api_key_env?: string | null
  supports_json_mode?: boolean
  extra_body?: Record<string, unknown>
  pricing?: ModelPricing | null
  command?: string[] | null
  timeout_seconds?: number
}

export type CliPresetId = 'claude' | 'codex' | 'agy' | 'custom'
export type CliModelMode = 'default' | 'exact'

export type CliPresetDefinition = {
  id: CliPresetId
  name: string
  defaultCommand: readonly string[] | null
  exact: {
    build: (exactModelId: string) => string[]
    parse: (command: readonly string[]) => string | null
  } | null
}

export type CliConfigProjection = {
  presetId: CliPresetId
  modelMode: CliModelMode
  exactModelId: string
  command: string[]
  extraBody: Record<string, unknown>
}

export type CliConfigOptions = {
  modelMode?: CliModelMode
  exactModelId?: string
  preserveProviderMarker?: boolean
}

export const CLI_PRESETS: readonly CliPresetDefinition[] = [
  {
    id: 'claude',
    name: 'Claude CLI',
    defaultCommand: ['claude', '-p', '{prompt}'],
    exact: {
      build: (exactModelId) => ['claude', '--model', exactModelId, '-p', '{prompt}'],
      parse: (command) => command.length === 5
        && command[0] === 'claude'
        && command[1] === '--model'
        && Boolean(command[2]?.trim())
        && command[3] === '-p'
        && command[4] === '{prompt}'
          ? command[2]
          : null,
    },
  },
  {
    id: 'codex',
    name: 'Codex CLI',
    defaultCommand: ['codex', 'exec', '{prompt}'],
    exact: {
      build: (exactModelId) => ['codex', 'exec', '--model', exactModelId, '{prompt}'],
      parse: (command) => command.length === 5
        && command[0] === 'codex'
        && command[1] === 'exec'
        && command[2] === '--model'
        && Boolean(command[3]?.trim())
        && command[4] === '{prompt}'
          ? command[3]
          : null,
    },
  },
  {
    id: 'agy',
    name: 'AGY',
    defaultCommand: ['agy', '-p', '{prompt}'],
    exact: {
      build: (exactModelId) => ['agy', '--model', exactModelId, '-p', '{prompt}'],
      parse: (command) => command.length === 5
        && command[0] === 'agy'
        && command[1] === '--model'
        && Boolean(command[2]?.trim())
        && command[3] === '-p'
        && command[4] === '{prompt}'
          ? command[2]
          : null,
    },
  },
  { id: 'custom', name: 'Custom CLI', defaultCommand: null, exact: null },
]

const PROVIDER_BY_ID = new Map(PROVIDERS.map((provider) => [provider.id, provider]))
const CLI_PRESET_BY_ID = new Map(CLI_PRESETS.map((preset) => [preset.id, preset]))
const OPENAI_BASE_URL = 'https://api.openai.com/v1'

export function cliConfigPayload(
  presetId: CliPresetId,
  customCommand: readonly string[] = [],
  extraBody: Record<string, unknown> = {},
  options: CliConfigOptions = {},
): Pick<ModelConfigPayload, 'command' | 'extra_body'> {
  const preset = CLI_PRESET_BY_ID.get(presetId)!
  if (preset.id === 'custom') {
    return { command: [...customCommand], extra_body: { ...extraBody } }
  }
  let command = [...preset.defaultCommand!]
  if (options.modelMode === 'exact') {
    const exactModelId = options.exactModelId?.trim() ?? ''
    if (!exactModelId) throw new Error('exact model ID is required')
    command = preset.exact!.build(exactModelId)
  }
  const projectedExtraBody = { ...extraBody }
  if (!options.preserveProviderMarker) projectedExtraBody.cli_provider = preset.id
  return {
    command,
    extra_body: projectedExtraBody,
  }
}

export function projectCliConfig(model: {
  command?: readonly string[] | null
  extra_body?: Record<string, unknown> | null
}): CliConfigProjection {
  const command = [...(model.command ?? [])]
  const extraBody = { ...(model.extra_body ?? {}) }
  const defaultPreset = CLI_PRESETS.find((candidate) =>
    candidate.id !== 'custom' && arraysEqual(candidate.defaultCommand!, command))
  const exactProjection = defaultPreset ? null : projectExactCliCommand(command)
  return {
    presetId: defaultPreset?.id ?? exactProjection?.presetId ?? 'custom',
    modelMode: exactProjection ? 'exact' : 'default',
    exactModelId: exactProjection?.exactModelId ?? '',
    command,
    extraBody,
  }
}

export function getProvider(providerId: ProviderId): ProviderDefinition {
  return PROVIDER_BY_ID.get(providerId)!
}

export function providerIdForModel(model: ProviderModelProjection): ProviderId | null {
  if (model.adapter === 'openai-compatible-http') {
    return normalizeBaseUrl(model.base_url) === OPENAI_BASE_URL
      ? 'openai'
      : 'custom-openai-compatible'
  }
  if (model.adapter === 'anthropic-http') return 'anthropic'
  if (model.adapter === 'gemini-http') return 'gemini'
  if (model.adapter === 'subscription-cli') return 'subscription-cli'
  if (model.adapter === 'mock') return 'mock'
  return null
}

export function modelConfigPayloadForProvider(
  providerId: ProviderId,
  draft: ProviderModelDraft = {},
): ModelConfigPayload {
  const provider = getProvider(providerId)
  const common = {
    adapter: provider.adapter,
    extra_body: draft.extra_body ?? {},
    pricing: draft.pricing ?? null,
    timeout_seconds: draft.timeout_seconds ?? 120,
  }

  if (provider.adapter === 'openai-compatible-http'
    || provider.adapter === 'anthropic-http'
    || provider.adapter === 'gemini-http') {
    return {
      ...common,
      base_url: draft.base_url === undefined
        ? provider.defaultBaseUrl
        : trimNullable(draft.base_url),
      model: trimNullable(draft.model),
      api_key_env: draft.api_key_env === undefined
        ? provider.defaultApiKeyEnv
        : trimNullable(draft.api_key_env),
      supports_json_mode: draft.supports_json_mode ?? false,
    }
  }

  if (provider.adapter === 'subscription-cli') {
    return {
      ...common,
      command: draft.command ? [...draft.command] : null,
    }
  }

  return common
}

export function modelDisplayLabel(model: ProviderModelProjection & { id: string }): string {
  const providerId = providerIdForModel(model)
  if (providerId === 'subscription-cli' && trimNullable(model.model) === null) {
    const cliProjection = projectCliConfig(model)
    if (cliProjection.modelMode === 'exact' && cliProjection.presetId !== 'custom') {
      const preset = CLI_PRESET_BY_ID.get(cliProjection.presetId)!
      return `Subscription CLI · ${preset.name} · ${cliProjection.exactModelId}`
    }
    return `Subscription CLI · 由 command 決定（${model.id}）`
  }
  const exactModelId = trimNullable(model.model) ?? model.id
  if (providerId === null) return exactModelId
  return `${getProvider(providerId).name} · ${exactModelId}`
}

function normalizeBaseUrl(value: string | null | undefined): string | null {
  const trimmed = trimNullable(value)
  return trimmed?.replace(/\/+$/, '') ?? null
}

function trimNullable(value: string | null | undefined): string | null {
  if (value == null) return null
  return value.trim() || null
}

function arraysEqual(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index])
}

function projectExactCliCommand(command: readonly string[]): {
  presetId: Exclude<CliPresetId, 'custom'>
  exactModelId: string
} | null {
  for (const preset of CLI_PRESETS) {
    if (preset.id === 'custom') continue
    const exactModelId = preset.exact!.parse(command)
    if (exactModelId !== null) return { presetId: preset.id, exactModelId }
  }
  return null
}
