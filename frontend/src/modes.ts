// Mode catalog. Primary data source is `GET /modes` (spec.md section 16.5), fetched via
// `refreshModeCatalog()` below - called once at app startup (slice B task 9 wires the
// call site). The six local consts further down (redBlueMode, courtroomMode, ...) seed
// `modeCatalog`'s initial value and double as the fallback catalog whenever the backend
// is unreachable, so behavior degrades to slice A's rather than breaking. Same schema
// (16.2) either way, so components should keep importing `modeCatalog`/`getModeById`
// from here regardless of which data source is currently live.
//
// The local fallback consts' `available` flags mirror slice A: only `red-blue` true, the
// rest false. Once the backend catalog loads, its own `available` values win instead -
// see mapBackendMode. The local copies exist so the New Case mode picker always has real
// content to browse (name/category/tagline/when-to-use/SOP) even before/without a
// successful fetch.
import { reactive } from 'vue'
import {
  getModes,
  type BackendModeDefinition,
  type BackendModeFanout,
  type BackendModeInput,
  type BackendModeRole,
  type BackendModeStep,
  type BackendModeSynthesis,
} from './api'

export type ModeCategory = 'relay' | 'parallel' | 'chatroom'

// Mirrors spec.md 16.2's `kind` enum. `member` is a participant whose output feeds the
// next step (relay) or the synthesis step (parallel); `adjudicator` is the relay's final
// decision-maker; `synthesizer` is the parallel executor's aggregation role.
export type RoleKind = 'member' | 'adjudicator' | 'synthesizer'

export type ModeRoleDefinition = {
  // The string that lands in events.jsonl's `role` field once slice B/C wire a mode up.
  id: string
  name: string
  color: string
  // Small-icon asset key (see useCouncil.ts's ROLE_ICON_ASSETS). Omitted => no hand-drawn
  // icon exists yet, so the UI falls back to a silhouette tinted with `color`.
  portrait?: string
  kind: RoleKind
}

// A relay step's `label` is what the UI actually shows (step-progress indicator, help
// drawer SOP-adjacent copy). `template` documents the prompts/ file the step will use
// once slice B implements it - it's reference metadata only, never parsed to drive
// runtime behavior here (the real, currently-shipped runner keyed off of backend
// `step_id`s stays entirely in useCouncil.ts, untouched by this catalog).
export type RelayStep = {
  role: string
  label: string
  template: string
}

// Parallel mode whose member roster is a fixed, fully-named set (e.g. six-hats' five
// hats) needs nothing beyond `roles` - every member already has its own identity. A
// parallel mode whose members are interchangeable copies of one persona slot (brainstorm,
// persona-testing) instead carries a `fanout` describing that prototype + how many
// instances (2-6, user-chosen at creation) to spin up as `{role.id}-1`..`{role.id}-N`.
export type FanoutConfig = {
  role: string
  label: string
  template: string
  minInstances: number
  maxInstances: number
  // Whether each spun-up instance may carry its own extra persona/angle prompt text
  // (brainstorm's "每委員可選自訂視角", persona-testing's persona description).
  instancePrompt: boolean
}

export type SynthesisConfig = {
  role: string
  label: string
  template: string
}

export type ModeInputField =
  | { id: 'position_a' | 'position_b'; label: string; kind: 'text' }
  | { id: 'personas'; label: string; kind: 'persona-list' }

export type ModeDefinition = {
  id: string
  name: string
  category: ModeCategory
  tagline: string
  whenToUse: string
  sop: string[]
  defaultScene: string
  inputs: ModeInputField[]
  // Catalog-time-known roster: for `relay`, every step's role; for a fixed-roster
  // `parallel` mode (six-hats), every hat + the synthesizer; for a prototype+N `parallel`
  // mode (brainstorm/persona-testing), just the synthesizer - the instantiable member
  // lives in `fanout` instead, since its count isn't known until meeting creation.
  roles: ModeRoleDefinition[]
  steps?: RelayStep[]
  fanout?: FanoutConfig
  synthesis?: SynthesisConfig
  // Sourced from the backend catalog (GET /modes - see refreshModeCatalog/mapBackendMode
  // below) once it loads. The local fallback consts further down intentionally stay
  // conservative for whenever the backend is unreachable.
  available: boolean
}

const ADJUDICATOR_COLOR = '#e8b44c'
const SYNTHESIZER_COLOR = '#8b6dd9'

