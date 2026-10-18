# Visual system

- Product register. Pure white content surface, quiet neutral sidebar, restrained warm-orange primary.
- Web UI tokens are OKLCH, anchored to hue 39–40; system Chinese sans-serif; 1px borders and 7–12px radii.
- Desktop sidebar 232px; editor and email preview in two columns. Below 992px use navigation drawer and editor/preview tabs; below 576px stack metadata and cards.
- Primary actions use explicit verbs, mail status always includes text. Motion 150–200ms only for state changes and respects reduced motion.
- Email is a separate presentation layer with conservative hex colors, inline styles and tables; never uses web CSS or scripts.

## Typography / readability (2026-10-17)

- Body, form inputs and rich text: 16px (1rem), preserved on mobile; no CSS zoom or transform scaling.
- Sidebar navigation and main actions: 15px; field labels and small actions: 14px; helper text: 13px; metadata/footer minimum: 12px. The 11px logo wordmark is decorative, not application copy.
- Section headings: 16–18px; page title: 32px (30px on phones).
- Normal inputs/selects: at least 48px high; compact controls 40px. Line-height, control padding and wrapping accompany the type scale.
- Email HTML remains separate and is not enlarged as a side effect of management UI styles.

- Submission destination is a single email address, independent of the sending SMTP account. Mail previews show a mailto action plus a copyable address; not a web upload link.

## Email reference-card theme (2026-10-18)

- Email only: pale cool-gray surround, white 760px rounded card, navy headline and coral underline; peach assignment/deadline panel; warm-orange mailto CTA.
- Desktop title 44px, body 19px, greeting 22px; mobile title 30px, body 17px with stacked metadata. Content and destination remain dynamic.
- Five project-authored PNG decorations, generated from SVG; data URI in sandbox preview, MIME CID in real email, with no remote image dependency.
- Tables and inline styles remain the baseline; media queries refine narrow layouts. Text and actions remain usable without images. Do not paste the reference screenshot as the email body.


## Roster workspace (2026-10-18)

- Scoped evolution of the class page only: white content, neutral toolbar/table header, warm-orange selection; compact class navigation instead of stacked cards. No decorative metrics, gradients or new dependencies.
- On viewports at least 992px wide and 640px high, `roster-active` enables a viewport-height flex shell. Header and warning remain in flow, the student list receives remaining height, its table header sticks, and pagination stays outside the scroll region. The class navigation scrolls independently. No hard-coded viewport subtraction.
- Below either bound, use a class select and ordinary document scrolling; add pagination above the table. At phone widths, stack the name and email inside a single table cell.
- Maintain 16px names, email addresses and search input on every size. Table labels/actions are 14px and helper text is 13px; strong focus indicators use the existing primary token. Text contrast samples pass 4.5:1.
- Page sizes: 20 (default), 50, 100. Filter the whole class before slicing. Keep management pagination separate from compose recipients. Dropdowns, modals, import confirmation and email styles retain their established behavior.
- No ornamental animation; hover/focus changes only, with existing reduced-motion support. Small-screen page changes scroll instantly to the toolbar and restore focus to the visible top pager.


## Import drawer (2026-10-18)

- Batch import alone uses a root-level Bootstrap end offcanvas: 720px desktop, full viewport below 768px, 220ms slide. Shared editing/delete/settings modals are unchanged.
- Fixed header with pinned target class, compact two-step indicator, one scroll body and fixed footer. The backdrop uses layer 1050 and drawer 1055, above navigation 1045; no clipping by the roster container. Reduced motion removes transitions.
- Step one shows one source tab at a time. Step two shows a compact result strip, collapsed column mapping, filtered 50-row preview and conditional explicit problem policies. No nested vertical table scroll and no repeated healthy-row status text.
- Preserve 16px text/input/email, 14px controls and 13px supplementary copy. Checked text contrast samples range from 4.518:1 to 15.044:1.
- Escape/backdrop use inline discard confirmation when dirty. Keyboard wraps within the drawer even at the document boundary; deferred focus handles backdrop mousedown. Closing restores the import trigger. Successful fast submits wait for the opening lifecycle before hiding.
- A dedicated import controller owns session/request generations, input source, captured class ID, preview freshness and commit outcomes; no browser persistence or real data in screenshots.


