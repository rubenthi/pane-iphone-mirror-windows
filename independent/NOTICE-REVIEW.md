# Pending notice review

Local review on 2026-11-08 found that all 31 resolved third-party packages pass
the declared no-GPL/LGPL/AGPL policy. That does not establish complete notices
or ownership. The strict notice collector currently blocks nine packages.

All files below are the exact `LICENSE-MIT` files from the crates.io registry
versions in `native/Cargo.lock`. Their full MIT bodies are present. Seven omit
a copyright line, while two contain years without a named holder. This is a
manual-review trigger in our tooling, not a finding that these dependencies
are GPL, unlicensed or infringing.

| Package/version | Upstream copyright header | SHA-256 of original file |
| --- | --- | --- |
| equivalent 1.0.3 | `Copyright (c) 2016--2023` | `7365cc8878a1d7ce155a58c4ca09c3d7a6be413efa5334a80ea842912b669349` |
| indexmap 2.14.2 | `Copyright (c) 2016--2017` | `ecc269ef87fd38a1d98e30bfac9ba964a9dbd9315c3770fed98d4d7cb5882055` |
| proc-macro2 1.0.107; quote 1.0.47; serde_core and serde_derive 1.0.229; syn 2.0.119 and 3.0.9; unicode-ident 1.0.27 | None | `23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3` |

Cargo author metadata and adjacent README license wording do not by themselves
establish a copyright-holder statement. No invented attribution or automatic
exception was added. Preserve original license files; review the available
source and applicable notice obligations before approving a distribution
notice. `unicode-ident` also has mandatory Unicode terms that must be retained
even when its MIT alternative is selected.

Earlier ignored snapshots were generated before this stricter check. They are
historical review artifacts and are not a passing current result. No passing
notice snapshot is produced until the current collector's entire graph passes.
