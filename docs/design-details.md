# Pane interface details

The desktop and iPhone app both display **Pane**. The internal Swift target remains `PaneFiles` to keep the build and USB discovery contract stable.

The following references informed individual design decisions; Pane does not copy their branding or layouts.

| Reference examined | Specific detail | Applied in Pane |
| --- | --- | --- |
| [Linear: March 2026 interface refresh](https://linear.app/now/behind-the-latest-design-refresh) | Dimmer inactive navigation, compact tabs, fewer high-contrast separators and smaller icons | Graphite surfaces, one periwinkle action color, compact persistent Connection/Uploads tabs, soft section rules and consistent 15–20 px outline icons |
| [Panic Transmit transfer queue](https://help.panic.com/transmit/transfer-queue/) (an older-version guide, used as a pattern reference) | Transfer names, amounts and states live together; cancellation is attached to the affected queue item | A stable filename column, direction and size beneath it, status aligned at the right, and Cancel beside a queued item |
| [Microsoft Fluent: progress bars](https://fluent2.microsoft.design/components/web/react/core/progressbar/usage/) | Determinate progress where measurable, useful units, and specific errors at the point of failure | Byte counts, percent complete and a thin progress track; no invented time estimates; interrupted transfers retain an explanation |
| [Microsoft Fluent: tabs](https://fluent2.microsoft.design/components/web/react/core/tablist/usage) | Consistent tab formats, short noun labels and an explicit selected state | Labeled tabs with the same icon format, an accent underline, arrow/Home/End keyboard navigation and ARIA relationships |

Other implementation details:

- Navigation remains fixed while the content scrolls; the file list has a reserved scrollbar gutter.
- Long filenames truncate visually with the full name available on hover; text is inserted as text, not executable markup.
- Transfer figures use tabular numerals. An unchanged poll does not rebuild the file list or disturb text selection.
- Idle, connecting, connected and error states have distinct text; color is supplemental.
- Setup highlights the current step. Completed indications depend on actual device results, not elapsed time or clicking Next.
- The empty state explains what populates the list. Download-folder details and destination instructions are nearby but secondary.
- Buttons have visible focus rings, explicit disabled states, accessible names and hover/pressed states. Motion respects reduced-motion preferences.
- iPhone uses native grouped sections, scalable system type, full-width rows, recognizable SF Symbols, file-size labels, progress and native Share actions. It supports light and dark appearance.
- Volume controls remain in their original location beside the mirror. The desktop phone outline, dragging, proportional resize and fullscreen behavior are preserved.

Validation includes browser screenshots, real staging/cancellation requests, keyboard tabs, narrow-layout checks, and the Windows native-window test suite. Device installation and radio behavior are separate hardware acceptance checks.
