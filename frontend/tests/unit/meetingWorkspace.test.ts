import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildMeetingSettingsPayload,
  hydrateMeetingSettingsDraft,
  isMeetingSettingsDirty,
  latestWorkspaceMessageTarget,
  materialImpactGuidance,
  messageClampPolicy,
  nextHistorySelection,
  nextWorkspaceRoleFilter,
  projectMeetingWorkspace,
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
  })
})

test('legacy confirmed courtroom can fill its missing case type through atomic meeting settings', () => {
  const legacyMeeting = { ...meeting, case_type: null }
  const draft = hydrateMeetingSettingsDraft(legacyMeeting)
  draft.caseType = 'civil'

  assert.deepEqual(validateMeetingSettingsDraft(draft, legacyMeeting), {
    title: '',
    goal: '',
    caseType: '',
  })
})

test('history selection stays local and resets when switching meetings', () => {
  assert.equal(nextHistorySelection('meeting-a', 'meeting-a', 'epoch-1', 'epoch-2'), 'epoch-1')
  assert.equal(nextHistorySelection('meeting-a', 'meeting-b', 'epoch-1', 'epoch-4'), 'epoch-4')
})

test('material impact guidance only offers restart scopes available to the meeting mode', () => {
  assert.equal(
    materialImpactGuidance('red-blue'),
    '為避免新舊資料混用，目前已暫停 AI。請到「流程操作」輸入原因並重開全部審議。',
  )
  assert.equal(
    materialImpactGuidance('courtroom'),
    '為避免新舊證據混用，目前已暫停 AI 與法官判斷。請到「流程操作」選擇重開目前爭點、重開全部審議或重新整理爭點。',
  )
})

const brainstormMode = {
  id: 'brainstorm',
  category: 'parallel',
  roles: [{ id: 'Moderator', name: '主持人' }],
  fanout: { role: 'Member', label: '委員發想' },
  synthesis: { role: 'Moderator', label: '主持人彙整' },
}

const brainstormMeeting = {
  meeting_id: 'meeting-parallel',
  mode_id: 'brainstorm',
  activity_status: 'running' as const,
  participants: [
    { role_id: 'Member-1', display_name: '委員 1' },
    { role_id: 'Member-2', display_name: '委員 2' },
    { role_id: 'Member-3', display_name: '委員 3' },
    { role_id: 'Moderator', display_name: '主持人' },
  ],
  courtroom: null,
  events: [
    {
      event_id: 'human-1', meeting_id: 'meeting-parallel', step_id: 'human-message',
      role: 'Human', attempt: 1, status: 'completed', content: '請分析方案',
    },
    {
      event_id: 'member-3', meeting_id: 'meeting-parallel', step_id: 'fanout-1-member-3',
      base_step_id: 'member-3', round: 1, role: 'Member-3', attempt: 1,
      status: 'completed', parsed_output: { summary: '第三位先完成', arguments: [], risks: [], recommendation: '採用' },
    },
    {
      event_id: 'member-1', meeting_id: 'meeting-parallel', step_id: 'fanout-1-member-1',
      base_step_id: 'member-1', round: 1, role: 'Member-1', attempt: 1,
      status: 'completed', parsed_output: { summary: '第一位後完成', arguments: [], risks: [], recommendation: '保留' },
    },
    {
      event_id: 'member-2-failed', meeting_id: 'meeting-parallel', step_id: 'fanout-1-member-2',
      base_step_id: 'member-2', round: 1, role: 'Member-2', attempt: 1,
      status: 'failed', error: '連線失敗', failure_kind: 'adapter_error' as const,
    },
  ],
}

test('conversation projection preserves saved arrival order and exposes parallel progress', () => {
  const workspace = projectMeetingWorkspace({
    meeting: brainstormMeeting,
    mode: brainstormMode,
  })

  assert.equal(workspace.family, 'conversation')
  assert.deepEqual(workspace.messages.map((message) => [message.id, message.kind]), [
    ['human-1', 'human'],
    ['member-3', 'ai'],
    ['member-1', 'ai'],
    ['member-2-failed', 'failed'],
  ])
  assert.deepEqual(workspace.parallel, {
    completed: 2,
    total: 3,
    synthesis: 'blocked',
  })
  assert.deepEqual(
    workspace.roles.map((role) => [role.roleId, role.state]),
    [
      ['Member-1', 'completed'],
      ['Member-2', 'failed'],
      ['Member-3', 'completed'],
      ['Moderator', 'waiting'],
    ],
  )
})

