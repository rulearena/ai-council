import type { ChatroomSource, ChatSourceToken } from './api'

export function detectSourceTrigger(text: string, selectionStart = text.length): { triggered: boolean; filterText: string; start: number } {
  const prefix = text.slice(0, selectionStart)
  const start = prefix.lastIndexOf('#')
  if (start < 0) return { triggered: false, filterText: '', start: -1 }
  const before = prefix[start - 1]
  if (before && !/[\s\n]/u.test(before)) return { triggered: false, filterText: '', start: -1 }
  const filterText = prefix.slice(start + 1)
  if (/\s/u.test(filterText)) return { triggered: false, filterText: '', start: -1 }
  return { triggered: true, filterText, start }
}

export function filterSourceOptions(
  sources: ChatroomSource[],
  filterText: string,
): ChatroomSource[] {
  const needle = filterText.toLocaleLowerCase()
  return sources.filter((source) => (
    source.active && source.readable && source.label.toLocaleLowerCase().includes(needle)
  ))
}

export function sourceOptionMetadata(source: ChatroomSource): string {
  const kind = source.kind === 'attachment' ? '附件' : '證據'
  const size = source.size === undefined ? '' : ` · ${source.size} bytes`
  const date = source.created_at ? ` · ${source.created_at}` : ''
  return `${kind}${size}${date}`
}

export function insertSourceToken(
  content: string,
  selectionStart: number,
  source: ChatroomSource,
  tokenId: string,
): { content: string; token: ChatSourceToken } {
  const trigger = detectSourceTrigger(content, selectionStart)
  const start = trigger.start < 0 ? selectionStart : trigger.start
  const displayText = `#${source.label}`
  const suffix = content.slice(selectionStart)
  const separator = suffix.startsWith(' ') || suffix.startsWith('\n') ? '' : ' '
  const nextContent = `${content.slice(0, start)}${displayText}${separator}${suffix}`
  const tokenStart = Array.from(content.slice(0, start)).length
  return {
    content: nextContent,
    token: {
      token_id: tokenId,
      source_ref: source.source_ref,
      display_text: displayText,
      start: tokenStart,
      end: tokenStart + Array.from(displayText).length,
    },
  }
}

export function orderedUniqueSourceRefs(tokens: ChatSourceToken[]): string[] {
  return [...new Set(tokens.map((token) => token.source_ref))]
}
