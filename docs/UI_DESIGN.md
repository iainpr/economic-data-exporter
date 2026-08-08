# 0.5.0 UI design foundation

Version 0.5.0 reorganizes the desktop interface as a research workspace rather than a single long form.

## Interaction model

1. **Select** providers in the persistent left sidebar.
2. **Build queue** by pasting multiple identifiers or using metadata search.
3. **Preview & clean** retrieved data before committing to Excel.
4. **Export** to a user-selected local workbook.

## UX principles

- Keep source selection visible while building a request.
- Make the primary action visually distinct and use action labels that describe the consequence.
- Keep destructive/secondary actions visually subordinate.
- Show the request count continuously so users know what will be retrieved.
- Use tooltips/descriptions for providers instead of forcing users to remember capabilities.
- Keep credentials close to the provider that requires them and make their storage state visible.
- Treat preview/cleaning as a reversible derived view; raw provider observations remain canonical.
- Avoid decorative dashboard elements that compete with the extraction workflow.

## Runtime note

The UI is implemented with PySide6 and a Fusion base style plus a local stylesheet. Network retrieval and Excel generation remain in worker threads.


## 0.5.0 refinement

The sidebar was redesigned as a coherent dark navigation rail: every source is an individually styled selectable control, credential controls use the same dark-card language, section labels are explicitly transparent, and sidebar buttons use dark secondary / blue primary treatments. The main workspace remains light so the export workflow has a strong visual hierarchy.

The design goal is consistent visual semantics rather than decorative dashboard elements: dark = navigation and configuration, white = working surface, blue = primary action / active state, red = destructive or failure action, green = credential status.