## Recipient search and selection (2026-10-18)

- Scoped to the compose recipient panel. Keep class select; replace the ambiguous heading badge with an explicit selected/total summary alongside the search input. Search/tools and hidden-selection notice sit outside the existing 260px list scroll region.
- White surface and subtle warm-orange selected rows; 18px native checkboxes with existing accent color, full-row click targets and strong focus. Names, emails and input remain 16px; phone layout stacks names/emails with wrapping. No avatars, decorative cards or pagination.
- Search is case-insensitive substring matching over full names/emails. Filtering never changes the authoritative selection Set. Bulk selection applies only to the filtered view, with matching-scope indeterminate state and a separate hidden-selected count.
- Do not rebuild or refocus the input while composing Chinese text. Commit search filtering at compositionend; search alone never dirties the notice or changes the email preview.
- Loading tracks a request generation and explicit all/subset/empty selection intent; retries retain that intent. Restore resets search, same-class refresh preserves it and intersects selected IDs with live students. A refresh does not select new imports.
- Pending or failed loads block send and draft-save so transient empty views cannot be persisted. Recheck selection after the asynchronous send-review preview and before final confirmation.

## Formal send confirmation drawer (2026-10-18)

- Formal sending alone uses a root-level Bootstrap end offcanvas: 720px desktop and full viewport below 768px. Test mail and all edit/delete dialogs remain on the shared modal.
- The fixed header states the frozen recipient count; one scrolling body orders sender details, the complete read-only roster, interval, then a collapsed sandboxed email sample; the fixed footer contains the acknowledgement and final action.
- The roster is rebuilt from the authoritative selected ID order, never the compose search result. Drawer search is display-only and paging is fixed at 20 without nested vertical scrolling. Names, subjects and complete email addresses wrap.
- Opening freezes the notice, SMTP profile identity, selected IDs and display names/emails. The preview and final create path reject late page changes; immediately before create, live student existence/name/email are compared with the frozen roster.
- Interval remains 1–60 seconds with a default of 3. Changing it clears acknowledgement; roster search and paging do not. Creating disables closing and controls.
- A create request receives one fixed idempotency key. An uncertain response remains explicitly pending and may only be retried manually with the same request/key. Once a job ID exists, subsequent recovery only reads that job and never creates again.
- Back returns to the compose recipient section without clearing compose search or selection. A normal reopen rebuilds the snapshot and clears acknowledgement; unresolved create/read recovery state is retained.

## Send policy controls (2026-10-18)

- Preserve the restrained white/warm-orange product register. Shared native radio segments expose 1–5 lanes; an adjacent numeric input exposes a 1–60 second per-lane cooldown. Default: one lane, three seconds. Body and input text remain 16px; labels 14px and supplementary copy 13px.
- Mailbox editing adds a single separated defaults section; the existing mailbox modal alone gets a scrollable body with reachable header/footer. Other generic modals are unchanged. Mailbox cards and history display a compact textual policy summary.
- The send drawer labels the source as “沿用邮箱默认” or “仅本次修改”; an inline reset action restores the frozen mailbox defaults. Either control clears acknowledgement. Search/paging never changes policy or acknowledgement. Uncertain create outcomes lock policy and retain identical request bytes/key.
- Desktop aligns radio segments and interval side-by-side. At phone widths the controls stack, all five segments remain available, and text wraps without reducing font size. No gradients, decorative metrics, new dependencies or speed promises.
- Native arrow-key selection, visible focus, reduced motion and text contrast were browser-tested. Sampled text contrast: 4.518:1 minimum. Fixed 720px drawer below 768px becomes full viewport; tested at 375/320px and short desktop heights.
