import type { ChairmanParticipant } from '../chairmanActions'

export type MentionOption = {
  role_id: string
  display_name?: string | null
  name?: string | null
}

export type TriggerDetection =
  | { triggered: false }
  | { triggered: true; filterText: string }

export function shouldShowMentionAutocomplete(modeCategory: string): boolean {
  return modeCategory === 'chatroom'
}

export function detectMentionTrigger(text: string): TriggerDetection {
  const lastAt = text.lastIndexOf('@')
  if (lastAt < 0) return { triggered: false }

  const charBefore = lastAt === 0 ? null : text[lastAt - 1]
  if (charBefore !== null && charBefore !== ' ' && charBefore !== '\t' && charBefore !== '\n') {
    return { triggered: false }
  }

  const afterAt = text.slice(lastAt + 1)
  if (/\s/.test(afterAt)) return { triggered: false }

  return { triggered: true, filterText: afterAt }
}

const ALL_OPTION: MentionOption = { role_id: 'all', display_name: '全體成員', name: null }

function matchesFilter(option: MentionOption, filterText: string): boolean {
  if (!filterText) return true
  if (option.role_id === 'all') return true
  const needle = filterText.toLowerCase()
  const haystack = `${option.display_name || ''} ${option.name || ''} ${option.role_id}`.toLowerCase()
  return haystack.includes(needle)
}

export function filterMentionOptions(
  participants: ChairmanParticipant[],
  filterText: string,
): MentionOption[] {
  const options: MentionOption[] = [ALL_OPTION, ...participants]
  return options.filter((option) => matchesFilter(option, filterText))
}

export function buildMentionMenuItems(
  participants: ChairmanParticipant[],
  filterText: string,
): MentionOption[] {
  return filterMentionOptions(participants, filterText)
}

export function selectMentionOption(
  fullText: string,
  selected: MentionOption,
): { text: string; selectionStart: number } {
  const lastAt = fullText.lastIndexOf('@')
  if (lastAt < 0) return { text: fullText + `@${selected.role_id} `, selectionStart: fullText.length + selected.role_id.length + 2 }

  const before = fullText.slice(0, lastAt)
  const insertion = `@${selected.role_id} `
  const newText = before + insertion
  return { text: newText, selectionStart: newText.length }
}

export type InsertionAction =
  | { action: 'dismiss'; open: false; text?: undefined; selectedOption?: undefined; newActiveIndex?: undefined }
  | { action: 'select'; open: false; text: undefined; selectedOption: MentionOption; newActiveIndex?: undefined }
  | { action: 'navigate'; open: true; text: undefined; selectedOption?: undefined; newActiveIndex: number }

export function resolveMentionInsertion(
  state: { open: boolean; filterText: string; activeIndex: number },
  key: 'escape' | 'enter' | 'tab' | 'arrow-down' | 'arrow-up',
  menuItems?: MentionOption[],
): InsertionAction {
  if (key === 'escape') {
    return { action: 'dismiss', open: false }
  }

  if (key === 'arrow-down' && menuItems && menuItems.length > 0) {
    return { action: 'navigate', open: true, text: undefined, newActiveIndex: (state.activeIndex + 1) % menuItems.length }
  }

  if (key === 'arrow-up' && menuItems && menuItems.length > 0) {
    return {
      action: 'navigate',
      open: true,
      text: undefined,
      newActiveIndex: (state.activeIndex - 1 + menuItems.length) % menuItems.length,
    }
  }

  if ((key === 'enter' || key === 'tab') && menuItems && menuItems.length > 0) {
    const selected = menuItems[state.activeIndex % menuItems.length]
    return { action: 'select', open: false, text: undefined, selectedOption: selected }
  }

  return { action: 'dismiss', open: false }
}