export const redBlueMode: ModeDefinition = {
  id: 'red-blue',
  name: '紅藍對抗',
  category: 'relay',
  tagline: '藍軍提案、紅軍質詢、裁判定案 —— 最扎實的方案壓力測試。',
  whenToUse: '需要對單一方案做深度攻防、揪出被忽略的風險與反例時使用。',
  sop: [
    '輸入要被驗證的方案主題',
    '為藍軍/紅軍/裁判挑選模型',
    '開始審議，觀察紅軍指出的缺陷',
    '對裁決不滿可追問或開新回合',
  ],
  defaultScene: 'meeting-room',
  inputs: [],
  roles: [
    { id: 'Blue', name: '藍軍', color: '#4d8dff', portrait: 'blue', kind: 'member' },
    { id: 'Red', name: '紅軍', color: '#ff6b5e', portrait: 'red', kind: 'member' },
    { id: 'Judge', name: '裁判', color: ADJUDICATOR_COLOR, portrait: 'judge', kind: 'adjudicator' },
  ],
  steps: [
    { role: 'Blue', label: '藍軍提案', template: 'blue_propose' },
    { role: 'Red', label: '紅軍質詢', template: 'red_critique' },
    { role: 'Blue', label: '藍軍修訂', template: 'blue_revise' },
    { role: 'Judge', label: '裁判裁決', template: 'judge_decide' },
  ],
  available: true,
}

export const courtroomMode: ModeDefinition = {
  id: 'courtroom',
  name: '法庭審理',
  category: 'relay',
  tagline: '像一場真實庭審一樣，逐條指控、逐條辯護，逼近事故或架構決策的真相。',
  whenToUse: '適合災難覆盤、複雜架構除錯 —— 把「被審理的事故/設計」當被告，交互詰問到水落石出。',
  sop: [
    '輸入要被審理的事故或架構決策',
    '為檢察官/辯護律師/法官挑選模型',
    '開始審理，依序觀察指控、辯護、再質詢',
    '參考法官判決；對判決不滿可追問或開新回合',
  ],
  defaultScene: 'courtroom',
  inputs: [],
  roles: [
    { id: 'Prosecutor', name: '檢察官', color: '#ff6b5e', kind: 'member' },
    { id: 'Defense', name: '辯護律師', color: '#4d8dff', kind: 'member' },
    { id: 'Judge', name: '法官', color: ADJUDICATOR_COLOR, kind: 'adjudicator' },
  ],
  steps: [
    { role: 'Prosecutor', label: '檢察官指控', template: 'courtroom_charge' },
    { role: 'Defense', label: '辯護律師答辯', template: 'courtroom_defense' },
    { role: 'Prosecutor', label: '檢察官再質詢', template: 'courtroom_rebuttal' },
    { role: 'Judge', label: '法官判決', template: 'courtroom_verdict' },
  ],
  available: false,
}

export const debateMode: ModeDefinition = {
  id: 'debate',
  name: '辯論',
  category: 'relay',
  tagline: '正反雙方各自申論、交叉質詢，仲裁人裁定哪條路線更站得住腳。',
  whenToUse: '適合在兩條明確對立的路線（position A vs. B）間做決策時使用。',
  sop: [
    '輸入正方/反方各自的立場',
    '為正方/反方/仲裁人挑選模型',
    '開始辯論，依序觀察申論與交叉質詢',
    '參考仲裁人裁決；對裁決不滿可追問或開新回合',
  ],
  defaultScene: 'meeting-room',
  inputs: [
    { id: 'position_a', label: '正方立場', kind: 'text' },
    { id: 'position_b', label: '反方立場', kind: 'text' },
  ],
  roles: [
    { id: 'Pro', name: '正方', color: '#4d8dff', kind: 'member' },
    { id: 'Con', name: '反方', color: '#ff6b5e', kind: 'member' },
    { id: 'Arbiter', name: '仲裁人', color: ADJUDICATOR_COLOR, kind: 'adjudicator' },
  ],
  steps: [
    { role: 'Pro', label: '正方申論', template: 'debate_statement_pro' },
    { role: 'Con', label: '反方申論', template: 'debate_statement_con' },
    { role: 'Pro', label: '正方質詢', template: 'debate_cross_pro' },
    { role: 'Con', label: '反方質詢', template: 'debate_cross_con' },
    { role: 'Arbiter', label: '仲裁人裁決', template: 'debate_verdict' },
  ],
  available: false,
}

