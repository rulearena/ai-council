<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ChairmanParticipant } from '../chairmanActions'
import {
  detectMentionTrigger,
  buildMentionMenuItems,
  resolveMentionInsertion,
  selectMentionOption,
  shouldShowMentionAutocomplete,
} from '../composables/useMentionAutocomplete'

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

function onInput(event: Event) {
  const target = event.target as HTMLTextAreaElement
  const text = target.value
  emit('update:modelValue', text)

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
}

function onKeyDown(event: KeyboardEvent) {
  if (!isOpen.value) return

  if (event.key === 'Escape') {
    event.preventDefault()
    isOpen.value = false
    return
  }

  if (event.key === 'ArrowDown') {
    event.preventDefault()
    const result = resolveMentionInsertion(
      { open: true, filterText: filterText.value, activeIndex: activeIndex.value },
      'arrow-down',
      menuItems.value,
    )
    if (result.action === 'navigate') activeIndex.value = result.newActiveIndex
    return
  }

  if (event.key === 'ArrowUp') {
    event.preventDefault()
    const result = resolveMentionInsertion(
      { open: true, filterText: filterText.value, activeIndex: activeIndex.value },
      'arrow-up',
      menuItems.value,
    )
    if (result.action === 'navigate') activeIndex.value = result.newActiveIndex
    return
  }

  if (event.key === 'Enter' || event.key === 'Tab') {
    event.preventDefault()
    selectItem(activeIndex.value)
    return
  }
}

function selectItem(index: number) {
  const item = menuItems.value[index]
  if (!item) return

  const result = selectMentionOption(props.modelValue, item)
  emit('update:modelValue', result.text)
  emit('mention-inserted', item.role_id)
  isOpen.value = false
}

function onMouseenter(index: number) {
  activeIndex.value = index
}

function optionLabel(item: { role_id: string; display_name?: string | null; name?: string | null }): string {
  if (item.role_id === 'all') return item.display_name || '全體成員'
  return item.display_name || item.name || item.role_id
}
</script>

<template>
  <div class="mention-autocomplete" data-testid="mention-autocomplete" role="listbox" aria-label="提及成員">
    <ul v-if="showMenu" class="mention-menu" data-testid="mention-menu">
      <li
        v-for="(item, index) in menuItems"
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
