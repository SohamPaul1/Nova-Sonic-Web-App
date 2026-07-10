# Frontend Suggestions — "Records Desk" (live DB tables in the right panel)

> **For:** the developer implementing the right-panel UI.
> **Status:** design + reference implementation. Nothing here has been applied yet.

---

## 1. Goal & the one hard constraint

The two-column layout in `static/index.html` (commit `9b855eb`) left the **`right-panel` an
empty dark card** — roughly 70% of the screen on desktop. Fill it with the four database
tables the agent actually uses:

| Order | Slug (public)          | DB table               | Role       |
|-------|------------------------|------------------------|------------|
| 1     | `new_subscribers`      | `new_user_details`     | **frontier** |
| 2     | `existing_subscribers` | `existing_user_details`| **frontier** |
| 3     | `prospects`            | `new_customers`        | secondary  |
| 4     | `renewals`             | `plan_extension`       | secondary  |

`call_analytics` is **intentionally excluded** (not used by any tool).

The agent writes to these tables **mid-call** (`tools.py`: `note_subscription_request`,
`send_renewal_request`, `follow_up_user`), so the panel is designed as a live **"Records
Desk"** — the operator watches records appear as Raj books them.

> ### 🚨 THE HARD CONSTRAINT
> **The voice workflow must not break.** Do **not** touch: the `/ws` WebSocket handler,
> `BedrockStreamManager`, the audio / VAD / transcript-reveal JavaScript (the existing
> `<script>` block), or `tools.py`. Every change below is additive and isolated.

---

## 2. Why a separate HTTP endpoint (architecture)

The voice path is a **stateful WebSocket** driving a Bedrock bidirectional stream. Table data
is a **stateless read**. Putting them on separate transports *guarantees* the voice workflow
can't be affected: the panel talks to a plain `GET` endpoint via `fetch()`; nothing about the
WS path changes.

**Reuse, don't reinvent:**
- **`db.fetch_all(query, params)`** (`db.py:76`) already returns `RealDictCursor` rows as a
  list of dicts, borrows a connection from the pool, and is safe to call alongside the
  concurrent WS sessions and tool calls — that pool is exactly why (`db.py` module docstring).
- **Serialization gotcha (learned the hard way):** these tables have `date`/`timestamp`
  columns (`valid_till`, `extended_date`, `call_date`, `start_date`, `startdate`). Plain
  `json.dumps(rows)` raises `TypeError: Object of type date is not JSON serializable`. Always
  serialize with **`json.dumps(..., default=str)`** (the same fix used for tool results).

---

## 3. Backend — `main.py` (one endpoint, nothing else)

### 3a. Imports to add

Today only `HTMLResponse` is imported (`main.py:37`). Add `JSONResponse` and `fetch_all`:

```python
from fastapi.responses import HTMLResponse, JSONResponse
from db import fetch_all
```

### 3b. Whitelist map (module level, near the other config)

The slug→(table, order-by) map is the **only** thing that reaches SQL, so a request can never
inject a table name:

```python
# Public slug -> (real table name, safe ORDER BY). The frontend only ever sends
# a slug; the table name and ordering come from THIS map, never from the request,
# so interpolating them into SQL below is injection-safe.
TABLE_VIEWS = {
    "new_subscribers":      ("new_user_details",      "start_date DESC NULLS LAST"),
    "existing_subscribers": ("existing_user_details", "valid_till DESC NULLS LAST"),
    "prospects":            ("new_customers",          "startdate DESC NULLS LAST"),
    "renewals":             ("plan_extension",         "call_date DESC NULLS LAST"),
}

# Column render order per view (so NULL-heavy rows still get a stable layout).
TABLE_COLUMNS = {
    "new_subscribers":      ["user_name", "phone_number", "address", "plan",
                             "start_date", "verification_status", "payment_status", "user_status"],
    "existing_subscribers": ["user_name", "contact_number", "address", "plan",
                             "valid_till", "status"],
    "prospects":            ["user_name", "contact_number", "address",
                             "intended_plan", "startdate", "message"],
    "renewals":             ["id", "user_name", "contact_number", "address",
                             "requested_plan", "extended_date", "payment_status",
                             "call_date", "verification_status", "interest"],
}
```

### 3c. The endpoint (add next to `@app.get("/")`, `main.py:937`)

