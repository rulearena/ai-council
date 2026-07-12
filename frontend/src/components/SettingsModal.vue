<script setup lang="ts">
import { computed, inject } from 'vue'
import { councilKey } from '../composables/useCouncil'
import { formatDateTime, roleClass, roleIcon } from '../composables/useCouncil'
import { useScenePreference } from '../scenes'
import Modal from './Modal.vue'

defineProps<{ show: boolean }>()
defineEmits<{ close: [] }>()

const store = inject(councilKey)!
const { models, selectedModels, modelTestResults, devMode, testSelectedModel, loading } = store

const { scenes, selectedSceneId, setScene } = useScenePreference()
const sceneModel = computed({
  get: () => selectedSceneId.value,
  set: (id: string) => setScene(id),
})
</script>

<template>
  <Modal :show="show" title="Settings" test-id="settings-modal" close-test-id="settings-close-button" @close="$emit('close')">
    <section class="settings-scene-row">
      <label class="scene-picker">
        場景
        <select v-model="sceneModel" data-testid="scene-select">
          <option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.label }}</option>
        </select>
      </label>
    </section>

    <section class="settings-role-grid">
      <label class="model-slot" :class="roleClass('Blue')">
        <span class="role-badge role-blue" data-testid="role-badge">
          <img :src="roleIcon('Blue')" class="role-icon" alt="Blue" />
          Blue
        </span>
        <span class="model-control">
          <select v-model="selectedModels.Blue" data-testid="blue-model-select">
            <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
          </select>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            data-testid="test-blue-model-button"
            @click="testSelectedModel('Blue')"
            :disabled="loading || !selectedModels.Blue"
          >
            Test
          </button>
        </span>
      </label>
      <label class="model-slot" :class="roleClass('Red')">
        <span class="role-badge role-red" data-testid="role-badge">
          <img :src="roleIcon('Red')" class="role-icon" alt="Red" />
          Red
        </span>
        <span class="model-control">
          <select v-model="selectedModels.Red" data-testid="red-model-select">
            <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
          </select>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            data-testid="test-red-model-button"
            @click="testSelectedModel('Red')"
            :disabled="loading || !selectedModels.Red"
          >
            Test
          </button>
        </span>
      </label>
      <label class="model-slot" :class="roleClass('Judge')">
        <span class="role-badge role-judge" data-testid="role-badge">
          <img :src="roleIcon('Judge')" class="role-icon" alt="Judge" />
          Judge
        </span>
        <span class="model-control">
          <select v-model="selectedModels.Judge" data-testid="judge-model-select">
            <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
          </select>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            data-testid="test-judge-model-button"
            @click="testSelectedModel('Judge')"
            :disabled="loading || !selectedModels.Judge"
          >
            Test
          </button>
        </span>
      </label>
    </section>

    <section class="model-test-status" data-testid="model-test-status">
      <span>
        <i class="status-dot" :data-status="modelTestResults.Blue.status" aria-hidden="true"></i>
        Blue: {{ modelTestResults.Blue.status }}
        <small v-if="modelTestResults.Blue.testedAt">測試 {{ formatDateTime(modelTestResults.Blue.testedAt) }}</small>
        <em v-if="modelTestResults.Blue.error">{{ modelTestResults.Blue.error }}</em>
      </span>
      <span>
        <i class="status-dot" :data-status="modelTestResults.Red.status" aria-hidden="true"></i>
        Red: {{ modelTestResults.Red.status }}
        <small v-if="modelTestResults.Red.testedAt">測試 {{ formatDateTime(modelTestResults.Red.testedAt) }}</small>
        <em v-if="modelTestResults.Red.error">{{ modelTestResults.Red.error }}</em>
      </span>
      <span>
        <i class="status-dot" :data-status="modelTestResults.Judge.status" aria-hidden="true"></i>
        Judge: {{ modelTestResults.Judge.status }}
        <small v-if="modelTestResults.Judge.testedAt">測試 {{ formatDateTime(modelTestResults.Judge.testedAt) }}</small>
        <em v-if="modelTestResults.Judge.error">{{ modelTestResults.Judge.error }}</em>
      </span>
    </section>

    <section class="dev-mode-row">
      <label class="dev-mode-toggle">
        <input type="checkbox" v-model="devMode" data-testid="dev-mode-toggle" />
        開發者模式（在議事紀錄中顯示 Debug 面板）
      </label>
    </section>
  </Modal>
</template>
