# Multi-rename

**Multi-rename …** (Ctrl+M) renames the selected entries according to a pattern. The table immediately shows **old name** and **new name**; conflicts are marked red and are not renamed.

## Pattern
- **Name** and **extension** are built from placeholders:
  - `[N]` name without extension, `[E]` extension
  - `[N1-5]` characters 1 to 5, `[N3-]` from character 3
  - `[C]` counter, `[D]` date/time

  The “Insert placeholder” menu helps with this.
- **Case**: UPPER, lower, first letter upper or each word capitalised, optionally including the extension.

## Search and replace
As plain **text**, with **wildcards** (`*`, `?`) or as a **regular expression**; optionally all occurrences and case-sensitive.

## Counter and date
- **Counter**: start, step and digits (e.g. 001).
- **Date**: based on now, last modification or creation date. The format uses JJJJ, MM, TT, hh, mm, ss.

## Profiles and undo
Settings can be saved as a **profile**. **Undo last rename** restores the old names.
