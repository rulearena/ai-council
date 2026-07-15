import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildMeetingSettingsPayload,
  hydrateMeetingSettingsDraft,
  isMeetingSettingsDirty,
  nextHistorySelection,
  validateMeetingSettingsDraft,
} from '../../src/meetingWorkspace.ts'

const meeting = {
  meeting_id: 'meeting-a',
  title: '土地糾紛案',
  goal: '被告是否應返還土地？',
  settings_revision: 3,
  scene: 'courtroom',
  mode_id: 'courtroom',
  case_type: 'civil' as const,
  courtroom: { status: 'confirmed' },
  participants: [
    { role_id: 'Prosecutor', model_config_id: 'model-a' },
    { role_id: 'Defense', model_config_id: 'model-b' },
    { role_id: 'Judge', model_config_id: 'model-c' },
  ],
}

test('meeting settings draft hydrates one meeting and emits one complete atomic payload', () => {
  const draft = hydrateMeetingSettingsDraft(meeting)
  draft.title = '土地返還案'
  draft.participantModels.Judge = 'model-d'

  assert.equal(isMeetingSettingsDirty(draft, meeting), true)
  assert.deepEqual(buildMeetingSettingsPayload(draft), {
    expected_revision: 3,
    title: '土地返還案',
    goal: '被告是否應返還土地？',
    case_type: 'civil',
    scene: 'courtroom',
    participant_models: {
      Prosecutor: 'model-a',
      Defense: 'model-b',
      Judge: 'model-d',
    },
  })
})

test('confirmed courtroom settings explain locked goal and case type', () => {
  const draft = hydrateMeetingSettingsDraft(meeting)
  draft.goal = ''
  draft.caseType = 'criminal'

  assert.deepEqual(validateMeetingSettingsDraft(draft, meeting), {
    title: '',
    goal: '爭點已確認，AI 目標只能檢視；重新整理爭點後才可修改。',
    caseType: '爭點已確認，案件類型只能檢視；重新整理爭點後才可修改。',
    participantModels: '',
  })
})

test('history selection stays local and resets when switching meetings', () => {
  assert.equal(nextHistorySelection('meeting-a', 'meeting-a', 'epoch-1', 'epoch-2'), 'epoch-1')
  assert.equal(nextHistorySelection('meeting-a', 'meeting-b', 'epoch-1', 'epoch-4'), 'epoch-4')
})
