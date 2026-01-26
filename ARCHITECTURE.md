# Artifact Capture UI Architecture

This app has three primary “record browsing” surfaces:

- **Recent**: browse most-recent records with pagination and multiple display modes.
- **Review**: browse subsets of records selected by “index field” buttons, with the same pagination + display modes.
- **Edit**: edit a single record (metadata + images) and manage images.

## Template layering

Top-level pages own **loop structure** and **view switching** (table/paragraph/grid).  
Partials render *one record* or *a table of records* and should avoid controlling outer loop structure.

```
recent.html   review.html
   │             │
   ├─(table)─────┼──► _record_table.html      (renders many records in a table)
   │             │
   ├─(paragraph)─┼──► loop rows → _record_card.html  (renders one record “card”)
   │             │
   └─(grid)──────┼──► loop rows → _record_grid.html  (renders one record “tile”)
```

## Record rendering partials

### `_record_card.html` (paragraph mode)
A single record card composed of:
- metadata key/value table
- image grid (via `_admin_images.html`)
- optional edit actions (Edit page)

### `_record_grid.html` (grid mode)
A compact record tile:
- image grid (via `_admin_images.html`)
- “hanging indent” text built from `meta.result_grid` fields (no labels)

### `_record_table.html` (table mode)
A table view of many records (labels as headers).

### `_admin_images.html`
The shared image-grid renderer used across paragraph/grid/edit contexts.
