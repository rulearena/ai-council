<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { councilKey } from '../composables/useCouncil'
import { councilRoles, formatDateTime, roleClass, roleColor, roleColorVars, roleIcon } from '../composables/useCouncil'
import RoleSilhouette from './RoleSilhouette.vue'
import { useScenePreference } from '../scenes'
import Modal from './Modal.vue'
import ModelManagerPanel from './ModelManagerPanel.vue'

const props = defineProps<{ show: boolean }>()
defineEmits<{ close: [] }>()

const store = inject(councilKey)!
const { models, selectedModels, modelTestResults, devMode, testSelectedModel, loading } = store

const { scenes, currentScene, setScene } = useScenePreference()
// Reads currentScene (not the persisted selectedSceneId) so the dropdown always matches
// what the stage is actually showing, including while a mode's default_scene override is
// in play - selecting an option here calls setScene(), which clears any override, so the
// picker never lags behind a manual pick either.
const sceneModel = computed({
  get: () => currentScene.value.id,
  set: (id: string) => setScene(id),
})

type SettingsTab = 'general' | 'models'
const activeTab = ref<SettingsTab>('general')

// activeTab lives here in SettingsModal, which stays mounted across modal close/reopen
// (only `show` toggles), so without this it would silently keep whatever tab was active
// last time - reset to 一般 on every reopen so a previous 模型管理 visit doesn't linger.
watch(
  () => props.show,
  (visible) => {
    if (visible) activeTab.value = 'general'
  },
)
</script>

<template>
  <Modal :show="show" title="Settings" test-id="settings-modal" close-test-id="settings-close-button" @close="$emit('close')">
    <div class="settings-tabs">
      <button
        type="button"
        class="btn btn-ghost btn-sm settings-tab-button"
        :class="{ active: activeTab === 'general' }"
        data-testid="general-tab"
        @click="activeTab = 'general'"
      >
        一般
      </button>
      <button
        type="button"
        class="btn btn-ghost btn-sm settings-tab-button"
        :class="{ active: activeTab === 'models' }"
        data-testid="model-manager-tab"
        @click="activeTab = 'models'"
      >
        模型管理
      </button>
    </div>

    <ModelManagerPanel v-if="activeTab === 'models'" />

    <template v-else>
    <section class="settings-scene-row">
      <label class="scene-picker">
        場景
        <select v-model="sceneModel" data-testid="scene-select">
          <option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.label }}</option>
        </select>
      </label>
    </section>

    <!-- One model-slot per active-mode role (councilRoles), not a hardcoded
         Blue/Red/Judge triple - a mode with a different roster renders however many
         slots it has, each colored from that role's catalog color (roleColorVars). -->
    <section class="settings-role-grid">
      <label v-for="role in councilRoles" :key="role" class="model-slot" :class="roleClass(role)" :style="roleColorVars(role)">
        <span class="role-badge" :class="roleClass(role)" :style="roleColorVars(role)" data-testid="role-badge">
          <img v-if="roleIcon(role)" :src="roleIcon(role)" class="role-icon" :alt="role" />
          <RoleSilhouette v-else :color="roleColor(role)" :size="20" />
          {{ role }}
        </span>
        <span class="model-control">
          <select v-model="selectedModels[role]" :data-testid="`${role.toLowerCase()}-model-select`">
            <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
          </select>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            :data-testid="`test-${role.toLowerCase()}-model-button`"
            @click="testSelectedModel(role)"
            :disabled="loading || !selectedModels[role]"
          >
            Test
          </button>
        </span>
      </label>
    </section>

    <section class="model-test-status" data-testid="model-test-status">
      <span v-for="role in councilRoles" :key="role">
        <i class="status-dot" :data-status="modelTestResults[role].status" aria-hidden="true"></i>
        {{ role }}: {{ modelTestResults[role].status }}
        <small v-if="modelTestResults[role].testedAt">測試 {{ formatDateTime(modelTestResults[role].testedAt) }}</small>
        <em v-if="modelTestResults[role].error">{{ modelTestResults[role].error }}</em>
      </span>
    </section>

    <section class="dev-mode-row">
      <label class="dev-mode-toggle">
        <input type="checkbox" v-model="devMode" data-testid="dev-mode-toggle" />
        開發者模式（在議事紀錄中顯示 Debug 面板）
      </label>
    </section>
    </template>
  </Modal>
</template>
