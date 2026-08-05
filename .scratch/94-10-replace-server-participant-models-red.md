# Backlog #94⑩ TDD red evidence

- Previous green: `23088ff`
- Test change: changed every `replaceServerParticipantModels` contract call to pass only `participants`.
- Command: `node --test --experimental-strip-types tests/unit/inRailModelSwitching.test.ts`
- Result: expected failure before implementation signature correction: 11 passed, 5 failed.
- Failure: the previous two-argument implementation treated `participants` as its unused first argument, then threw `TypeError: Cannot read properties of undefined (reading 'map')`.

This demonstrates that the public helper contract now requires the participant-only API before the implementation and caller are corrected.
