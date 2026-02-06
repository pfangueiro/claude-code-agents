# Styling & Layout Guidelines

## Styling Approach

### Tech Stack
- **Primary**: Ant Design components
- **Utility Classes**: Tailwind CSS for custom styling
- **Charts**: shadcn/ui components where applicable
- **Avoid**: Inline styles unless absolutely necessary

### Import Order
```tsx
// 1. React and Next.js
import { useState } from 'react';
import { useRouter } from 'next/router';

// 2. Third-party libraries
import { Form, Input, Button } from 'antd';

// 3. Internal components
import { CustomComponent } from '@/components';

// 4. Utilities and types
import { formatDate } from '@/utils';
import type { User } from '@/types';

// 5. Styles
import styles from './Component.module.css';
```

## Tailwind Utilities

### Spacing
Use consistent spacing based on the 4px grid:

```tsx
// Padding
p-1  // 4px
p-2  // 8px
p-3  // 12px
p-4  // 16px (most common)
p-6  // 24px
p-8  // 32px

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
```tsx
// Mobile-first approach
<div className="w-full md:w-1/2 lg:w-1/3">
  
// Breakpoints:
// sm: 640px
// md: 768px
// lg: 1024px
// xl: 1280px
// 2xl: 1536px
```

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
      colorPrimary: '#1890ff',
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

```tsx
// Use consistent z-index scale
z-0    // Base layer
z-10   // Elevated content
z-20   // Dropdowns
z-30   // Sticky headers
z-40   // Modals backdrop
z-50   // Modals
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
1. **Use Tailwind utilities** over custom CSS when possible
2. **Avoid deep nesting** in custom CSS
3. **Minimize CSS-in-JS** runtime costs
4. **Use CSS modules** for component-specific styles

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

```tsx
// Using Tailwind dark mode
<div className="bg-white dark:bg-neutral-900 text-neutral-900 dark:text-white">
  Content
</div>
```

## Common Patterns Checklist

- [ ] Use Ant Design components as base
- [ ] Apply Tailwind for spacing and layout
- [ ] Follow 4px spacing grid
- [ ] Use semantic color tokens
- [ ] Mobile-first responsive design
- [ ] Maintain consistent shadows
- [ ] Ensure accessible focus states
- [ ] Use shadow-md for standard cards
- [ ] Keep z-index values organized
- [ ] Test on multiple screen sizes
