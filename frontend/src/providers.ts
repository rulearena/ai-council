import type { ModelConfigPayload, ModelPricing } from './api'

export type ProviderId =
  | 'openai'
  | 'anthropic'
  | 'gemini'
  | 'custom-openai-compatible'
  | 'subscription-cli'
  | 'mock'

export type ProviderDiscovery = 'openai-compatible' | 'manual-only'

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
    discovery: 'manual-only',
  },
  {
    id: 'gemini',
    name: 'Gemini',
    adapter: 'gemini-http',
    defaultBaseUrl: 'https://generativelanguage.googleapis.com/v1beta',
    defaultApiKeyEnv: 'GEMINI_API_KEY',
    discovery: 'manual-only',
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

const PROVIDER_BY_ID = new Map(PROVIDERS.map((provider) => [provider.id, provider]))
const OPENAI_BASE_URL = 'https://api.openai.com/v1'

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
