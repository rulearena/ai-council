// Council chamber scene configuration. Phase A shipped a single CSS-drawn placeholder
// scene; Phase B adds a real pixel-art-adjacent background + per-seat portraits without
// touching CouncilStage.vue's core rendering logic (pendingRoles/status flow untouched).
// Phase C adds a scene registry + a persisted user preference so a scene picker can be
// added without touching CouncilStage.vue; Phase D adds the courtroom scene, exercising
// the registry's whole point (a new scene needing only a new entry here) plus the
// aspectRatio/topicCard escape hatches for scenes whose composition doesn't match the
// meeting-room scene's assumptions (4:3 art, empty tabletop dead center).
//
// Mode-system slice A (spec.md 16.6) replaces the fixed Chairman/Blue/Red/Judge seat keys
// with slot *groups* - adjudicator/chair/podium[]/ring[] - so a scene describes "where
// this kind of seat goes" rather than "where this specific role goes". Every existing
// scene's pixel coordinates are unchanged; only the shape holding them moved. See
// resolveSceneSeats below for how a roster (Chairman + the active mode's roles) gets
// mapped onto a scene's slots.

import { computed, ref } from 'vue'
import meetingRoomBackground from './assets/scenes/meeting-room.webp'
import courtroomBackground from './assets/scenes/courtroom.webp'
import chairmanPortrait from './assets/scenes/chairman.png'
import bluePortrait from './assets/scenes/blue.png'
import redPortrait from './assets/scenes/red.png'
import judgePortrait from './assets/scenes/judge.png'
import { ringSeatLayout, type RoleKind } from './modes'

// A role id ('Blue', 'Red', ...) or the fixed human chair seat. Generalized from the old
// 'Chairman' | 'Blue' | 'Red' | 'Judge' union - any mode's role ids are valid here now.
export type SeatRole = string

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

// Slot groups (spec.md 16.6): `adjudicator` holds the relay's decision-maker (or a
// parallel mode's synthesizer - both are "the one seat that isn't a peer member"),
// `chair` is the always-present human seat (not a mode role at all), `podium[]` holds a
// relay's 2 peer members side-by-side, and `ring[]` holds however many concurrent
// members a parallel mode's fanout spins up. A scene only needs to hand-author the
// slots it actually uses; resolveSceneSeats fills in `ring[]` procedurally via
// ringSeatLayout when a scene leaves it empty (no shipped scene needs a hand-tuned ring
// yet - no parallel mode is buildable in slice A).
export type SeatSlots = {
  adjudicator: SeatConfig
  chair: SeatConfig
  podium: SeatConfig[]
  ring: SeatConfig[]
}

export type SceneConfig = {
  id: string
  // Display name for the scene picker (SettingsModal).
  label: string
  // Path to a background image, or null to render the built-in CSS chamber placeholder.
  background: string | null
  seats: SeatSlots
  // Per-scene full-body portraits, keyed by role id (or 'Chairman') - independent of
  // which slot a role resolves to, since portrait identity and seat position are
  // orthogonal. A role missing from this map (or an entirely absent `portraits` field)
  // falls back to the existing small circular avatar/silhouette.
  portraits?: Partial<Record<string, string>>
  // Background image's own width/height ratio. Defaults to 4/3 (see CouncilStage.vue's
  // --scene-aspect-ratio custom property) - only needs setting when a scene's source art
  // isn't 4:3, so `background-size: cover` doesn't crop content that matters (e.g. the
  // courtroom scene's judge bench/gallery) off the top and bottom.
  aspectRatio?: number
  // Percentage position (same coordinate space as seats) for the meeting-topic card.
  // Defaults to dead center (50, 50), which is where the meeting-room scene's table
  // sits. A scene whose composition doesn't have empty space at dead center (e.g. the
  // courtroom, where the judge's seat is close to the middle) can override this instead
  // of moving the card for every scene.
  topicCard?: { x: number; y: number }
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
    chair: { x: 50, y: 16 },
    podium: [{ x: 20, y: 58 }, { x: 80, y: 58 }],
    adjudicator: { x: 50, y: 86 },
    ring: [],
  },
}

