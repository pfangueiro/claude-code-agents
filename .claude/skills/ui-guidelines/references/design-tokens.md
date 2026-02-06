# Design Tokens

## Color Palette

### Brand Colors
```javascript
const brandColors = {
  primary: '#F79400',     // Brand Orange - Main brand color
  secondary: '#7C4DFF',   // Purple - Product Owner
  success: '#52c41a',     // Green - Tech Owner
  warning: '#faad14',     // Yellow/Orange
  error: '#ff4d4f',       // Red - Errors and overdue
  info: '#1890ff',        // Blue
};
```

### Neutral/Gray Scale
```javascript
const neutralColors = {
  50: '#fafafa',
  100: '#f5f5f5',
  200: '#e8e8e8',
  300: '#d9d9d9',
  400: '#bfbfbf',
  500: '#8c8c8c',
  600: '#595959',
  700: '#434343',
  800: '#262626',
  900: '#1f1f1f',
  950: '#141414',
};
```

### Avatar Colors (Consistent hashing)
```javascript
const avatarColors = [
  '#f56a00', '#7265e6', '#ffbf00', '#00a2ae', '#1890ff',
  '#52c41a', '#eb2f96', '#faad14', '#722ed1', '#13c2c2'
];
```

### Background Colors
- **Page Background**: `#fafafa` or from theme token
- **Card Background**: `#ffffff` or `token.colorBgContainer`
- **Section Background**: `token.colorBgLayout`
- **Hover Background**: `token.colorFillSecondary`

### Text Colors
- **Primary Text**: `token.colorText`
- **Secondary Text**: `token.colorTextSecondary` or `type="secondary"`
- **Tertiary Text**: `token.colorTextTertiary`
- **Disabled Text**: `#999` or `token.colorTextDisabled`

## Typography

### Font Families
```css
--font-primary: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
--font-mono: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', Consolas, 'Courier New', monospace;
```

### Font Sizes
```javascript
const fontSize = {
  xs: '12px',    // Small labels, captions
  sm: '14px',    // Body text, form inputs
  base: '16px',  // Default body
  lg: '18px',    // Emphasized text
  xl: '20px',    // H4
  '2xl': '24px', // H3
  '3xl': '30px', // H2
  '4xl': '38px', // H1
};
```

### Font Weights
```javascript
const fontWeight = {
  normal: 400,
  medium: 500,
  semibold: 600,
  bold: 700,
};
```

### Line Heights
```javascript
const lineHeight = {
  tight: 1.25,
  normal: 1.5,
  relaxed: 1.75,
};
```

## Spacing Scale

Use consistent spacing based on actual patterns from codebase:

```javascript
// Common spacing values used in the app
const spacing = {
  xs: '4px',
  sm: '8px',
  md: '12px',
  base: '16px',
  lg: '24px',
  xl: '32px',
  '2xl': '40px',
};
```

### Common Usage Patterns
- **Component gaps**: `gap: "8px"` or `gap: "12px"`
- **Card padding**: `padding: "12px"` or `padding: '12px 16px'`
- **Section margins**: `marginBottom: 16` or `marginBottom: 12`
- **Page padding**: `padding: "24px 40px 24px 24px"`
- **Space between filters**: `<Space>` with default 8px or custom gap
- **Modal content spacing**: `marginBottom: 16` between sections

## Border Radius

```javascript
const borderRadius = {
  sm: '2px',
  base: '4px',     // Default for small elements
  md: '6px',       // Forms, inputs, tags  
  lg: '8px',       // Cards, containers
  pill: '9999px',  // Avatars, pills
};
```

### Usage
- **Tags**: `borderRadius: "8px"` or `borderRadius: "6px"`
- **Cards**: `borderRadius: '8px'`
- **Buttons**: Ant Design default (typically 6px)
- **Small indicators**: `borderRadius: '50%'` or `'4px'`
- **Avatars**: `borderRadius: '50%'` (circular)

## Shadows

```javascript
const shadows = {
  sm: '0 1px 2px rgba(0, 0, 0, 0.04)',        // Subtle - stream cards
  md: '0 1px 2px rgba(0, 0, 0, 0.05)',        // Default cards (className="shadow-md")
  hover: '0 4px 6px -1px rgba(0, 0, 0, 0.1)', // Hover states
};
```

### Usage
- **Cards**: `boxShadow: '0 1px 2px rgba(0, 0, 0, 0.04)'` or `className="shadow-md"`
- **Ant Design cards**: Typically use `bordered={false}` with subtle shadow
- **Hover effects**: Not heavily used, prefer subtle transitions

## Z-Index Scale

```javascript
const zIndex = {
  dropdown: 1000,
  sticky: 1020,
  fixed: 1030,
  modalBackdrop: 1040,
  modal: 1050,
  popover: 1060,
  tooltip: 1070,
};
```

## Breakpoints

```javascript
const breakpoints = {
  xs: '480px',
  sm: '576px',
  md: '768px',
  lg: '992px',
  xl: '1200px',
  '2xl': '1600px',
};
```

## Animation Tokens

### Durations
```javascript
const duration = {
  fast: '150ms',
  base: '250ms',
  slow: '350ms',
};
```

### Easing Functions
```javascript
const easing = {
  default: 'cubic-bezier(0.4, 0, 0.2, 1)',
  in: 'cubic-bezier(0.4, 0, 1, 1)',
  out: 'cubic-bezier(0, 0, 0.2, 1)',
  inOut: 'cubic-bezier(0.4, 0, 0.2, 1)',
};
```