```python
@app.get("/api/tables/{slug}")
async def get_table(slug: str):
    """Read-only snapshot of one whitelisted DB table for the Records Desk panel.

    Separate from the /ws voice path on purpose — a stateless read that can never
    affect the Bedrock stream. Only whitelisted slugs reach SQL.
    """
    view = TABLE_VIEWS.get(slug)
    if not view:
        return JSONResponse({"error": "Unknown table."}, status_code=404)

    table, order_by = view
    try:
        # fetch_all is sync/blocking (psycopg2) — offload like the tool calls do,
        # so the event loop serving the WebSocket audio is never blocked.
        rows = await asyncio.to_thread(fetch_all, f"SELECT * FROM {table} ORDER BY {order_by}")
        payload = {"slug": slug, "columns": TABLE_COLUMNS[slug], "rows": rows}
        # default=str: date/datetime/Decimal columns aren't JSON-native and would
        # otherwise raise TypeError (same fix as the tool-result serialization).
        return JSONResponse(content=json.loads(json.dumps(payload, default=str)))
    except Exception as e:
        logger.error(f"/api/tables/{slug} failed: {e}")
        return JSONResponse({"error": "Couldn't load records."}, status_code=500)
```

> `json.loads(json.dumps(..., default=str))` hands `JSONResponse` a fully JSON-safe dict.
> (Alternatively return `Response(json.dumps(payload, default=str), media_type="application/json")`.)

**Optional niceties** (not required): a `?limit=` cap for very large tables, and a
`GET /api/tables` returning the slug→label list so the frontend list isn't hardcoded.

---

## 4. Frontend — `static/index.html` (right panel only)

Everything below is **additive and scoped**. Do not modify the existing voice `<script>` or
its globals. New JS goes in a **new `<script>` wrapped in an IIFE** so nothing leaks.

### 4a. Markup — replace the empty `.right-panel` (`index.html:660`)

```
right-panel
 └─ records-desk                (flex column, fills the panel)
    ├─ desk-masthead            "RECORDS DESK" eyebrow + current table title + row-count
    ├─ desk-nav                 ‹ prev  ·  edition dots ●●○○  ·  next ›
    ├─ desk-table-scroll        <table><thead sticky><tbody>…  (horizontal scroll if wide)
    └─ desk-footer              "⟳ auto · last synced Ns ago"  +  ⟳ manual refresh button
```

One table is visible at a time; prev/next (and the dots) cycle the 4 slugs in the order in
the table above — **frontier tables first**.

### 4b. New scoped `<script>` responsibilities (IIFE, after the existing one)

```js
(function recordsDesk() {
  const VIEWS = [
    { slug: 'new_subscribers',      label: 'New Subscribers',      subtitle: 'Fresh sign-ups' },
    { slug: 'existing_subscribers', label: 'Existing Subscribers', subtitle: 'Active readers' },
    { slug: 'prospects',            label: 'Prospects',            subtitle: 'Interested leads' },
    { slug: 'renewals',             label: 'Renewals',             subtitle: 'Extension requests' },
  ];
  // ... state: activeIndex, lastRowKeys (Set), lastSyncedAt, timer ...
})();
```

- **`loadTable(slug)`** → `fetch('/api/tables/' + slug)` → build `<thead>`/`<tbody>` from
  `columns` + `rows`. Humanize headers via a label map (below); render `null`/`''` as a muted
  `—`.
- **Navigation:** prev/next + edition-dot click handlers change `activeIndex`, reset the
  seen-row set, and re-render.
- **Auto-refresh (~5s):** `setInterval` re-fetches the *current* slug. Diff each row against
  the previous render by a **stable key** (see 4d) → rows whose key wasn't present last tick
  get a `.row-new` class → CSS gold flash that fades. Update "last synced Ns ago".
- **Manual refresh** button calls the same loader and resets the "synced" timer.
- **Kick-off:** on `DOMContentLoaded`, `loadTable(VIEWS[0].slug)` and start the interval —
  **independent of the voice session**, so the desk is populated before the mic starts.
- **Guard rails:** a failed/500 fetch renders an inline state inside `desk-table-scroll`
  ("Couldn't reach the records desk. Retrying…"), **never** `alert()`, **never** throws — the
  interval just keeps trying. Pause polling while `document.hidden` to avoid idle load
  (optional but nice).

### 4c. Header label map (humanize `SELECT *` columns)

```js
const LABELS = {
  user_name: 'Name', phone_number: 'Phone', contact_number: 'Phone', address: 'Address',
  plan: 'Plan', intended_plan: 'Intended Plan', requested_plan: 'Requested Plan',
  start_date: 'Start', startdate: 'Start', valid_till: 'Valid Till', extended_date: 'Extended',
  call_date: 'Called', verification_status: 'Verification', payment_status: 'Payment',
  user_status: 'Status', status: 'Status', interest: 'Interest', message: 'Message', id: '#',
};
```

### 4d. Stable row key for the "new row" diff

