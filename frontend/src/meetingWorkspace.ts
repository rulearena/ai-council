export type MeetingSettingsSource = {
  meeting_id: string
  title: string
  goal: string | null
  settings_revision: number
  scene: string
  mode_id: string
  case_type?: 'civil' | 'criminal' | null
  courtroom?: { status: string } | null
  participants: Array<{ role_id: string; model_config_id: string | null }>
}

export type MeetingSettingsDraft = {
  meetingId: string
  expectedRevision: number
  title: string
  goal: string
  caseType: 'civil' | 'criminal' | null
  scene: string
  participantModels: Record<string, string>
}

export type MeetingSettingsErrors = {
  title: string
  goal: string
  caseType: string
  participantModels: string
}

export function hydrateMeetingSettingsDraft(meeting: MeetingSettingsSource): MeetingSettingsDraft {
  return {
    meetingId: meeting.meeting_id,
    expectedRevision: meeting.settings_revision,
    title: meeting.title,
    goal: meeting.goal ?? '',
    caseType: meeting.mode_id === 'courtroom' ? meeting.case_type ?? null : null,
    scene: meeting.scene,
    participantModels: Object.fromEntries(
      meeting.participants.map((participant) => [
        participant.role_id,
        participant.model_config_id ?? '',
      ]),
    ),
  }
}

export function buildMeetingSettingsPayload(draft: MeetingSettingsDraft) {
  return {
    expected_revision: draft.expectedRevision,
    title: draft.title.trim(),
    goal: draft.goal.trim(),
    case_type: draft.caseType,
    scene: draft.scene,
    participant_models: { ...draft.participantModels },
  }
}

export function isMeetingSettingsDirty(
  draft: MeetingSettingsDraft,
  meeting: MeetingSettingsSource,
): boolean {
  return JSON.stringify(buildMeetingSettingsPayload(draft)) !== JSON.stringify(
    buildMeetingSettingsPayload(hydrateMeetingSettingsDraft(meeting)),
  )
}

export function validateMeetingSettingsDraft(
  draft: MeetingSettingsDraft,
  meeting: MeetingSettingsSource,
): MeetingSettingsErrors {
  const confirmedCourtroom = meeting.mode_id === 'courtroom' && meeting.courtroom?.status === 'confirmed'
  return {
    title: draft.title.trim() ? '' : '請輸入會議名稱。',
    goal: confirmedCourtroom && draft.goal !== (meeting.goal ?? '')
      ? '爭點已確認，AI 目標只能檢視；重新整理爭點後才可修改。'
      : draft.goal.trim() ? '' : '請輸入 AI 最終目標。',
    caseType: confirmedCourtroom && draft.caseType !== meeting.case_type
      ? '爭點已確認，案件類型只能檢視；重新整理爭點後才可修改。'
      : meeting.mode_id === 'courtroom' && !draft.caseType ? '請選擇民事或刑事。' : '',
    participantModels: Object.values(draft.participantModels).every(Boolean)
      ? ''
      : '請為每個角色選擇模型。',
  }
}

export function nextHistorySelection(
  previousMeetingId: string | null,
  nextMeetingId: string | null,
  selectedEpochId: string,
  activeEpochId: string,
): string {
  return previousMeetingId === nextMeetingId ? selectedEpochId : activeEpochId
}
