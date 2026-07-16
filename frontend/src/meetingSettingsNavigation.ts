export type MeetingSettingsNavigationState = {
  dirty: () => boolean
  saving: () => boolean
  discard: () => void
}

let state: MeetingSettingsNavigationState | null = null

export function registerMeetingSettingsNavigationState(next: MeetingSettingsNavigationState | null) {
  state = next
}

export function canLeaveMeetingSettings(): boolean {
  if (!state) return true
  if (state.saving()) {
    window.alert('會議設定正在儲存，請等待完成後再離開。')
    return false
  }
  if (!state.dirty()) return true
  if (!window.confirm('尚有未儲存的會議設定，確定放棄變更？')) return false
  state.discard()
  return true
}
