# Pane update and release workflow

## Repeated development steps

1. **Plan:** identify desktop, native helper, installer, signing, and iPhone impacts; define acceptance checks and preservation requirements.
2. **Implement:** make the smallest coherent change on a feature branch. Preserve settings, saved pairings, browser profiles, signing data, bundle identity, and rollback behavior. Add regression tests.
3. **Validate:** run the checks below, record hardware checks separately, and open a draft PR. Review the exact final commit's CI, not an earlier green run.
4. **Prepare:** update CHANGELOG.md for user-visible changes. Normal desktop patches need no manual version bump. For a deliberate major/minor release, set `handset/version.py` and all four fields in `packaging/version.txt` to a version above every reserved stable tag/release. For iPhone changes, follow the independent companion policy below.
5. **Publish:** only merge when authorized and reviewed. A qualifying push to main automatically starts the tested release workflow. Do not manually publish an untested executable, overwrite an existing release, or auto-merge a PR merely because checks pass.
6. **Check rollout:** verify the run's source/release commits, stable tag, all four assets, version/checksum metadata, and `/releases/latest/download/update.json`. Confirm update behavior on a real Windows installation without deleting user data.

Personal Codex skills can guide these steps, but are not required to use this repository.

## Automatic desktop versions

Activation: merging the PR that introduces this workflow is itself a qualifying release-workflow change and can publish the next tested desktop patch. Creating or reviewing its draft PR does not activate automation, merge code, or publish a release. Review and authorize that merge with this consequence in mind.

`.github/workflows/release.yml` runs on main changes to application, native, signer, iOS, packaging, dependencies, or release/companion workflows. Markdown-only changes, tests-only changes, and unrelated documentation do not publish. It also supports explicit `v*` tags and manual dispatch on main.

`packaging/prepare_release.py` inventories **all** stable tags and releases (including drafts) under the serialized release workflow. It keeps a requested source version if it exceeds all reserved versions; otherwise it chooses the next patch above the highest. Versions use strict `major.minor.patch` numeric components within Windows resource limits. No pre-release tag is used as a stable version baseline.

Main is not rewritten by a bot. The workflow creates a local immutable release commit whose parent is the triggering source SHA, changing only `handset/version.py` and `packaging/version.txt`. Its commit message records `Pane-Source: <SHA>`. Windows tests, executable build, manifest, and smoke tests all run on this versioned commit. The iOS build uses the triggering source SHA; its entire iOS source tree is unchanged in the release commit. The desktop and iPhone versions intentionally need not match.

After all gates pass, a main run fetches main and verifies its source remains an ancestor. Newer release inputs supersede the run rather than publishing stale code; the newer qualifying run handles the accumulated changes. Documentation/tests-only advancement is allowed because it does not change the released runtime/build inputs. GitHub concurrency may replace queued pending runs; the latest run includes earlier merged changes. A failed or superseded run does not imply a release.

The workflow pushes **only the new tag**, never a main/feature branch, and never force-pushes. The tag targets the exact tested release commit, then all four assets are uploaded to a draft and published together as latest. Tags pushed by `GITHUB_TOKEN` do not recursively start workflows. The workflow needs repository contents-write permission and must be allowed to create tags by repository rules. Branch protection and review requirements remain a repository-owner responsibility.

Explicit version-tag runs must match both source version files, be newer than other reserved stable versions, and not have an existing release. They do not allocate a different version. Manual dispatch on a feature branch is refused.

## Companion version policy

Compared with the latest published stable release, non-Markdown changes under `ios/`, or changes to `handset/companion_version.py`, require:

- A strictly higher `MARKETING_VERSION` in `ios/project.yml`.
- A strictly higher integer `CURRENT_PROJECT_VERSION` in `ios/project.yml`.
- Exactly matching `COMPANION_VERSION` in `handset/companion_version.py`.

This deliberately fails safe even for an iOS configuration-only change. Desktop-only changes leave these fields alone, so a routine desktop patch does not falsely prompt an iPhone update. A companion version/build downgrade is rejected. The release manifest additionally verifies the packaged IPA's identity, protocol, and marketing version.

## Checks

Run locally where supported:

- `python -m unittest discover -s tests -v`
- `npm ci --ignore-scripts` and `npm test`
- `npx playwright install chromium`
- `npm run test:setup`, `npm run test:experience`, `npm run test:companion-update`, `npm run test:visual`, `npm run test:native`
- `cargo fmt --check --manifest-path native/Cargo.toml`
- `cargo test --locked --manifest-path native/Cargo.toml`
- On Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File tests/install_update.tests.ps1`, then `packaging/build.ps1` and `packaging/smoke.ps1`.

CI additionally compiles/packages the iPhone companion on macOS. Record platform skips and missing dependencies honestly. Physical-device signing, permissions, audio, notifications, mirroring, and whole-program performance are separate hardware checks, not guaranteed by CI.

The release helper is CI tooling, not a normal feature-development command. It creates a local commit. Its arguments are `--releases <JSON file from gh api --paginate --slurp> --source <exact checkout SHA> --output <environment output file> [--tag vX.Y.Z]`.

## Failure and recovery

Preparation rejects a source already reserved by a release tag, existing draft/public releases, version collisions, malformed metadata, and stale iOS versions. No version/tag/release is overwritten. A failed upload may leave a reserved tag or draft. Inspect the run, tag target, and uploaded assets first; do not blindly rerun or delete tags to reuse versions. Prefer a reviewed corrective commit/new version. Completing a retained draft requires explicitly verifying all assets came from its tested commit and authorization to publish. Merely rerunning publication is not a new test pass.

Generated release notes use GitHub's merged-change summary plus source/release commit provenance. `packaging/release-notes.md` is historical and is not copied verbatim into each future release.

## Existing installation behavior and limits

The existing updater in this fork checks GitHub latest at launch, then every six hours; transient errors retry after 15 minutes. It verifies the exact fork/version URL, SHA-256, and size. A supported packaged Windows executable stages a newer version and installs it **after normal Pane exit**. Reopen Pane afterward. A backup of the prior executable is retained; settings, saved phone pairings, browser profiles, and protected signing data are not replaced.

This is not an instant update of every installation. Source runs, other forks, builds without this updater, offline machines, unwritable install locations, interrupted exits, or blocked GitHub access may need manual installation or repair. An older build's own updater behavior determines whether it can upgrade. Windows releases do not automatically sign/install/renew the iPhone companion; that requires the existing USB/signing flow with the same Apple Account/team to preserve identity/files.
