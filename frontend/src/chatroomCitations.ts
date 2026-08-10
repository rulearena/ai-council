import type { ChatroomSource } from './api'

export type ChatroomCitation = {
  source_ref: string
  label: string
  segment_refs: string[]
}

export function resolveChatroomCitation(
  citation: ChatroomCitation,
  sources: ChatroomSource[],
): { label: string; reader_ref: string; available: boolean } {
  const source = sources.find((candidate) => candidate.source_ref === citation.source_ref)
  return {
    label: citation.label,
    reader_ref: source?.reader_ref ?? citation.source_ref,
    available: Boolean(source?.active && source?.readable),
  }
}
