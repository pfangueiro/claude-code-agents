---
name: browser-testing
description: E2E browser testing with Playwright MCP. Visual regression, responsive design, cross-browser testing, codegen sessions. Auto-activates on e2e test, visual regression, screenshot test, browser test, Playwright, responsive test, cross-browser, visual verification.
---

# Browser Testing with Playwright MCP

Comprehensive patterns for end-to-end browser testing, visual regression, and responsive design verification using the Playwright MCP server.

## First: prefer the repo's own test suite

This skill auto-activates on the bare word "Playwright", including in repos that already have a Playwright suite. Before hand-driving any MCP tool, check for one:

- `playwright.config.{ts,js,mjs}`, a `tests/` / `e2e/` directory, or a `test:e2e` / `playwright` script in `package.json`.

If a suite exists, **run it** (the repo's script, or `npx playwright test`) and report its actual result. A suite is reproducible, runs in CI, and asserts far more than a hand-driven MCP session can. Use the MCP tools below only to (a) debug a failure the suite surfaced, (b) explore a page interactively, or (c) build coverage where no suite exists.

Do not re-implement an existing test by hand, and never present a hand-driven MCP walkthrough as equivalent to a suite run — if the suite was not run, say so.

## Available Playwright MCP Tools

Names below are the full MCP tool names, as invoked.

### Navigation & State
- `mcp__playwright__playwright_navigate` — Open a URL (set `browserType`, `width`, `height`, `headless`)
- `mcp__playwright__playwright_go_back` / `mcp__playwright__playwright_go_forward` — History navigation
- `mcp__playwright__playwright_resize` — Change viewport (manual or 143+ device presets: `iPhone 13`, `iPad Pro`, `Galaxy S24`, etc.)

### Interaction
- `mcp__playwright__playwright_click` — Click an element (CSS selector)
- `mcp__playwright__playwright_fill` — Fill an input field
- `mcp__playwright__playwright_select` — Select dropdown value
- `mcp__playwright__playwright_hover` — Hover over element
- `mcp__playwright__playwright_drag` — Drag element to target
- `mcp__playwright__playwright_press_key` — Press keyboard key
- `mcp__playwright__playwright_upload_file` — Upload file to input

### Inspection
- `mcp__playwright__playwright_screenshot` — Capture page or element screenshot (with `fullPage`, `selector`, `savePng`, `downloadsDir`)
- `mcp__playwright__playwright_get_visible_text` — Get all visible text on page
- `mcp__playwright__playwright_get_visible_html` — Get HTML (options: `cleanHtml`, `minify`, `removeScripts`, `selector`)
- `mcp__playwright__playwright_console_logs` — Retrieve browser console logs (filter by type: error, warning, etc.)
- `mcp__playwright__playwright_evaluate` — Execute arbitrary JavaScript in browser

### HTTP API Testing
- `mcp__playwright__playwright_get` / `mcp__playwright__playwright_post` / `mcp__playwright__playwright_put` / `mcp__playwright__playwright_patch` / `mcp__playwright__playwright_delete` — Direct HTTP operations with auth headers

### Code Generation
These four are the only tools with no `playwright_` infix — the name is `mcp__playwright__start_codegen_session`, not `..._playwright_start_codegen_session`.

- `mcp__playwright__start_codegen_session` — Begin recording interactions as Playwright test code (requires `options.outputPath`)
- `mcp__playwright__end_codegen_session` — Generate the test file from recorded actions (requires `sessionId`)
- `mcp__playwright__get_codegen_session` — Check session status (requires `sessionId`)
- `mcp__playwright__clear_codegen_session` — Discard without generating (requires `sessionId`)

### Response Validation
- `mcp__playwright__playwright_expect_response` — Start waiting for an HTTP response. Required: `id` (an arbitrary handle you choose) and `url` (pattern). Registers the wait; does not block.
- `mcp__playwright__playwright_assert_response` — Await that response. Required: `id`. Optional: `value` — a substring that must appear in the JSON body.

**Neither tool can assert an HTTP status code — there is no status parameter.** Two consequences, both fail-closed:

- **Never call `assert_response` with only an `id`.** With no `value`, the server reports success for *any* response it received: a 401, 403 or 500 comes back as "Response assertion ... successful" with the status merely *printed* in the message, not checked. A failed login then reads as a green E2E. Always pass `value`.
- **`value` must be a substring that appears ONLY on success** (a token field name, the user id, `"status":"ok"`). A string that also occurs in the error body proves nothing. If no success-only substring exists, this tool cannot verify the call — assert the outcome another way (e.g. `mcp__playwright__playwright_get_visible_text` for an element that renders only when authenticated) and report the response as *not verified* rather than as a pass.

`value` is matched as a plain substring against `JSON.stringify(body)`, and the body is parsed as JSON — a non-JSON response makes the assertion error out.

## Patterns

### E2E Test: User Journey
```
1. mcp__playwright__playwright_navigate → target URL
2. mcp__playwright__playwright_fill → username/password fields
3. mcp__playwright__playwright_expect_response → id: "auth", url: "**/api/auth**"
   (MUST precede the click — the wait is registered here; a response that
    fires before this call is never seen)
4. mcp__playwright__playwright_click → submit button
5. mcp__playwright__playwright_assert_response → id: "auth", value: "\"authenticated\":true"
   (`value` is mandatory — with only `id`, a 401 is reported as success)
6. mcp__playwright__playwright_screenshot → capture authenticated state
7. mcp__playwright__playwright_get_visible_text → verify welcome message
```

Replace `"\"authenticated\":true"` with whatever substring your auth endpoint returns **only** on success.

### Visual Regression: Screenshot Comparison

**The Playwright MCP server has no image comparator** — no baseline store, no diff, no threshold. `mcp__playwright__playwright_screenshot` only captures. The comparison step must be an external tool, or the comparison is not happening.

```
1. mcp__playwright__playwright_resize → pin an exact viewport (both runs must match)
2. mcp__playwright__playwright_navigate → target page
3. mcp__playwright__playwright_screenshot → name: "homepage", savePng: true,
     downloadsDir: "<repo>/.screenshots/baseline"
4. [Make code changes]
5. mcp__playwright__playwright_navigate → same page (fresh load)
6. mcp__playwright__playwright_screenshot → name: "homepage", savePng: true,
     downloadsDir: "<repo>/.screenshots/current"
7. Run an external comparator with an explicit threshold, e.g. ImageMagick:
     compare -metric AE .screenshots/baseline/homepage.png \
                        .screenshots/current/homepage.png diff.png
   (prints the differing-pixel count; requires ImageMagick installed)
```

Fail-closed rules:

- **Decide the pass threshold before running.** "Looks fine" is not a threshold.
- **A missing baseline is a FAIL, not a pass.** Recording a first baseline is a separate, deliberate step — never let "nothing to compare against" report green.
- **Pin the viewport and use the same `fullPage` value for both captures.** A size mismatch makes the comparator error out; treat that error as a FAIL.
- **A comparator that did not run, is not installed, or errored is a FAIL.** Report "not verified" — never downgrade it to a pass.
- **Never report a visual-regression pass from eyeballing two screenshots.** Model inspection of two PNGs is not a diff; if no comparator ran, the honest result is "not verified".

### Responsive Design Testing
```
1. mcp__playwright__playwright_navigate → target page
2. mcp__playwright__playwright_resize → device: "iPhone 13" (375x812)
3. mcp__playwright__playwright_screenshot → name: "mobile"
4. mcp__playwright__playwright_resize → device: "iPad Pro 11" (834x1194)
5. mcp__playwright__playwright_screenshot → name: "tablet"
6. mcp__playwright__playwright_resize → width: 1920, height: 1080
7. mcp__playwright__playwright_screenshot → name: "desktop"
```

### Form Validation Testing
```
1. mcp__playwright__playwright_navigate → form page
2. mcp__playwright__playwright_fill → invalid email
3. mcp__playwright__playwright_click → submit
4. mcp__playwright__playwright_get_visible_text → check for error messages
5. mcp__playwright__playwright_console_logs → type: "error" (check for JS errors)
6. mcp__playwright__playwright_fill → valid data
7. mcp__playwright__playwright_expect_response → id: "submit", url: "**/api/submit**"
   (register the wait BEFORE the click that triggers it)
8. mcp__playwright__playwright_click → submit
9. mcp__playwright__playwright_assert_response → id: "submit", value: "\"created\":true"
   (success-only substring; omitting `value` would pass on a 422 validation error)
```

### Codegen: Record Test from Manual Actions
```
1. mcp__playwright__start_codegen_session → options: { outputPath: "/tests/e2e/" }
2. mcp__playwright__playwright_navigate → target URL
3. mcp__playwright__playwright_click → interact with elements
4. mcp__playwright__playwright_fill → fill forms
5. mcp__playwright__end_codegen_session → sessionId from step 1; writes the test file to outputPath
```

### Cross-Browser Testing
```
1. mcp__playwright__playwright_navigate → url, browserType: "chromium"
2. mcp__playwright__playwright_screenshot → name: "chrome-result"
3. mcp__playwright__playwright_close
4. mcp__playwright__playwright_navigate → url, browserType: "firefox"
5. mcp__playwright__playwright_screenshot → name: "firefox-result"
6. mcp__playwright__playwright_close
7. mcp__playwright__playwright_navigate → url, browserType: "webkit"
8. mcp__playwright__playwright_screenshot → name: "safari-result"
```

## Best Practices

- Run the repo's existing Playwright suite before hand-driving MCP tools (see the gate at the top)
- Always `mcp__playwright__playwright_close` when done — releases browser resources
- Use `selector` option on screenshots to capture specific components
- Set `headless: true` for CI/automated runs, `false` for debugging
- Use `mcp__playwright__playwright_console_logs` with `type: "error"` after interactions to catch JS errors
- Register `mcp__playwright__playwright_expect_response` BEFORE the action that triggers the request
- Always pass `value` to `mcp__playwright__playwright_assert_response` — without it, a 401/500 passes
- Use device presets for accurate mobile/tablet testing (includes user-agent + touch emulation)
- For iframes, use `mcp__playwright__playwright_iframe_click` and `mcp__playwright__playwright_iframe_fill`

## When to Use

- **After implementing UI changes** — verify visual correctness
- **During investigate** — reproduce UI bugs with exact browser state
- **For accessibility** — check WCAG compliance with visual + text inspection
- **For API testing** — use HTTP tools for direct endpoint verification
- **For regression** — screenshot before/after code changes

## Related

- `test-automation` agent — generates test suites (uses Playwright for E2E)
- `frontend-specialist` agent — implements UI components (uses Playwright for verification)
- `investigate` skill — Phase 2 (REPRODUCE) uses Playwright for UI bug reproduction
