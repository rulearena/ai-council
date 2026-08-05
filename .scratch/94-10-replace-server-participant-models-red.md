# Backlog #94⑩ TDD red evidence

- Base: `349a7c9`
- Test change: renamed the unit contract and import from `mergeServerParticipantModels` to `replaceServerParticipantModels`.
- Command: `node --test --experimental-strip-types tests/unit/inRailModelSwitching.test.ts`
- Result: expected failure before implementation.
- Failure: `meetingWorkspace.ts` did not provide the requested `replaceServerParticipantModels` export.

This demonstrates that the renamed public helper contract was introduced before the implementation rename.
