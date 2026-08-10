# Styling & Layout Guidelines

## Styling Approach

> **Reconciled with `SKILL.md`.** This file is written Tailwind-first, which reads against the grain
> of the Ant-Design-first mandates in `SKILL.md`. Every known conflict is called out inline below.
> Where anything here still disagrees with `SKILL.md`, **`SKILL.md` wins.**

### Tech Stack
- **Primary**: Ant Design components
- **Utility Classes**: Tailwind CSS — sparingly, utility classes only (SKILL.md ranks it 4th, "rarely")
- **Charts**: **out of scope for this skill entirely** — see SKILL.md, "Out of Scope". Use a dedicated data-visualization reference.
- **Inline styles**: **expected** for layout and spacing — SKILL.md's Styling Approach ranks them *above* Tailwind. Do not avoid them.

### Import Order
```tsx
// 1. React and Next.js — App Router. Use 'next/navigation', NOT the Pages Router
//    'next/router'. This matches the real code in codebase-patterns.md.
import { useState } from 'react';
import { useRouter } from 'next/navigation';

// 2. Third-party libraries
import { Form, Input, Button } from 'antd';

// 3. Internal components
import { CustomComponent } from '@/components';

// 4. Utilities and types
import { formatDate } from '@/utils';
import type { User } from '@/types';

// 5. Styles — NONE.
//    SKILL.md DON'Ts: "Don't create custom CSS files". There is no per-component
//    stylesheet to import; use theme tokens + inline styles instead.
```

## Tailwind Utilities

### Spacing

The mandated steps are **8px / 12px / 16px / 24px** (SKILL.md, Step 3) — *not* every rung of
Tailwind's 4px scale. 4px is reserved for optical nudges only (the card-grid `paddingBottom: 4px`
and the drawer fullscreen button's `padding: 4px` in SKILL.md are the documented uses).

```tsx
// Padding — mandated steps
p-2  // 8px
p-3  // 12px
p-4  // 16px (most common)
p-6  // 24px

// Off-scale — do not reach for these
p-1  // 4px  — optical nudges only, not a spacing step
p-8  // 32px — not a mandated step

// Margin
mt-4  // margin-top: 16px
mb-6  // margin-bottom: 24px
mx-auto // horizontal centering

// Gap (for flex/grid)
gap-2  // 8px
gap-4  // 16px
```

### Layout
```tsx
// Flexbox
<div className="flex items-center justify-between gap-4">

// Grid
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">

// Container
<div className="container mx-auto px-4 max-w-7xl">
```

### Responsive Design

Responsive layout is **antd Grid's** job (`<Row>` / `<Col>`), per SKILL.md's Ant-Design-first
mandate — and it is what the Sidebar Layout and Card Grid patterns further down this file already
use.

```tsx
// antd <Col> breakpoints:
// xs:  < 576px
// sm:  >= 576px
// md:  >= 768px
// lg:  >= 992px
// xl:  >= 1200px
// xxl: >= 1600px
<Row gutter={[16, 16]}>
  <Col xs={24} md={12} lg={8}>...</Col>
</Row>
```

⚠ **Tailwind's same-named breakpoints are different numbers** (sm 640 / md 768 / lg 1024 / xl 1280 /
2xl 1536). Only `md` coincides. Never express one responsive rule half in antd and half in Tailwind:
`lg:` flips at 1024px while `<Col lg>` flips at 992px, so the two disagree across a 32px band and the
layout breaks only at those widths. Pick antd Grid.

### Typography
```tsx
// Headings
<h1 className="text-4xl font-bold text-neutral-900">
<h2 className="text-3xl font-semibold text-neutral-900">
<h3 className="text-2xl font-semibold text-neutral-900">
<h4 className="text-xl font-medium text-neutral-900">

// Body text
<p className="text-base text-neutral-700 leading-relaxed">

// Small text
<span className="text-sm text-neutral-600">
```

