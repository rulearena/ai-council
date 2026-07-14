export type MeetingMigrationDraft = {
  title: string
  goal: string
}

export type MeetingMigrationKey = {
  meetingId: string | null | undefined
  requiresGoal: boolean | undefined
}

export type MeetingMigrationSource = MeetingMigrationKey & {
  title: string
  goal: string | null
}

export function nextMeetingMigrationDraft(
  current: MeetingMigrationDraft,
  previous: MeetingMigrationKey,
  next: MeetingMigrationSource | null,
): MeetingMigrationDraft {
  if (next === null) return { title: '', goal: '' }
  if (previous.meetingId !== next.meetingId) {
    return { title: next.title, goal: next.goal ?? '' }
  }
  if (previous.requiresGoal && !next.requiresGoal) {
    return { title: '', goal: '' }
  }
  return current
}