export const brainstormMode: ModeDefinition = {
  id: 'brainstorm',
  name: '腦力激盪',
  category: 'parallel',
  tagline: '多位委員同時發散思考，主持人彙整出共識、分歧與結論。',
  whenToUse: '適合早期發散、廣度優先探索多種可能性的場合，而非驗證單一方案。',
  sop: [
    '輸入要腦力激盪的主題',
    '決定委員人數（2–6 位），可為每位委員指定自訂視角',
    '為所有委員與主持人挑選模型',
    '開始討論，等待全部委員完成後觸發彙整',
  ],
  defaultScene: 'meeting-room',
  inputs: [],
  roles: [{ id: 'Moderator', name: '主持人', color: SYNTHESIZER_COLOR, kind: 'synthesizer' }],
  fanout: {
    role: 'Member',
    label: '委員發想',
    template: 'brainstorm_member',
    minInstances: 2,
    maxInstances: 6,
    instancePrompt: true,
  },
  synthesis: { role: 'Moderator', label: '主持人彙整', template: 'brainstorm_synthesis' },
  available: false,
}

export const sixHatsMode: ModeDefinition = {
  id: 'six-hats',
  name: '六頂思考帽',
  category: 'parallel',
  tagline: '白/紅/黑/黃/綠五頂帽子各司其職同時發言，藍帽統整成一份完整報告。',
  whenToUse: '適合需要系統性覆蓋事實、直覺、風險、樂觀、創意五種視角，不遺漏任何一面時使用。',
  sop: [
    '輸入要討論的主題',
    '為五頂帽子與藍帽統整挑選模型',
    '開始討論：白/紅/黑/黃/綠帽同時發言',
    '等待五頂帽子完成後，查看藍帽統整報告',
  ],
  defaultScene: 'meeting-room',
  inputs: [],
  roles: [
    { id: 'HatWhite', name: '白帽（事實數據）', color: '#e8e8ec', kind: 'member' },
    { id: 'HatRed', name: '紅帽（直覺感受）', color: '#ff6b5e', kind: 'member' },
    { id: 'HatBlack', name: '黑帽（風險批判）', color: '#8a8f9c', kind: 'member' },
    { id: 'HatYellow', name: '黃帽（價值樂觀）', color: '#f0c05a', kind: 'member' },
    { id: 'HatGreen', name: '綠帽（創意發想）', color: '#3dd68c', kind: 'member' },
    { id: 'HatBlue', name: '藍帽（流程統整）', color: '#4d8dff', kind: 'synthesizer' },
  ],
  available: false,
}

export const personaTestingMode: ModeDefinition = {
  id: 'persona-testing',
  name: '盲測用戶',
  category: 'parallel',
  tagline: '一群使用者輪番對產品/方案做出真實反應，產品顧問彙整成一份可行動的報告。',
  whenToUse: '適合在正式上線或投放前，快速蒐集不同用戶輪廓對方案的第一反應。',
  sop: [
    '輸入要盲測的產品或方案描述',
    '定義每個 persona 的名稱與描述（2–6 位）',
    '為所有 persona 與產品顧問挑選模型',
    '開始測試，等待全部 persona 反應完成後查看彙整報告',
  ],
  defaultScene: 'meeting-room',
  inputs: [{ id: 'personas', label: 'Persona 清單（名稱＋描述）', kind: 'persona-list' }],
  roles: [{ id: 'ProductAdvisor', name: '產品顧問', color: SYNTHESIZER_COLOR, kind: 'synthesizer' }],
  fanout: {
    role: 'Persona',
    label: 'Persona 反應',
    template: 'persona_member',
    minInstances: 2,
    maxInstances: 6,
    instancePrompt: true,
  },
  synthesis: { role: 'ProductAdvisor', label: '產品顧問彙整', template: 'persona_synthesis' },
  available: false,
}

// `reactive` (not a plain array) so `refreshModeCatalog`'s in-place splice below is
// visible to every component's `v-for`/`.find()` over `modeCatalog` without them
// re-importing anything - same array identity, new contents.
export const modeCatalog = reactive<ModeDefinition[]>([
  redBlueMode,
  courtroomMode,
  debateMode,
  brainstormMode,
  sixHatsMode,
  personaTestingMode,
])