### Colors
```tsx
// Background
bg-white
bg-neutral-50
bg-primary-500

// Text
text-neutral-900  // Primary text
text-neutral-600  // Secondary text
text-primary-500  // Brand text

// Border
border-neutral-200
border-primary-500
```

## Layout Patterns

### Page Layout
```tsx
export default function Page() {
  return (
    <div className="min-h-screen bg-neutral-50">
      {/* Header */}
      <header className="bg-white border-b border-neutral-200">
        <div className="container mx-auto px-4 py-4 max-w-7xl">
          {/* Header content */}
        </div>
      </header>
      
      {/* Main content */}
      <main className="container mx-auto px-4 py-8 max-w-7xl">
        {/* Page content */}
      </main>
      
      {/* Footer */}
      <footer className="bg-white border-t border-neutral-200 mt-auto">
        <div className="container mx-auto px-4 py-6 max-w-7xl">
          {/* Footer content */}
        </div>
      </footer>
    </div>
  );
}
```

### Section Layout
```tsx
<section className="mb-8">
  <h2 className="text-2xl font-semibold mb-4 text-neutral-900">
    Section Title
  </h2>
  <div className="bg-white rounded-lg shadow-md p-6">
    {/* Section content */}
  </div>
</section>
```

### Card Grid
```tsx
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
  {items.map(item => (
    <Card key={item.id} className="shadow-md" bordered={false}>
      {/* Card content */}
    </Card>
  ))}
</div>
```

### Sidebar Layout
```tsx
import { Row, Col } from 'antd';

<Row gutter={[24, 24]}>
  {/* Main content */}
  <Col xs={24} lg={16}>
    <div className="bg-white rounded-lg shadow-md p-6">
      {/* Main content */}
    </div>
  </Col>
  
  {/* Sidebar */}
  <Col xs={24} lg={8}>
    <div className="bg-white rounded-lg shadow-md p-6 sticky top-4">
      {/* Sidebar content */}
    </div>
  </Col>
</Row>
```

## Component Styling

### Ant Design Customization
```tsx
// Configure theme in app
import { ConfigProvider } from 'antd';

<ConfigProvider
  theme={{
    token: {
      colorPrimary: '#F79400', // brand orange — see design-tokens.md (canonical)
      borderRadius: 6,
      fontSize: 16,
    },
  }}
>
  <App />
</ConfigProvider>
```

### Combining Ant Design + Tailwind
```tsx
import { Button } from 'antd';

// Good: Use Tailwind for margins/spacing
<Button type="primary" className="mt-4 mb-6">
  Submit
</Button>

// Good: Custom width with Tailwind
<Input className="max-w-md" />

// Avoid: Don't override Ant Design's core styles
<Button className="bg-red-500"> {/* Bad - use danger prop instead */}
```

### Custom Components
```tsx
// Use Tailwind for custom components
export const CustomCard = ({ children }: { children: React.ReactNode }) => (
  <div className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow duration-250">
    {children}
  </div>
);
```

## Spacing Guidelines

### Component Spacing
```tsx
// Between form fields
<div className="space-y-4">
  <Form.Item>...</Form.Item>
  <Form.Item>...</Form.Item>
</div>

// Between sections
<div className="space-y-8">
  <section>...</section>
  <section>...</section>
</div>

// Between cards
<div className="grid gap-6">
  <Card>...</Card>
  <Card>...</Card>
</div>
```

### Content Spacing
```tsx
// Article/content spacing
<article className="prose max-w-none">
  <h1 className="mb-4">Title</h1>
  <p className="mb-4">Paragraph</p>
  <h2 className="mt-8 mb-4">Subtitle</h2>
  <p className="mb-4">More content</p>
</article>
```

## Borders and Dividers

### Card Borders
```tsx
// Prefer shadows over borders
<Card className="shadow-md" bordered={false}>

// When borders are needed
<Card className="border border-neutral-200">
```

