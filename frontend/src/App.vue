<script setup lang="ts">
import { provide, ref } from 'vue'
import { councilKey, useCouncil, type CouncilRole } from './composables/useCouncil'
import { useScenePreference } from './scenes'
import TopBar from './components/TopBar.vue'
import SettingsModal from './components/SettingsModal.vue'
import MeetingsModal from './components/MeetingsModal.vue'
import NewCaseModal from './components/NewCaseModal.vue'
import RoleDrawer from './components/RoleDrawer.vue'
import RecordsDrawer from './components/RecordsDrawer.vue'
import ModeHelpDrawer from './components/ModeHelpDrawer.vue'
import CourtroomDocketPanel from './components/CourtroomDocketPanel.vue'
import MeetingSettingsDrawer from './components/MeetingSettingsDrawer.vue'
import CaseMaterialsDrawer from './components/CaseMaterialsDrawer.vue'
import ConversationWorkspace from './components/ConversationWorkspace.vue'
import { canLeaveMeetingSettings } from './meetingSettingsNavigation'

const store = useCouncil()
provide(councilKey, store)

const { currentScene } = useScenePreference()

type ModalName = 'settings' | 'past-topics' | 'new-case'
const openModal = ref<ModalName | null>(null)
const openRole = ref<CouncilRole | 'Chairman' | null>(null)
const recordsOpen = ref(false)
const modeHelpOpen = ref(false)
const meetingSettingsOpen = ref(false)
const materialsOpen = ref(false)

function closeModal() {
  openModal.value = null
}

function navigateFromMeetingSettings(action: () => void) {
  if (!canLeaveMeetingSettings()) return
  meetingSettingsOpen.value = false
  action()
}

function onSeatClick(role: CouncilRole | 'Chairman') {
  if (!store.selectedMeeting.value) return
  openRole.value = openRole.value === role ? null : role
}
</script>

<template>
  <main class="app-shell">
    <TopBar
      @open-settings="navigateFromMeetingSettings(() => openModal = 'settings')"
      @open-meeting-settings="meetingSettingsOpen = true"
      @open-materials="navigateFromMeetingSettings(() => materialsOpen = true)"
      @open-past-topics="navigateFromMeetingSettings(() => openModal = 'past-topics')"
      @open-new-case="navigateFromMeetingSettings(() => openModal = 'new-case')"
      @open-records="navigateFromMeetingSettings(() => recordsOpen = true)"
      @open-mode-help="navigateFromMeetingSettings(() => modeHelpOpen = true)"
    />

    <template v-if="store.selectedMeeting.value?.mode_id === 'courtroom'">
      <CourtroomDocketPanel
        :scene="currentScene"
        @open-meeting-settings="meetingSettingsOpen = true"
        @open-materials="materialsOpen = true"
        @role-click="onSeatClick"
      />
    </template>
    <ConversationWorkspace
      v-else
      :scene="currentScene"
      @role-click="onSeatClick"
      @open-materials="materialsOpen = true"
    />

    <SettingsModal :show="openModal === 'settings'" @close="closeModal" />
    <MeetingsModal :show="openModal === 'past-topics'" @close="closeModal" />
    <NewCaseModal :show="openModal === 'new-case'" @close="closeModal" />
    <RoleDrawer :role="openRole" @close="openRole = null" />
    <RecordsDrawer :show="recordsOpen" @close="recordsOpen = false" />
    <MeetingSettingsDrawer :show="meetingSettingsOpen" @close="meetingSettingsOpen = false" />
    <CaseMaterialsDrawer :show="materialsOpen" @close="materialsOpen = false" />
    <ModeHelpDrawer :show="modeHelpOpen" @close="modeHelpOpen = false" />
  </main>
</template>
