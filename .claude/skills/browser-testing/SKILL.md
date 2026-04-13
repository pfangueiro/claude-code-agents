---
name: browser-testing
description: E2E browser testing with Playwright MCP. Visual regression, responsive design, cross-browser testing, codegen sessions. Auto-activates on e2e test, visual regression, screenshot test, browser test, Playwright, responsive test, cross-browser, visual verification.
---

# Browser Testing with Playwright MCP

Comprehensive patterns for end-to-end browser testing, visual regression, and responsive design verification using the Playwright MCP server.

## Available Playwright MCP Tools

### Navigation & State
- `playwright_navigate` — Open a URL (set `browserType`, `width`, `height`, `headless`)
- `playwright_go_back` / `playwright_go_forward` — History navigation
- `playwright_resize` — Change viewport (manual or 143+ device presets: `iPhone 13`, `iPad Pro`, `Galaxy S24`, etc.)

### Interaction
- `playwright_click` — Click an element (CSS selector)
- `playwright_fill` — Fill an input field
- `playwright_select` — Select dropdown value
- `playwright_hover` — Hover over element
- `playwright_drag` — Drag element to target
- `playwright_press_key` — Press keyboard key
- `playwright_upload_file` — Upload file to input

### Inspection
- `playwright_screenshot` — Capture page or element screenshot (with `fullPage`, `selector`, `savePng`)
- `playwright_get_visible_text` — Get all visible text on page
- `playwright_get_visible_html` — Get HTML (options: `cleanHtml`, `minify`, `removeScripts`, `selector`)
- `playwright_console_logs` — Retrieve browser console logs (filter by type: error, warning, etc.)
- `playwright_evaluate` — Execute arbitrary JavaScript in browser

### HTTP API Testing
- `playwright_get` / `playwright_post` / `playwright_put` / `playwright_patch` / `playwright_delete` — Direct HTTP operations with auth headers

### Code Generation
- `start_codegen_session` — Begin recording interactions as Playwright test code
- `end_codegen_session` — Generate the test file from recorded actions
- `get_codegen_session` — Check session status
- `clear_codegen_session` — Discard without generating

### Response Validation
- `playwright_expect_response` — Start waiting for an HTTP response (by URL pattern)
- `playwright_assert_response` — Validate the response body

## Patterns

### E2E Test: User Journey
```
1. playwright_navigate → target URL
2. playwright_fill → username/password fields
3. playwright_click → submit button
4. playwright_expect_response → /api/auth (start waiting)
5. playwright_assert_response → verify auth succeeded
6. playwright_screenshot → capture authenticated state
7. playwright_get_visible_text → verify welcome message
```

### Visual Regression: Screenshot Comparison
```
1. playwright_navigate → target page
2. playwright_screenshot → name: "baseline-homepage", savePng: true
3. [Make code changes]
4. playwright_navigate → same page (fresh load)
5. playwright_screenshot → name: "current-homepage", savePng: true
6. Compare screenshots visually or via diff tool
```

### Responsive Design Testing
```
1. playwright_navigate → target page
2. playwright_resize → device: "iPhone 13" (375x812)
3. playwright_screenshot → name: "mobile"
4. playwright_resize → device: "iPad Pro 11" (834x1194)
5. playwright_screenshot → name: "tablet"
6. playwright_resize → width: 1920, height: 1080
7. playwright_screenshot → name: "desktop"
```

### Form Validation Testing
```
1. playwright_navigate → form page
2. playwright_fill → invalid email
3. playwright_click → submit
4. playwright_get_visible_text → check for error messages
5. playwright_console_logs → type: "error" (check for JS errors)
6. playwright_fill → valid data
7. playwright_click → submit
8. playwright_assert_response → verify API success
```

### Codegen: Record Test from Manual Actions
```
1. start_codegen_session → outputPath: "/tests/e2e/"
2. playwright_navigate → target URL
3. playwright_click → interact with elements
4. playwright_fill → fill forms
5. end_codegen_session → generates test file at outputPath
```

### Cross-Browser Testing
```
1. playwright_navigate → url, browserType: "chromium"
2. playwright_screenshot → name: "chrome-result"
3. playwright_close
4. playwright_navigate → url, browserType: "firefox"
5. playwright_screenshot → name: "firefox-result"
6. playwright_close
7. playwright_navigate → url, browserType: "webkit"
8. playwright_screenshot → name: "safari-result"
```

## Best Practices

- Always `playwright_close` when done — releases browser resources
- Use `selector` option on screenshots to capture specific components
- Set `headless: true` for CI/automated runs, `false` for debugging
- Use `playwright_console_logs` with `type: "error"` after interactions to catch JS errors
- Use `playwright_expect_response` BEFORE the action that triggers the request
- Use device presets for accurate mobile/tablet testing (includes user-agent + touch emulation)
- For iframes, use `playwright_iframe_click` and `playwright_iframe_fill`

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