test('parallel running projection derives incomplete members from the round after reload', () => {
  const workspace = projectMeetingWorkspace({
    meeting: brainstormMeeting,
    mode: brainstormMode,
    thinkingRoleIds: [],
  })

  assert.equal(workspace.family, 'conversation')
  assert.deepEqual(
    workspace.roles.map((role) => [role.roleId, role.state]),
    [
      ['Member-1', 'completed'],
      ['Member-2', 'failed'],
      ['Member-3', 'completed'],
      ['Moderator', 'waiting'],
    ],
  )

  const partial = projectMeetingWorkspace({
    meeting: {
      ...brainstormMeeting,
      events: brainstormMeeting.events.filter((event) => event.role !== 'Member-3'),
    },
    mode: brainstormMode,
    thinkingRoleIds: [],
  })
  assert.equal(partial.family, 'conversation')
  assert.deepEqual(
    partial.roles.map((role) => [role.roleId, role.state]),
    [
      ['Member-1', 'completed'],
      ['Member-2', 'failed'],
      ['Member-3', 'thinking'],
      ['Moderator', 'waiting'],
    ],
  )

  const retry = projectMeetingWorkspace({
    meeting: brainstormMeeting,
    mode: brainstormMode,
    thinkingRoleIds: ['Member-2'],
  })
  assert.equal(retry.family, 'conversation')
  assert.equal(retry.roles.find((role) => role.roleId === 'Member-2')?.state, 'thinking')
})

test('parallel synthesis role becomes thinking only after every member completes', () => {
  const workspace = projectMeetingWorkspace({
    mode: brainstormMode,
    meeting: {
      ...brainstormMeeting,
      events: [
        ...brainstormMeeting.events.slice(0, 3),
        {
          event_id: 'member-2', meeting_id: 'meeting-parallel', step_id: 'fanout-1-member-2',
          base_step_id: 'member-2', round: 1, role: 'Member-2', attempt: 2,
          status: 'completed', parsed_output: { summary: '重試完成', arguments: [], risks: [], recommendation: '採用' },
        },
      ],
    },
    thinkingRoleIds: [],
  })

  assert.equal(workspace.family, 'conversation')
  assert.deepEqual(workspace.roles.map((role) => role.state), [
    'completed', 'completed', 'completed', 'thinking',
  ])
})

test('relay queue projects only its first role as thinking and overrides stale failures', () => {
  const workspace = projectMeetingWorkspace({
    mode: {
      id: 'red-blue', category: 'relay',
      roles: [
        { id: 'Blue', name: '藍軍', kind: 'member' },
        { id: 'Red', name: '紅軍', kind: 'member' },
        { id: 'Judge', name: '裁判', kind: 'adjudicator' },
      ],
      steps: [
        { role: 'Blue', label: '藍軍提案', template: 'blue_propose' },
        { role: 'Red', label: '紅軍質疑', template: 'red_critique' },
      ],
    },
    meeting: {
      meeting_id: 'meeting-relay', mode_id: 'red-blue', activity_status: 'running',
      courtroom: null,
      participants: [
        { role_id: 'Blue' }, { role_id: 'Red' }, { role_id: 'Judge' },
      ],
      events: [
        {
          event_id: 'blue-old-failure', meeting_id: 'meeting-relay', step_id: 'blue-propose',
          role: 'Blue', attempt: 1, status: 'failed', error: '舊失敗',
        },
        {
          event_id: 'red-old-complete', meeting_id: 'meeting-relay', step_id: 'red-critique',
          role: 'Red', attempt: 1, status: 'completed', content: '舊回應',
        },
      ],
    },
    thinkingRoleIds: ['Blue', 'Red', 'Blue', 'Judge'],
  })

  assert.equal(workspace.family, 'conversation')
  assert.deepEqual(workspace.roles.map((role) => role.state), [
    'thinking', 'waiting', 'waiting',
  ])
})

test('conversation messages format every structured role-output field without exposing raw JSON', () => {
  const workspace = projectMeetingWorkspace({
    meeting: {
      ...brainstormMeeting,
      events: [{
        event_id: 'structured', meeting_id: 'meeting-parallel', step_id: 'fanout-1-member-1',
        role: 'Member-1', attempt: 1, status: 'completed',
        parsed_output: {
          summary: '先做小規模驗證',
          arguments: [{ title: '成本', detail: '可降低首次投入' }],
          risks: [{ title: '樣本偏差', detail: '需涵蓋不同使用者' }],
          recommendation: '兩週後檢視成效',
        },
        raw_output: '{"summary":"不應直接顯示的原始 JSON"}',
      }],
    },
    mode: brainstormMode,
  })

  assert.equal(workspace.family, 'conversation')
  assert.equal(workspace.messages[0]?.content, [
    '摘要',
    '先做小規模驗證',
    '',
    '論點',
    '成本：可降低首次投入',
    '',
    '風險',
    '樣本偏差：需涵蓋不同使用者',
    '',
    '建議處置',
    '兩週後檢視成效',
  ].join('\n'))
  assert.equal(workspace.messages[0]?.content.includes('原始 JSON'), false)
})

