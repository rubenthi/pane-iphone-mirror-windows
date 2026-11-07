# Working on Pane

Read `docs/release-workflow.md` before feature, bug-fix, version, installer, or release work. Follow its plan → implement → validate → prepare → publish → rollout sequence. Personal `pane-*` Codex skills are optional helpers, not a dependency.

- Use a feature branch and a draft PR. Do not merge or publish without authorization; green CI alone is not authorization.
- Preserve user settings, pairing records, browser profiles, signing data, bundle identity, and update rollback. Add regression tests for changes.
- Run the documented applicable checks against the final commit. Report skipped, failed, and unavailable platform/hardware checks accurately.
- Desktop patch numbers are allocated by the release workflow; do not bump versions for every patch. Explicit major/minor intent requires matching desktop metadata above all reserved stable tags/releases.
- iOS source changes require an independent companion marketing-version AND build-number increase, with the matching desktop companion declaration. Desktop-only releases must not fabricate an iPhone update.
- Release only the tested immutable snapshot and all verified assets together. Never overwrite a tag/release, force-push, delete user data for rollout testing, or claim universal/instant updates.
