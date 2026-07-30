<script setup lang="ts">
import { computed, nextTick, ref, useId, watch } from 'vue'
import type { ChairmanParticipant } from '../chairmanActions'
import {
  detectMentionTrigger,
  buildMentionMenuItems,
  resolveMentionInsertion,
  selectMentionOption,
  shouldShowMentionAutocomplete,
} from '../composables/useMentionAutocomplete'
import type { MentionOption } from '../composables/useMentionAutocomplete'

const props = defineProps<{
  modelValue: string
  participants: ChairmanParticipant[]
  modeCategory: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'mention-inserted': [roleId: string]
}>()

const isOpen = ref(false)
const filterText = ref('')
const activeIndex = ref(0)

const menuItems = computed(() => {
  if (!isOpen.value) return []
  return buildMentionMenuItems(props.participants, filterText.value)
})

const showMenu = computed(() => isOpen.value && menuItems.value.length > 0)

// The menu is the listbox and the composer's textarea is what keeps focus, so the
// active option has to be named by id for a screen reader to follow the selection.
const uid = useId()
const menuId = `mention-menu-${uid}`
const optionId = (index: number) => `${menuId}-option-${index}`
const activeOptionId = computed(() => (showMenu.value ? optionId(activeIndex.value) : undefined))

const menuRef = ref<HTMLUListElement | null>(null)
watch([activeIndex, showMenu], () => {
  if (!showMenu.value) return
  // The menu caps its height and scrolls, so arrowing past the fold has to bring the
  // active option along or keyboard navigation walks out of sight.
  nextTick(() => {
    menuRef.value?.querySelector('.mention-option-active')?.scrollIntoView({ block: 'nearest' })
  })
})

watch(() => props.modelValue, (text) => {
  if (!shouldShowMentionAutocomplete(props.modeCategory)) {
    isOpen.value = false
    return
  }

  const trigger = detectMentionTrigger(text)
  if (trigger.triggered) {
    isOpen.value = true
    filterText.value = trigger.filterText
    activeIndex.value = 0
  } else {
    isOpen.value = false
  }
})

const NAVIGATION_KEYS: Record<string, 'escape' | 'enter' | 'tab' | 'arrow-down' | 'arrow-up'> = {
  Escape: 'escape',
  Enter: 'enter',
  Tab: 'tab',
  ArrowDown: 'arrow-down',
  ArrowUp: 'arrow-up',
}

/**
 * Handles a keystroke aimed at the open menu. Returns whether the key was consumed, so
 * the composer knows to stop rather than also treating Enter as send.
 */
function handleKeyDown(event: KeyboardEvent): boolean {
  // Only claim a key when there is actually a menu to act on. `isOpen` can be true with
  // nothing matching the filter, and claiming Enter there would swallow it entirely:
  // no option to select, and no send either.
  if (!showMenu.value) return false

  const key = NAVIGATION_KEYS[event.key]
  if (!key) return false

  const result = resolveMentionInsertion(
    { open: true, filterText: filterText.value, activeIndex: activeIndex.value },
    key,
    menuItems.value,
  )
  event.preventDefault()

  if (result.action === 'navigate') activeIndex.value = result.newActiveIndex
  else if (result.action === 'select') applySelection(result.selectedOption)
  else isOpen.value = false

  return true
}

function applySelection(option: MentionOption) {
  const result = selectMentionOption(props.modelValue, option)
  emit('update:modelValue', result.text)
  emit('mention-inserted', option.role_id)
  isOpen.value = false
}

function selectItem(index: number) {
  const item = menuItems.value[index]
  if (!item) return
  applySelection(item)
}

defineExpose({ handleKeyDown, menuId, activeOptionId, isExpanded: showMenu })

function onMouseenter(index: number) {
  activeIndex.value = index
}

function optionLabel(item: { role_id: string; display_name?: string | null; name?: string | null }): string {
  if (item.role_id === 'all') return item.display_name || '全體成員'
  return item.display_name || item.name || item.role_id
}
</script>

<template>
  <div class="mention-autocomplete" data-testid="mention-autocomplete">
    <!-- The listbox role belongs on the menu itself: on the wrapper it announced an
         empty listbox the whole time the menu was closed. -->
    <ul
      v-if="showMenu"
      :id="menuId"
      ref="menuRef"
      class="mention-menu"
      data-testid="mention-menu"
      role="listbox"
      aria-label="提及成員"
    >
      <li
        v-for="(item, index) in menuItems"
        :id="optionId(index)"
        :key="item.role_id"
        class="mention-option"
        :class="{ 'mention-option-active': index === activeIndex }"
        data-testid="mention-option"
        role="option"
        :aria-selected="index === activeIndex"
        @mousedown.prevent="selectItem(index)"
        @mouseenter="onMouseenter(index)"
      >
        {{ optionLabel(item) }}
        <span v-if="item.role_id !== 'all'" class="mention-role-id">{{ item.role_id }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.mention-autocomplete {
  position: absolute;
  bottom: 100%;
  left: 0;
  z-index: 100;
  width: 220px;
}

.mention-menu {
  list-style: none;
  margin: 0;
  padding: 4px 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  box-shadow: var(--shadow-md);
  max-height: 200px;
  overflow-y: auto;
}

.mention-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 13px;
  color: var(--color-text);
}

.mention-option-active,
.mention-option:hover {
  background: var(--color-surface-muted);
}

.mention-role-id {
  margin-left: 8px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-text-muted);
}
</style>
