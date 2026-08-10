<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ChatroomSource, ChatSourceToken } from '../api'
import {
  detectSourceTrigger,
  filterSourceOptions,
  insertSourceToken,
  sourceOptionMetadata,
} from '../chatroomSources'

const props = defineProps<{
  modelValue: string
  sources: ChatroomSource[]
  selectionStart?: number
  disabled?: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  'source-inserted': [token: ChatSourceToken]
}>()

const open = ref(false)
const filterText = ref('')
const activeIndex = ref(0)
const items = computed(() => filterSourceOptions(props.sources, filterText.value))

watch([() => props.modelValue, () => props.selectionStart], ([text]) => {
  if (props.disabled) {
    open.value = false
    return
  }
  const trigger = detectSourceTrigger(text, props.selectionStart ?? text.length)
  if (!trigger.triggered) {
    open.value = false
    return
  }
  filterText.value = trigger.filterText
  activeIndex.value = 0
  open.value = true
})

function handleKeyDown(event: KeyboardEvent): boolean {
  if (!open.value || !items.value.length) return false
  if (event.key === 'Escape') {
    event.preventDefault()
    open.value = false
    return true
  }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const delta = event.key === 'ArrowDown' ? 1 : -1
    activeIndex.value = (activeIndex.value + delta + items.value.length) % items.value.length
    return true
  }
  if (event.key === 'Enter' || event.key === 'Tab') {
    event.preventDefault()
    select(items.value[activeIndex.value])
    return true
  }
  return false
}

function select(source: ChatroomSource) {
  const result = insertSourceToken(
    props.modelValue,
    props.selectionStart ?? props.modelValue.length,
    source,
    `source-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  )
  emit('update:modelValue', result.content)
  emit('source-inserted', result.token)
  open.value = false
}

defineExpose({ isExpanded: open, handleKeyDown })
</script>

<template>
  <div class="source-autocomplete" data-testid="source-autocomplete">
    <ul v-if="open && items.length" class="source-menu" data-testid="source-menu" role="listbox" aria-label="選取附件">
      <li
        v-for="source in items"
        :key="source.source_ref"
        class="source-option"
        :class="{ active: activeIndex === items.indexOf(source) }"
        data-testid="source-option"
        role="option"
        @mousedown.prevent="select(source)"
      >
        <span>#{{ source.label }}</span>
        <small>{{ sourceOptionMetadata(source) }}</small>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.source-autocomplete { position: absolute; bottom: 100%; left: 230px; z-index: 100; width: 300px; min-height: 1px; }
.source-menu { list-style: none; margin: 0; padding: 4px 0; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-surface); box-shadow: var(--shadow-md); max-height: 220px; overflow-y: auto; }
.source-option { display: flex; justify-content: space-between; gap: 8px; padding: 6px 10px; cursor: pointer; color: var(--color-text); }
.source-option:hover { background: var(--color-surface-muted); }
.source-option.active { background: var(--color-surface-muted); }
.source-option small { color: var(--color-text-muted); }
</style>
