// Council chamber scene configuration. Phase A shipped a single CSS-drawn placeholder
// scene; Phase B adds a real pixel-art-adjacent background + per-seat portraits without
// touching CouncilStage.vue's core rendering logic (pendingRoles/status flow untouched).

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