test('workspace role filters find the latest saved message and reset on meeting switch', () => {
  const workspace = projectMeetingWorkspace({ meeting: brainstormMeeting, mode: brainstormMode })
  const selected = nextWorkspaceRoleFilter(null, 'meeting-parallel', 'Member-3')

  assert.deepEqual(selected, { meetingId: 'meeting-parallel', roleId: 'Member-3' })
  assert.equal(latestWorkspaceMessageTarget(workspace, selected), 'member-3')
  assert.equal(
    nextWorkspaceRoleFilter(selected, 'meeting-other', undefined),
    null,
  )
  assert.equal(latestWorkspaceMessageTarget(workspace, {
    meetingId: 'meeting-other',
    roleId: 'Member-3',
  }), null)
})

test('workspace role filter accepts Chairman as a filterable seat id and toggles off on re-click', () => {
  const filter = nextWorkspaceRoleFilter(null, 'meeting-a', 'Chairman')
  assert.deepEqual(filter, { meetingId: 'meeting-a', roleId: 'Chairman' })
  // Re-clicking the same seat clears the filter (toggle)
  const cleared = nextWorkspaceRoleFilter(filter, 'meeting-a', 'Chairman')
  assert.equal(cleared, null)
})

test('long message clamp policy is deterministic and keeps short messages open', () => {
  assert.deepEqual(messageClampPolicy('短回應'), {
    collapsible: false,
    collapsedByDefault: false,
    lineClamp: 3,
  })
  assert.deepEqual(messageClampPolicy('a'.repeat(241)), {
    collapsible: true,
    collapsedByDefault: true,
    lineClamp: 3,
  })
  assert.equal(messageClampPolicy('1\n2\n3\n4').collapsible, true)
})

test('completed synthesis is a final distinct message after every parallel member', () => {
  const workspace = projectMeetingWorkspace({
    mode: brainstormMode,
    meeting: {
      ...brainstormMeeting,
      activity_status: 'completed',
      events: [
        ...brainstormMeeting.events.slice(0, 3),
        {
          event_id: 'member-2', meeting_id: 'meeting-parallel', step_id: 'fanout-1-member-2',
          base_step_id: 'member-2', round: 1, role: 'Member-2', attempt: 2,
          status: 'completed', parsed_output: { summary: '重試完成', arguments: [], risks: [], recommendation: '採用' },
        },
        {
          event_id: 'synthesis', meeting_id: 'meeting-parallel', step_id: 'synthesis-1',
          round: 1, role: 'Moderator', attempt: 1, status: 'completed',
          parsed_output: { summary: '最終彙整', arguments: [], risks: [], recommendation: '執行' },
        },
      ],
    },
  })

  assert.equal(workspace.family, 'conversation')
  assert.equal(workspace.messages.at(-1)?.kind, 'synthesizer')
  assert.deepEqual(workspace.parallel, { completed: 3, total: 3, synthesis: 'completed' })
})

test('parallel round changes only when running follows a completed synthesis with a new instruction', () => {
  const finishedEvents = [
    ...brainstormMeeting.events.slice(0, 3),
    {
      event_id: 'member-2', meeting_id: 'meeting-parallel', step_id: 'fanout-1-member-2',
      base_step_id: 'member-2', round: 1, role: 'Member-2', attempt: 2,
      status: 'completed', parsed_output: { summary: '重試完成', arguments: [], risks: [], recommendation: '採用' },
    },
    {
      event_id: 'synthesis', meeting_id: 'meeting-parallel', step_id: 'synthesis-1',
      round: 1, role: 'Moderator', attempt: 1, status: 'completed',
      parsed_output: { summary: '最終彙整', arguments: [], risks: [], recommendation: '執行' },
    },
  ]
  const finishing = projectMeetingWorkspace({
    mode: brainstormMode,
    meeting: { ...brainstormMeeting, activity_status: 'running', events: finishedEvents },
  })
  assert.equal(finishing.family, 'conversation')
  assert.deepEqual(finishing.parallel, { completed: 3, total: 3, synthesis: 'completed' })
  assert.deepEqual(finishing.roles.map((role) => role.state), [
    'completed', 'completed', 'completed', 'completed',
  ])

  const nextRound = projectMeetingWorkspace({
    mode: brainstormMode,
    meeting: {
      ...brainstormMeeting,
      activity_status: 'running',
      events: [
        ...finishedEvents,
        {
          event_id: 'human-2', meeting_id: 'meeting-parallel', step_id: 'human-message',
          role: 'Human', attempt: 1, status: 'completed', content: '請開始新一輪',
        },
      ],
    },
  })
  assert.equal(nextRound.family, 'conversation')
  assert.deepEqual(nextRound.parallel, { completed: 0, total: 3, synthesis: 'waiting' })
  assert.deepEqual(nextRound.roles.map((role) => role.state), [
    'thinking', 'thinking', 'thinking', 'waiting',
  ])
})

