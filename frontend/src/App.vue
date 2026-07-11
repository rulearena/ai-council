<script setup lang="ts">
import { provide, ref } from 'vue'
import { councilKey, useCouncil, type CouncilRole } from './composables/useCouncil'
import { meetingRoomScene } from './scenes'
import TopBar from './components/TopBar.vue'
import CouncilStage from './components/CouncilStage.vue'
import ActionBar from './components/ActionBar.vue'
import SettingsModal from './components/SettingsModal.vue'
import MeetingsModal from './components/MeetingsModal.vue'
import NewCaseModal from './components/NewCaseModal.vue'
import RoleDrawer from './components/RoleDrawer.vue'
import RecordsDrawer from './components/RecordsDrawer.vue'

const store = useCouncil()
provide(councilKey, store)

type ModalName = 'settings' | 'past-topics' | 'new-case'
const openModal = ref<ModalName | null>(null)
const openRole = ref<CouncilRole | 'Chairman' | null>(null)
const recordsOpen = ref(false)

function closeModal() {
  openModal.value = null
}

function onSeatClick(role: CouncilRole | 'Chairman') {
  if (!store.selectedMeeting.value) return
  openRole.value = openRole.value === role ? null : role
}
</script>

<template>
  <main class="app-shell">
    <TopBar
      @open-settings="openModal = 'settings'"
      @open-past-topics="openModal = 'past-topics'"
      @open-new-case="openModal = 'new-case'"
      @open-records="recordsOpen = true"
    />

    <CouncilStage :scene="meetingRoomScene" @seat-click="onSeatClick" />

    <ActionBar />

    <SettingsModal :show="openModal === 'settings'" @close="closeModal" />
    <MeetingsModal :show="openModal === 'past-topics'" @close="closeModal" />
    <NewCaseModal :show="openModal === 'new-case'" @close="closeModal" />
    <RoleDrawer :role="openRole" @close="openRole = null" />
    <RecordsDrawer :show="recordsOpen" @close="recordsOpen = false" />
  </main>
</template>
