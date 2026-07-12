<script setup lang="ts">
// TopBar's "?" button opens this - browsing-only view of the same mode catalog the New
// Case picker uses (spec.md 16.6: "頂欄常駐「?」按鈕開模式說明抽屜...同一份 catalog 資料"),
// so a user mid-meeting can check a mode's tagline/when-to-use/SOP without going through
// New Case. showActions=false on every card since choosing a mode isn't meaningful here.
import { modeCatalog } from '../modes'
import Drawer from './Drawer.vue'
import ModeCard from './ModeCard.vue'

defineProps<{ show: boolean }>()
defineEmits<{ close: [] }>()
</script>

<template>
  <Drawer :show="show" title="會議模式說明" test-id="mode-help-drawer" close-test-id="mode-help-drawer-close-button" @close="$emit('close')">
    <p class="mode-help-intro">
      目前僅「紅藍對抗」可實際建立會議；其餘模式的名稱、適合情境與 SOP 已可先行瀏覽，將於後續版本開放建立。
    </p>
    <div class="mode-card-grid">
      <ModeCard
        v-for="mode in modeCatalog"
        :key="mode.id"
        :mode="mode"
        test-id-prefix="mode-help-card"
        :show-actions="false"
      />
    </div>
  </Drawer>
</template>
