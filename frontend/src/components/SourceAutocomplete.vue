<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ChatroomSource, ChatSourceToken } from '../api'

const props = defineProps<{
  modelValue: string
  sources: ChatroomSource[]
  disabled?: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  'source-inserted': [token: ChatSourceToken]
}>()

const open = ref(false)
const filterText = ref('')
const items = computed(() => props.sources.filter((source) => {
  if (!source.active || !source.readable) return false
  return !filterText.value || source.label.toLowerCase().includes(filterText.value.toLowerCase())
}))

watch(() => props.modelValue, (text) => {
  const index = text.lastIndexOf('#')
  if (index < 0 || (index > 0 && !/[\s\n]/.test(text[index - 1]))) {
    open.value = false
    return
  }
  const suffix = text.slice(index + 1)
  if (/\s/.test(suffix)) {
    open.value = false
    return
  }
  filterText.value = suffix
  open.value = true
})

function select(source: ChatroomSource) {
  const index = props.modelValue.lastIndexOf('#')
  const before = props.modelValue.slice(0, index)
  const displayText = `#${source.label}`
  const next = `${before}${displayText} `
  const start = Array.from(before).length
  emit('update:modelValue', next)
  emit('source-inserted', {
    token_id: `source-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    source_ref: source.source_ref,
    display_text: displayText,
    start,
    end: start + Array.from(displayText).length,
  })
  open.value = false
}

defineExpose({ isExpanded: open })
</script>

<template>
  <div class="source-autocomplete" data-testid="source-autocomplete">
    <ul v-if="open && items.length" class="source-menu" data-testid="source-menu" role="listbox" aria-label="選取附件">
      <li
        v-for="source in items"
        :key="source.source_ref"
        class="source-option"
        data-testid="source-option"
        role="option"
        @mousedown.prevent="select(source)"
      >
        <span>#{{ source.label }}</span>
        <small>{{ source.kind === 'attachment' ? '附件' : '證據' }} · {{ source.source_ref }}</small>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.source-autocomplete { position: absolute; bottom: 100%; left: 230px; z-index: 100; width: 300px; }
.source-menu { list-style: none; margin: 0; padding: 4px 0; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-surface); box-shadow: var(--shadow-md); max-height: 220px; overflow-y: auto; }
.source-option { display: flex; justify-content: space-between; gap: 8px; padding: 6px 10px; cursor: pointer; color: var(--color-text); }
.source-option:hover { background: var(--color-surface-muted); }
.source-option small { color: var(--color-text-muted); }
</style>