### Dividers
```tsx
import { Divider } from 'antd';

<Divider />  // Horizontal
<Divider type="vertical" />  // Vertical

// Custom divider
<div className="border-t border-neutral-200 my-6" />
```

## Z-Index Management

**antd owns overlay layering — Tailwind's `z-*` scale cannot reach it.** Modals, drawers, dropdowns,
popovers, `message` and `notification` are rendered by antd far above Tailwind's ceiling: antd's
`Drawer` `zIndexPopup` defaults to **1000**, `Popover` **1030**, `Dropdown` **1050**, `Popconfirm`
**1060**. Tailwind's `z-50` is literally `z-index: 50`, so it cannot stack against any of them.

Adjust antd layers with the `zIndexPopupBase` seed token or a per-component `zIndexPopup` on
`ConfigProvider` — never with a utility class.

```tsx
// Tailwind z-* is only for in-page, non-antd stacking, and must stay below 1000
z-0    // Base layer
z-10   // Elevated content
z-20   // Custom (non-antd) floating elements
z-30   // Sticky headers

// ❌ These rows were wrong and are removed: antd modals/drawers sit at >= 1000,
//    so `z-40` / `z-50` never layer a backdrop or modal against them.
```

## Shadow Usage

```tsx
// Card shadows
shadow-sm   // Subtle elevation
shadow-md   // Standard cards (most common)
shadow-lg   // Prominent cards
shadow-xl   // Hero sections

// Hover shadows
hover:shadow-lg  // Card hover effect
```

## Accessibility

### Focus Styles
```tsx
// Always maintain visible focus
<button className="focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2">
  Button
</button>
```

### Color Contrast
- Text on white: minimum `text-neutral-700`
- Small text on white: minimum `text-neutral-900`
- Interactive elements: minimum 3:1 contrast ratio

### Screen Reader Only
```tsx
<span className="sr-only">
  Screen reader only text
</span>
```

## Performance

### CSS Best Practices
1. **Prefer theme tokens + inline styles**, then Tailwind utilities — never a new stylesheet
2. **Avoid deep nesting** in any CSS you inherit
3. **No CSS-in-JS libraries** (SKILL.md DON'Ts) — antd's own runtime is the exception you already have
4. **No component CSS files, including CSS modules** — SKILL.md DON'Ts: "Don't create custom CSS files"

### Class Composition
```tsx
// Good: Use clsx for conditional classes
import clsx from 'clsx';

<div className={clsx(
  'base-classes',
  isActive && 'active-classes',
  hasError && 'error-classes'
)}>
```

## Dark Mode (If Applicable)

Prefer antd's dark algorithm plus `theme.useToken()` — SKILL.md mandates theme tokens
(`token.colorText`, `token.colorBgContainer`), which already flip with the active algorithm. The
Tailwind `dark:` form below only applies to non-antd markup, and must be kept in sync with the antd
theme by hand.

```tsx
// Using Tailwind dark mode
<div className="bg-white dark:bg-neutral-900 text-neutral-900 dark:text-white">
  Content
</div>
```

## Common Patterns Checklist (layout only)

Topic-scoped **supplement** to the authoritative component checklist in `SKILL.md`, Step 2 — not a
replacement. Run Step 2 as well; it wins on any conflict.

- [ ] Use Ant Design components as base
- [ ] Use theme tokens + inline styles for spacing and layout; Tailwind only as a rare utility
- [ ] Follow the 8px / 12px / 16px / 24px spacing steps
- [ ] Use semantic color tokens
- [ ] Mobile-first responsive design via antd Grid breakpoints (not Tailwind's)
- [ ] Maintain consistent shadows
- [ ] Ensure a visible keyboard focus state (see `animations.md`, Focus States)
- [ ] Use shadow-md for standard cards
- [ ] Layer antd overlays via ConfigProvider z-index tokens, not utility classes
- [ ] Test on multiple screen sizes