Use identity columns, not the whole row (so a status change doesn't re-flash the row):

- `new_subscribers` / `prospects`: `phone_number|contact_number` + `plan|intended_plan`
- `existing_subscribers`: `contact_number`
- `renewals`: `id` (has a real PK)

Keep last tick's keys in a `Set`; any row whose key is absent from it is "fresh ink" → flash.

---

## 5. Visual spec

**Reuse the existing `:root` tokens — do not introduce a new palette.** The left panel already
established a **dark indigo glassmorphic** identity (`--bg-primary #08081a`, `--accent
#6c63ff`, `--accent-secondary #a855f7`, `#60a5fa`, plus `--success`/`--warning`/`--error`).
The right panel must read as the same product. **Avoid** the generic "cream broadsheet"
newspaper look — it would clash with the established dark left panel.

**Signature element (the one memorable thing):** the **"edition" ledger navigation** — each
table is a register you flip through, with a masthead label and a live **"fresh ink" gold
flash** (`--warning #fbbf24`) on rows the agent just wrote. This single device ties the
newspaper metaphor to the live-writes behavior. Keep everything else quiet.

- **Type:** reuse the `Inter` stack for data. Give the masthead label the existing gradient
  `.title` treatment so it echoes "The Adamas Times" at the top; use the uppercase,
  letter-spaced `.subtitle` / `.panel-title` style for the "Records Desk" eyebrow.
- **Table:** hairline row separators (`--border-subtle`); **sticky `<thead>`** with
  `--text-secondary` uppercase micro-labels; zebra striping via `--bg-card`;
  `font-variant-numeric: tabular-nums` on phone/date cells so columns align.
- **Status pills:** render `pending`/`verified`/`Active`/`interested`/`not interested` as
  small rounded pills colored from `--warning` / `--success` / `--error` (map value → color).
- **Fresh-ink flash:**
  ```css
  @keyframes rowFlash { from { background: rgba(251,191,36,0.25); } to { background: transparent; } }
  .row-new { animation: rowFlash 2.5s ease-out; }
  @media (prefers-reduced-motion: reduce) { .row-new { animation: none; } /* skip flip transition too */ }
  ```
- **Empty table:** reuse the `.transcript-empty` pattern — centered, muted, "No records yet."
- **Responsive:** the panel is already hidden under the 900px breakpoint
  (`.right-panel { display: none }`, `index.html:570`), so mobile needs no extra work.
- **CSS hygiene:** prefix all new classes (`desk-*`, `records-*`) and keep them inside the
  existing `<style>` block; don't reuse generic names that could collide with `.container`,
  `.header`, `.message`, etc.

---

## 6. 🚨 Security note (read before deploying beyond an internal machine)

`GET /api/tables/{slug}` is **unauthenticated** and returns **customer PII** — full phone
numbers and addresses — to anyone who can reach the server. This is acceptable for an internal
helpdesk tool on a trusted network, but **before any wider deployment**, do one of:

- gate the endpoint behind the same session/auth the operator already uses (or HTTP basic
  auth / a shared token / same-origin check), and/or
- **mask** on the server: phone → `98••••1105`, truncate `address`. (Masking in the browser is
  cosmetic only — the raw data still crosses the wire.)

Track this as a follow-up; it's out of scope for the initial internal build.

---

## 7. Verification checklist

1. **Voice unaffected (most important).** `python main.py` (port 8009), open the page, click
   power → Raj greets, mic works, transcript reveals, barge-in works, and a status/renewal
   tool call still succeeds. `/ws` and `Agent.log` behavior unchanged.
2. **Endpoint.** `curl -s localhost:8009/api/tables/new_subscribers | head` → JSON with
   `columns` + `rows`; date columns serialize (no 500). Hit all four slugs; an unknown slug → 404.
3. **Panel.** Desk loads the first table on page load (before starting a session); prev/next
   and edition dots flip through all four; wide tables scroll horizontally; an empty table
   shows the empty state.
4. **Live writes.** With a session running, complete a `noteSubscriptionRequest` (or renewal)
   through the agent → within ~5s the new row appears in the matching table with the gold flash.
5. **Resilience.** Stop the DB (or force a 500) → panel shows the inline retry state and keeps
   polling; the voice UI stays fully functional. At <900px the right panel is hidden.

---

## 8. Files touched

| File | Change |
|------|--------|
| `main.py` | Add `TABLE_VIEWS` / `TABLE_COLUMNS` + `GET /api/tables/{slug}` near `@app.get("/")` (`:937`); add `JSONResponse` + `fetch_all` imports (`:37`). **No `/ws` or `BedrockStreamManager` changes.** |
| `static/index.html` | Replace empty `.right-panel` (`:660`) with the records-desk markup; add one new scoped `<script>` before `</body>`; add `desk-*` CSS to the existing `<style>`. **No changes to the voice `<script>`.** |
| `db.py` | **Read-only reuse** of `fetch_all` (`:76`). No edits. |
| `tools.py` | Untouched. |
