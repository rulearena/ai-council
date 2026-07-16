<script setup lang="ts">
import { inject, ref, watch } from 'vue'
import { councilKey } from '../composables/useCouncil'
import Modal from './Modal.vue'
import ModelManagerPanel from './ModelManagerPanel.vue'

const props = defineProps<{ show: boolean }>()
defineEmits<{ close: [] }>()
const { devMode } = inject(councilKey)!
const activeTab = ref<'models' | 'advanced'>('models')

watch(() => props.show, (show) => {
  if (show) activeTab.value = 'models'
})
</script>

<template>
  <Modal :show="show" title="系統設定" test-id="settings-modal" close-test-id="settings-close-button" @close="$emit('close')">
    <p class="scope-hint">這裡只管理所有會議共用的 Provider 與模型。單場會議資料請使用上方的會議次導覽。</p>
    <div class="settings-tabs">
      <button type="button" class="btn btn-ghost btn-sm settings-tab-button" :class="{ active: activeTab === 'models' }" data-testid="model-manager-tab" @click="activeTab = 'models'">Provider 與模型</button>
      <button type="button" class="btn btn-ghost btn-sm settings-tab-button" :class="{ active: activeTab === 'advanced' }" data-testid="advanced-settings-tab" @click="activeTab = 'advanced'">進階功能</button>
    </div>
    <ModelManagerPanel v-if="show && activeTab === 'models'" />
    <section v-else class="dev-mode-row">
      <label class="dev-mode-toggle">
        <input type="checkbox" v-model="devMode" data-testid="dev-mode-toggle" />
        顯示事件原始資料
      </label>
      <p>預設關閉。只影響議事紀錄畫面，不會改變 AI 的提示詞、模型或執行方式。</p>
    </section>
  </Modal>
</template>