export const meetingRoomScene: SceneConfig = {
  id: 'meeting-room',
  label: '議事廳',
  background: meetingRoomBackground,
  seats: {
    chair: { x: 50, y: 31.5, scale: 0.85 },
    podium: [{ x: 20, y: 66, scale: 1 }, { x: 80, y: 66, scale: 1 }],
    adjudicator: { x: 50, y: 93, scale: 1.05 },
    ring: [],
  },
  portraits: {
    Chairman: chairmanPortrait,
    Blue: bluePortrait,
    Red: redPortrait,
    Judge: judgePortrait,
  },
}

export const courtroomScene: SceneConfig = {
  id: 'courtroom',
  label: '法院',
  background: courtroomBackground,
  // courtroom.webp is 2236x1792 (~1.248), noticeably narrower than the 4/3 (~1.333)
  // the stage box otherwise assumes - without this, `cover` crops the top/bottom just
  // enough to bite into the judge's bench and the gallery pews at the bottom edge.
  aspectRatio: 2236 / 1792,
  seats: {
    // The judge's bench sits high and central in the art - the judge stands at/behind
    // it rather than at table height like the other three roles.
    adjudicator: { x: 50, y: 44, scale: 0.85 },
    podium: [{ x: 21.6, y: 62, scale: 0.9 }, { x: 78.4, y: 62, scale: 0.9 }],
    // The chairman stands in the center aisle at the bar (the low railing separating
    // the well from the gallery), not at the head of the room like the meeting-room scene.
    chair: { x: 50, y: 80, scale: 0.95 },
    ring: [],
  },
  portraits: {
    Chairman: chairmanPortrait,
    Blue: bluePortrait,
    Red: redPortrait,
    Judge: judgePortrait,
  },
  // Dead center (the default) sits right under the judge's feet/nameplate here, unlike
  // the meeting-room scene where it's genuinely empty tabletop. The open floor between
  // the judge and the counsel tables is a tight corridor once queue labels are counted,
  // not just nameplates: measured with mock-slow and all four seats queued, the judge's
  // "等待發言" label bottoms out at 51.5% of the stage height and Blue/Red's tops out at
  // 62.7% - y:59 (tuned only against the idle nameplate-only footprint) still clipped
  // Blue/Red's queue label. 57 centers the card in that 51.5-62.7 corridor with ~1.6%
  // clearance on both sides for typical single-line topics.
  topicCard: { x: 50, y: 57 },
}

// Scene registry - a future scene only needs one new entry here.
// meetingRoomScene stays first/default since it's the shipped default look; defaultScene
// (the CSS placeholder) is kept as the documented fallback example.
export const scenes: SceneConfig[] = [meetingRoomScene, courtroomScene, defaultScene]

// A roster entry the resolver needs to know about: an id (the string that will land in
// events.jsonl, or 'Chairman' for the fixed human seat) plus which slot family it
// belongs in. Callers build this from the active mode's roles (see useCouncil.ts's
// activeModeRoles) plus the always-present Chairman.
export type SeatRosterEntry = { id: string; kind: RoleKind | 'chair' }

