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
  const legacyCaseTypeMissing = confirmedCourtroom && !meeting.case_type
  return {
    title: draft.title.trim() ? '' : '請輸入會議名稱。',
    goal: confirmedCourtroom && draft.goal !== (meeting.goal ?? '')
      ? '爭點已確認，AI 目標只能檢視；重新整理爭點後才可修改。'
      : draft.goal.trim() ? '' : '請輸入 AI 最終目標。',
    caseType: confirmedCourtroom && !legacyCaseTypeMissing && draft.caseType !== meeting.case_type
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

export function materialImpactGuidance(modeId: string): string {
  return modeId === 'courtroom'
    ? '為避免新舊證據混用，目前已暫停 AI 與法官判斷。請到「流程操作」選擇重開目前爭點、重開全部審議或重新整理爭點。'
    : '為避免新舊資料混用，目前已暫停 AI。請到「流程操作」輸入原因並重開全部審議。'
}
