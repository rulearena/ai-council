<script setup lang="ts">
// Generic colorable placeholder for any role without a hand-drawn icon (spec.md 16.6:
// "無立繪的角色用「角色色 SVG 剪影」placeholder"). Same bust glyph CouncilStage.vue used
// to hardcode for the Chairman fallback, now shared by any role - new modes' roles
// (Prosecutor, Pro/Con, the six hats, personas, ...) never ship art, so this is what
// they render everywhere a role icon/portrait would otherwise go.
defineProps<{ color: string; size?: number }>()
</script>

<template>
  <svg
    :width="size ?? 28"
    :height="size ?? 28"
    viewBox="0 0 24 24"
    :fill="color"
    aria-hidden="true"
    class="role-silhouette"
  >
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
  </svg>
</template>
