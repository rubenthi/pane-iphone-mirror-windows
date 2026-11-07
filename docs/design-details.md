# Pane interface details

The desktop and iPhone app both display **Pane**. The internal Swift target remains `PaneFiles` to keep the build and USB discovery contract stable.

The following references informed individual design decisions; Pane does not copy their branding or layouts.

| Reference examined | Specific detail | Applied in Pane |
| --- | --- | --- |
| [Linear: March 2026 interface refresh](https://linear.app/now/behind-the-latest-design-refresh) | Dimmer inactive navigation, compact tabs, fewer high-contrast separators and smaller icons | Compact persistent Connection/Uploads/Settings tabs, soft section rules and consistent outline icons; the current revision uses blue glass surfaces matched to the existing icon |
| [Panic Transmit transfer queue](https://help.panic.com/transmit/transfer-queue/) (an older-version guide, used as a pattern reference) | Transfer names, amounts and states live together; cancellation is attached to the affected queue item | A stable filename column, direction and size beneath it, status aligned at the right, and Cancel beside a queued item |
| [Microsoft Fluent: progress bars](https://fluent2.microsoft.design/components/web/react/core/progressbar/usage/) | Determinate progress where measurable, useful units, and specific errors at the point of failure | Byte counts, percent complete and a thin progress track; no invented time estimates; interrupted transfers retain an explanation |
| [Microsoft Fluent: tabs](https://fluent2.microsoft.design/components/web/react/core/tablist/usage) | Consistent tab formats, short noun labels and an explicit selected state | Short labeled tabs with an inset selected surface, arrow/Home/End keyboard navigation and ARIA relationships |

Other implementation details:

- Main menus fit the default phone size; settings use separate pages and transfer history shows two items per page. Overflow remains accessible at high zoom or small sizes. Navigation and the opt-in background switch stay fixed.
- Long filenames truncate visually with the full name available on hover; text is inserted as text, not executable markup.
- Transfer figures use tabular numerals. An unchanged poll does not rebuild the file list or disturb text selection.
- Idle, connecting, connected and error states have distinct text; color is supplemental.
- Setup highlights the current step. Completed indications depend on actual device results, not elapsed time or clicking Next.
- The empty state explains what populates the list. Download-folder details and destination instructions are nearby but secondary.
- Buttons have visible focus rings, explicit disabled states, accessible names and hover/pressed states. Motion respects reduced-motion preferences.
- iPhone uses native grouped sections, scalable system type, full-width rows, recognizable SF Symbols, file-size labels, progress and native Share actions. It supports light and dark appearance.
- Volume controls remain in their original location beside the mirror. The desktop phone outline, dragging, proportional resize and fullscreen behavior are preserved.

Validation includes browser screenshots, real staging/cancellation requests, keyboard tabs, narrow-layout checks, and the Windows native-window test suite. Device installation and radio behavior are separate hardware acceptance checks.


The current redesign applies the requested frontend-design skill. Direct access to `rubenthi.com` still returns proxy HTTP 403; the web reader also could not open it. The user supplied verified samples from the published ChatGPT Site's production screenshot. The Sites connector confirmed the matching published portfolio. These are representative sampled colors, **not exact source CSS tokens**:

| Reference sample | Role in the darker desktop adaptation |
| --- | --- |
| Ivory `#FBFAF6` | Primary text |
| Deep blue-green `#132B35` | Button text and the glass hue |
| Charcoal-green `#25312F` | Neutral surface direction |
| Muted gray-green `#666B64` | Lightened to `#A5B5AA` for readable dark-mode secondary text |
| Pale sage `#E6EDE5` | Stronger sage `#D3E5C7` for links, focus and selected controls |
| Soft background `#F2F3ED` | Warm ivory highlights on near-black teal `#080F11` |

Desktop typography is locally bundled **Commissioner**, a compact variable family with distinct letterforms. The single Latin file is 36.7 KB; the license ships alongside it. There is no font CDN or animation library. Text and secondary text against the brightest solid drawer color (`#172B2B`) have calculated contrast ratios of 14.19:1 and 6.91:1; primary button text against the darker gradient stop is 9.29:1. These token comparisons do not replace a full accessibility audit. The approved blue icon remains unchanged. This refinement does not change the native iOS interface.

Dropdowns progressively enhance the existing select elements, preserving form IDs, values, preference writes and device state. One shared listbox supports keyboard arrows, Home/End, typeahead, Enter, Escape, Tab and pointer selection. Lists are bounded to the phone surface, close on navigation/resize and react to changed device options without an idle timer. Labels and descriptions remain accessible; the native select remains the no-JavaScript fallback.

Required steps start as short, small hints. Enabling phone notifications expands a larger, high-contrast instruction to enable **Share System Notifications** on the iPhone. Enabling audio reveals the iPhone output-selection step. Background mode exposes a direct link to phone notifications when they are still off. Preview text explains that message content will appear on the PC when enabled. These are instructions, not confirmations that an OS permission or route is already enabled.

Motion responds to pointer or keyboard actions: the rail's connected island, dropdown caret and list, settings-row cue, icon movement and switch thumb. Reduced motion removes transitions and animations. No pointer-tracking loop or idle animation is added. At narrow sizes, tabs adapt and content can scroll; the default main menus fit without scrolling.

The three-line handle expands into a single connected island containing minimize, maximize/restore and close. Icons react to hover/press and all motion respects Reduce Motion. A single custom tooltip supports keyboard focus and pointer hover. Setup and the feature tour remain separate: clicking through a tour cannot mark a device as configured. Signing options and troubleshooting expand on demand, leaving the main install action visible.