test('a new parallel round does not reuse the previous round synthesis state', () => {
  const previousRound = [
    ...brainstormMeeting.events.slice(0, 3),
    {
      event_id: 'member-2', meeting_id: 'meeting-parallel', step_id: 'fanout-1-member-2',
      base_step_id: 'member-2', round: 1, role: 'Member-2', attempt: 1,
      status: 'completed', parsed_output: { summary: '第二位', arguments: [], risks: [], recommendation: '採用' },
    },
    {
      event_id: 'synthesis-1', meeting_id: 'meeting-parallel', step_id: 'synthesis-1',
      round: 1, role: 'Moderator', attempt: 1, status: 'completed',
      parsed_output: { summary: '第一輪彙整', arguments: [], risks: [], recommendation: '執行' },
    },
  ]
  const workspace = projectMeetingWorkspace({
    mode: brainstormMode,
    meeting: {
      ...brainstormMeeting,
      events: [
        ...previousRound,
        {
          event_id: 'round-2-member-3', meeting_id: 'meeting-parallel', step_id: 'fanout-2-member-3',
          base_step_id: 'member-3', round: 2, role: 'Member-3', attempt: 1,
          status: 'completed', parsed_output: { summary: '第二輪先完成', arguments: [], risks: [], recommendation: '採用' },
        },
      ],
    },
    thinkingRoleIds: ['Member-1', 'Member-2'],
  })

  assert.equal(workspace.family, 'conversation')
  assert.deepEqual(workspace.parallel, { completed: 1, total: 3, synthesis: 'waiting' })
  assert.deepEqual(
    workspace.roles.slice(0, 3).map((role) => role.state),
    ['thinking', 'thinking', 'completed'],
  )
})

test('court hearing groups saved events by backend issue and phase and passes actions through', () => {
  const workspace = projectMeetingWorkspace({
    mode: {
      id: 'courtroom', category: 'relay',
      roles: [
        { id: 'Prosecutor', name: '檢察官' },
        { id: 'Defense', name: '辯護律師' },
        { id: 'Judge', name: '法官' },
      ],
    },
    meeting: {
      meeting_id: 'meeting-court', mode_id: 'courtroom', activity_status: 'idle',
      participants: [
        { role_id: 'Prosecutor', display_name: '原告代理人' },
        { role_id: 'Defense', display_name: '被告代理人' },
        { role_id: 'Judge', display_name: '法官' },
      ],
      courtroom: {
        status: 'confirmed', current_issue_id: 'issue-1', final_status: 'not-ready',
        available_actions: ['submit-ruling', 'add-note'], case_type: 'civil',
        requires_case_type: false,
        issues: [{ id: 'issue-1', title: '被告有無占有權源？', position: 1, status: 'awaiting-ruling' }],
      },
      events: [
        {
          event_id: 'charge', meeting_id: 'meeting-court', step_id: 'courtroom-charge',
          role: 'Prosecutor', attempt: 1, status: 'completed', issue_id: 'issue-1',
          issue_phase: 'charge', interaction_type: 'courtroom-issue-phase', content: '原告主張',
        },
        {
          event_id: 'defense', meeting_id: 'meeting-court', step_id: 'courtroom-defense',
          role: 'Defense', attempt: 1, status: 'completed', issue_id: 'issue-1',
          issue_phase: 'defense', interaction_type: 'courtroom-issue-phase', content: '被告答辯',
        },
        {
          event_id: 'note', meeting_id: 'meeting-court', step_id: 'human-message',
          role: 'Human', attempt: 1, status: 'completed', content: '主席補充',
        },
      ],
    },
  })

  assert.equal(workspace.family, 'court-hearing')
  assert.deepEqual(workspace.availableActions, ['submit-ruling', 'add-note'])
  assert.deepEqual(
    workspace.issues[0]?.phases.map((phase) => [phase.phase, phase.messages.map((message) => message.id)]),
    [
      ['charge', ['charge']],
      ['defense', ['defense']],
    ],
  )
  assert.deepEqual(workspace.ungroupedMessages.map((message) => message.id), ['note'])
  assert.deepEqual(workspace.capabilities.directedRoleIds, [])
})
