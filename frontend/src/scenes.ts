// Council chamber scene configuration. Phase A shipped a single CSS-drawn placeholder
// scene; Phase B adds a real pixel-art-adjacent background + per-seat portraits without
// touching CouncilStage.vue's core rendering logic (pendingRoles/status flow untouched).
// Phase C adds a scene registry + a persisted user preference so a scene picker (and
// future scenes, e.g. a courtroom) can be added without touching CouncilStage.vue at all.

import { computed, ref } from 'vue'
import meetingRoomBackground from './assets/scenes/meeting-room.webp'
import chairmanPortrait from './assets/scenes/chairman.png'
import bluePortrait from './assets/scenes/blue.png'
import redPortrait from './assets/scenes/red.png'
import judgePortrait from './assets/scenes/judge.png'

export type SeatRole = 'Chairman' | 'Blue' | 'Red' | 'Judge'

// Percentage coordinates (0-100) within the stage container, so the layout survives a
// background-image swap and different aspect ratios instead of being pinned to pixels.
// For a seat with a portrait, (x, y) marks the character's foot position - the seat
// element is bottom-anchored there. For a seat without a portrait (fallback avatar),
// (x, y) marks the avatar's center, matching Phase A's placeholder behavior.
export type SeatConfig = {
  x: number
  y: number
  // Multiplier on the portrait's base size (~22% of the scene's rendered height).
  // Ignored for seats that fall back to the small circular avatar. Defaults to 1.
  scale?: number
}

export type SceneConfig = {
  id: string
  // Display name for the scene picker (SettingsModal).
  label: string
  // Path to a background image, or null to render the built-in CSS chamber placeholder.
  background: string | null
  seats: Record<SeatRole, SeatConfig>
  // Per-scene full-body portraits. A role missing from this map (or an entirely absent
  // `portraits` field) falls back to the existing small circular avatar - using
  // assets/roles/*.png for Blue/Red/Judge, or the generic silhouette for Chairman.
  portraits?: Partial<Record<SeatRole, string>>
}

// Kept as the documented fallback example: any scene that omits `background` renders
// this hand-drawn CSS chamber instead of a photo, and seats without a `portraits` entry
// always render the small avatar - this is what makes that path exercise-able going
// forward (e.g. a future courtroom scene reusing the same mechanism).
export const defaultScene: SceneConfig = {
  id: 'default-chamber',
  label: '極簡預設（CSS）',
  background: null,
  seats: {
    Chairman: { x: 50, y: 16 },
    Blue: { x: 20, y: 58 },
    Red: { x: 80, y: 58 },
    Judge: { x: 50, y: 86 },
  },
}

export const meetingRoomScene: SceneConfig = {
  id: 'meeting-room',
  label: '議事廳',
  background: meetingRoomBackground,
  seats: {
    Chairman: { x: 50, y: 31.5, scale: 0.85 },
    Blue: { x: 20, y: 66, scale: 1 },
    Red: { x: 80, y: 66, scale: 1 },
    Judge: { x: 50, y: 93, scale: 1.05 },
  },
  portraits: {
    Chairman: chairmanPortrait,
    Blue: bluePortrait,
    Red: redPortrait,
    Judge: judgePortrait,
  },
}

// Scene registry - a future scene (e.g. a courtroom) only needs one new entry here.
// meetingRoomScene stays first/default since it's the shipped default look; defaultScene
// (the CSS placeholder) is kept as the documented fallback example.
export const scenes: SceneConfig[] = [meetingRoomScene, defaultScene]

const SCENE_STORAGE_KEY = 'ai-council-scene'

function readStoredSceneId(): string | null {
  try {
    return localStorage.getItem(SCENE_STORAGE_KEY)
  } catch {
    return null
  }
}

// Module-scoped (singleton) state: this is a pure visual preference, unrelated to any
// meeting data, so it deliberately lives outside the useCouncil() store and doesn't need
// provide/inject - every caller of useScenePreference() shares the same ref.
// A stored id that doesn't match any registered scene (e.g. left over from a scene that
// was since removed) is sanitized to the default right here - otherwise the <select> in
// SettingsModal would render blank (no matching <option>) even though currentScene below
// already falls back correctly, leaving the picker visually out of sync with the stage.
const storedSceneId = readStoredSceneId()
const selectedSceneId = ref(
  storedSceneId && scenes.some((scene) => scene.id === storedSceneId) ? storedSceneId : meetingRoomScene.id,
)

export function useScenePreference() {
  // A stale/unknown id left over in localStorage (e.g. a scene that was removed) falls
  // back to meetingRoomScene here - in the computed itself, not just on load - so it can
  // never render a blank stage.
  const currentScene = computed(
    () => scenes.find((scene) => scene.id === selectedSceneId.value) ?? meetingRoomScene,
  )

  function setScene(id: string) {
    selectedSceneId.value = id
    try {
      localStorage.setItem(SCENE_STORAGE_KEY, id)
    } catch {
      // Ignore write failures (e.g. private browsing) - the in-memory selection still works.
    }
  }

  return { scenes, selectedSceneId, currentScene, setScene }
}