function mapBackendRole(role: BackendModeRole): ModeRoleDefinition {
  return {
    id: role.id,
    name: role.name,
    color: role.color,
    portrait: role.portrait ?? undefined,
    // Backend already validated `kind` against VALID_ROLE_KINDS (modes.py) when it
    // parsed config/modes.yaml, so it's already one of RoleKind's members here.
    kind: role.kind as RoleKind,
  }
}

function mapBackendStep(step: BackendModeStep): RelayStep {
  return { role: step.role, label: step.label, template: step.template }
}

function mapBackendInput(input: BackendModeInput): ModeInputField {
  // Backend already validated `id`/`kind` against the yaml schema; the frontend's
  // ModeInputField discriminated union doesn't need to re-verify that overlap here.
  return { id: input.id, label: input.label, kind: input.kind } as ModeInputField
}

function mapBackendFanout(fanout: BackendModeFanout): FanoutConfig {
  return {
    role: fanout.role,
    label: fanout.label,
    template: fanout.template,
    minInstances: fanout.min_instances,
    maxInstances: fanout.max_instances,
    instancePrompt: fanout.instance_prompt,
  }
}

function mapBackendSynthesis(synthesis: BackendModeSynthesis): SynthesisConfig {
  return { role: synthesis.role, label: synthesis.label, template: synthesis.template }
}

// snake_case (backend/spec.md 16.2) -> camelCase (this module's existing ModeDefinition
// shape). `steps`/`fanout`/`synthesis` are optional both sides - the backend omits the
// key entirely for a mode that doesn't have it, so this only sets them when present
// rather than writing `undefined` over top.
export function mapBackendMode(raw: BackendModeDefinition): ModeDefinition {
  const mode: ModeDefinition = {
    id: raw.id,
    name: raw.name,
    // Backend already validated `category` against VALID_CATEGORIES (modes.py) when it
    // parsed config/modes.yaml, so it's already one of ModeCategory's members here.
    category: raw.category as ModeCategory,
    tagline: raw.tagline,
    whenToUse: raw.when_to_use,
    sop: raw.sop,
    defaultScene: raw.default_scene,
    inputs: raw.inputs.map(mapBackendInput),
    roles: raw.roles.map(mapBackendRole),
    available: raw.available,
  }
  if (raw.steps) mode.steps = raw.steps.map(mapBackendStep)
  if (raw.fanout) mode.fanout = mapBackendFanout(raw.fanout)
  if (raw.synthesis) mode.synthesis = mapBackendSynthesis(raw.synthesis)
  return mode
}

// Swaps `modeCatalog`'s contents for the live backend catalog, in place (so existing
// references stay valid - see the `reactive` note above). Falls back to whatever
// `modeCatalog` already holds (the local consts, on first call) if the backend is
// unreachable or returns nothing, so a failed fetch degrades to slice A's behavior
// instead of leaving the picker empty.
export async function refreshModeCatalog(): Promise<void> {
  try {
    const fetched = await getModes()
    if (fetched.length) modeCatalog.splice(0, modeCatalog.length, ...fetched.map(mapBackendMode))
  } catch (error) {
    console.warn('GET /modes failed; using local mode catalog fallback', error)
  }
}

export const DEFAULT_MODE_ID = 'red-blue'

export function getModeById(id: string): ModeDefinition | undefined {
  return modeCatalog.find((mode) => mode.id === id)
}

// Pure, side-effect-free point layout for a `ring[]` seat group (spec.md 16.6): N seats
// evenly spaced along an arc, for parallel modes' N concurrent members.
export function ringSeatLayout(
  count: number,
  options: { centerX?: number; topY?: number; bottomY?: number; radiusX?: number } = {},
): Array<{ x: number; y: number }> {
  if (count <= 0) return []
  const centerX = options.centerX ?? 50
  const topY = options.topY ?? 30
  const bottomY = options.bottomY ?? 78
  const radiusX = options.radiusX ?? 38
  if (count === 1) return [{ x: centerX, y: bottomY }]
  const seats: Array<{ x: number; y: number }> = []
  for (let index = 0; index < count; index += 1) {
    // Spread evenly across a half-turn (0..PI) so the arc sweeps left-to-right across
    // the front of the stage rather than wrapping all the way around behind the camera.
    const t = index / (count - 1)
    const angle = Math.PI * t
    const x = centerX - Math.cos(angle) * radiusX
    const y = bottomY - Math.sin(angle) * (bottomY - topY)
    seats.push({ x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 })
  }
  return seats
}