// Maps a scene's slot groups onto a concrete roster, producing one SeatConfig per role
// id (plus 'Chairman'). `member` roles fill `podium[]` in roster order (relay modes:
// exactly the 2 peers either side of the table); `adjudicator` and `synthesizer` roles
// both anchor to the single `adjudicator` slot (a parallel mode's synthesizer plays the
// same "one seat that isn't a peer" part a relay's adjudicator does); any role that
// doesn't fit those (e.g. more members than podium has room for, or an explicit `ring`
// kind once slice C adds it) falls back to `ring[]`, procedurally generated via
// ringSeatLayout when the scene didn't hand-author one.
export function resolveSceneSeats(scene: SceneConfig, roster: SeatRosterEntry[]): Record<string, SeatConfig> {
  const result: Record<string, SeatConfig> = { Chairman: scene.seats.chair }
  const members = roster.filter((entry) => entry.kind === 'member')
  const authority = roster.filter((entry) => entry.kind === 'adjudicator' || entry.kind === 'synthesizer')
  const overflow: SeatRosterEntry[] = []

  authority.forEach((entry, index) => {
    if (index === 0) {
      result[entry.id] = scene.seats.adjudicator
    } else {
      overflow.push(entry)
    }
  })

  members.forEach((entry, index) => {
    const seat = scene.seats.podium[index]
    if (seat) {
      result[entry.id] = seat
    } else {
      overflow.push(entry)
    }
  })

  if (overflow.length) {
    const ring = scene.seats.ring.length ? scene.seats.ring : ringSeatLayout(overflow.length)
    overflow.forEach((entry, index) => {
      result[entry.id] = ring[index % ring.length]
    })
  }

  return result
}

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

// Mode-system slice B (spec.md 16.7): a non-persisted override applied whenever a meeting
// is opened, so courtroom meetings land on the courtroom scene without touching the
// user's persisted `selectedSceneId` preference. Null means "no override - use the
// persisted preference", which is also the state a closed/absent meeting resets to (see
// applyModeScene's caller in useCouncil.ts's selectedMeeting watcher).
const sceneOverrideId = ref<string | null>(null)

export function useScenePreference() {
  // Override wins while set (an open meeting's mode just applied it); otherwise fall back
  // to the persisted preference. A stale/unknown selectedSceneId left over in localStorage
  // (e.g. a scene that was removed) falls back to meetingRoomScene here - in the computed
  // itself, not just on load - so it can never render a blank stage.
  const currentScene = computed(() => {
    if (sceneOverrideId.value) {
      const overridden = scenes.find((scene) => scene.id === sceneOverrideId.value)
      if (overridden) return overridden
    }
    return scenes.find((scene) => scene.id === selectedSceneId.value) ?? meetingRoomScene
  })

  // A manual pick (Settings) always wins immediately and persists - clearing the mode's
  // override here is what makes that true even while a meeting with a default_scene is
  // open. Trade-off (spec.md 16.7): this only lasts for the current meeting - useCouncil.ts's
  // sceneOverrideKey watcher re-applies the mode's default_scene via applyModeScene on the
  // *next* meeting switch (including re-opening the same meeting), so a manual switch never
  // becomes a persistent override for that mode. It does last for the rest of the *current*
  // meeting, including while it's actively running: that watcher is keyed on meeting
  // identity + default_scene, not on every mutation of the meeting object, so a stream of
  // websocket events/step completions doesn't quietly reapply the override underneath a
  // manual pick. The manual pick does persist as the fallback used by modes/meetings with
  // no override in play (e.g. switching to a mode whose default_scene doesn't apply, or
  // after closing the meeting list).
  function setScene(id: string) {
    sceneOverrideId.value = null
    selectedSceneId.value = id
    try {
      localStorage.setItem(SCENE_STORAGE_KEY, id)
    } catch {
      // Ignore write failures (e.g. private browsing) - the in-memory selection still works.
    }
  }

  return { scenes, selectedSceneId, currentScene, setScene }
}

// Applies (or clears) the active mode's default_scene as a non-persisted override -
// called from useCouncil.ts's selectedMeeting watcher, not by scene-picker UI. An unknown
// scene id (e.g. a mode config referencing a scene that doesn't exist) safely degrades to
// null (no override) rather than leaving the stage on a stale override or throwing.
export function applyModeScene(sceneId: string | null) {
  sceneOverrideId.value = sceneId && scenes.some((scene) => scene.id === sceneId) ? sceneId : null
}
