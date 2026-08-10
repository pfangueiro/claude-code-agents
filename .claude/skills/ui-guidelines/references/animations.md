# Animation & Interaction Guidelines

## Animation Principles

1. **Purpose-driven**: Every animation should serve a purpose (feedback, guidance, delight)
2. **Performance-first**: Animations should not impact performance
3. **Consistent timing**: Use standardized durations and easing
4. **Respectful**: Respect user preferences (prefers-reduced-motion)

## Standard Durations

```javascript
const duration = {
  fast: '150ms',    // Micro-interactions (hover, focus)
  base: '250ms',    // Standard transitions (modals, drawers)
  slow: '350ms',    // Complex animations (page transitions)
};
```

## Easing Functions

```javascript
const easing = {
  default: 'cubic-bezier(0.4, 0, 0.2, 1)',  // Most animations
  in: 'cubic-bezier(0.4, 0, 1, 1)',         // Elements entering
  out: 'cubic-bezier(0, 0, 0.2, 1)',        // Elements exiting
  inOut: 'cubic-bezier(0.4, 0, 0.2, 1)',    // Elements moving
};
```

## Common Animations

### Fade Transitions
```tsx
// CSS
.fade-enter {
  opacity: 0;
}
.fade-enter-active {
  opacity: 1;
  transition: opacity 250ms cubic-bezier(0.4, 0, 0.2, 1);
}
.fade-exit {
  opacity: 1;
}
.fade-exit-active {
  opacity: 0;
  transition: opacity 250ms cubic-bezier(0.4, 0, 0.2, 1);
}
```

### Slide Transitions
```tsx
// CSS for slide from bottom
.slide-enter {
  transform: translateY(20px);
  opacity: 0;
}
.slide-enter-active {
  transform: translateY(0);
  opacity: 1;
  transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}
```

### Scale Transitions
```tsx
// CSS for scale animations
.scale-enter {
  transform: scale(0.95);
  opacity: 0;
}
.scale-enter-active {
  transform: scale(1);
  opacity: 1;
  transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}
```

## Loading Animations

### Spinner Component
```tsx
import { Spin } from 'antd';
import { LoadingOutlined } from '@ant-design/icons';

const customIcon = <LoadingOutlined style={{ fontSize: 24 }} spin />;

export const LoadingSpinner = () => (
  <div className="flex items-center justify-center p-8">
    <Spin indicator={customIcon} />
  </div>
);
```

### Skeleton Loading
```tsx
import { Skeleton } from 'antd';

export const ContentSkeleton = () => (
  <div className="space-y-4">
    <Skeleton active paragraph={{ rows: 1 }} />
    <Skeleton active paragraph={{ rows: 3 }} />
  </div>
);
```

### Progress Bar Loading
```tsx
import { Progress } from 'antd';
import { useState, useEffect } from 'react';

export const ProgressLoader = () => {
  const [percent, setPercent] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setPercent((prev) => {
        if (prev >= 100) return 0;
        return prev + 10;
      });
    }, 500);
    
    return () => clearInterval(timer);
  }, []);

  return (
    <Progress 
      percent={percent} 
      status="active"
      strokeColor={{
        '0%': '#F79400',  // brand orange — see design-tokens.md (canonical)
        '100%': '#52c41a',
      }}
    />
  );
};
```

### Dots Animation
```tsx
export const DotsLoader = () => (
  <div className="flex items-center justify-center space-x-2">
    <div className="w-2 h-2 bg-primary-500 rounded-full animate-bounce" 
         style={{ animationDelay: '0ms' }} />
    <div className="w-2 h-2 bg-primary-500 rounded-full animate-bounce" 
         style={{ animationDelay: '150ms' }} />
    <div className="w-2 h-2 bg-primary-500 rounded-full animate-bounce" 
         style={{ animationDelay: '300ms' }} />
  </div>
);
```

### Pulse Animation
```tsx
// Tailwind CSS
<div className="animate-pulse bg-neutral-200 rounded h-4 w-full" />

// Custom CSS
.pulse {
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}
```

## Hover States

### Button Hover
```css
.btn-hover {
  transition: all 150ms cubic-bezier(0.4, 0, 0.2, 1);
}

.btn-hover:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

.btn-hover:active {
  transform: translateY(0);
}
```

### Card Hover
```css
.card-hover {
  transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}

.card-hover:hover {
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}
```

### Link Hover
```css
.link-hover {
  position: relative;
  transition: color 150ms cubic-bezier(0.4, 0, 0.2, 1);
}

.link-hover::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  width: 0;
  height: 2px;
  background: currentColor;
  transition: width 250ms cubic-bezier(0.4, 0, 0.2, 1);
}

.link-hover:hover::after {
  width: 100%;
}
```

## Focus States

Every interactive element must have a visible **keyboard** focus state. Scope it with
`:focus-visible`, not `:focus` — browsers match `:focus-visible` on keyboard/programmatic focus but
not on an ordinary mouse click, which is precisely the "ring persists after clicking" complaint that
`component-patterns.md` addresses.

```css
.focus-ring:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px rgba(247, 148, 0, 0.2); /* brand orange */
  border-color: #F79400;
}
```

### Interaction with the `blur()` pattern

`component-patterns.md` (Button Patterns → "Removing Focus Border After Click") mandates
`e.currentTarget.blur()` on toggle and icon-only buttons. **That file owns the rule — follow it
there.** Be aware of what it does: `blur()` fires on *activation*, and keyboard activation
(Enter/Space on a `<button>`) dispatches the same click event, so focus moves to `<body>` whether
the user clicked or typed. Verified on a `<button>`: after `focus()` the active element is the
button; after activation with a `blur()` handler it is `BODY`.

Two consequences to respect:

- **Never signal state by the element keeping focus.** Use `aria-pressed` / `aria-expanded` plus a
  styled active state, so the control still reads correctly once focus is gone.
- **Do not extend `blur()` beyond the buttons that file names** (toggles, icon-only actions, state
  changes that do not navigate). Never apply it to form fields, links, or controls inside a dialog
  that a keyboard user has to return to.

## Modal/Drawer Animations

### Modal Entry
```tsx
import { Modal } from 'antd';

<Modal
  open={isOpen}
  transitionName="fade"
  maskTransitionName="fade"
  centered
>
  Modal content
</Modal>
```

### Drawer Entry

Drawer behaviour is owned by **`component-patterns.md` → Drawer Patterns**, which mandates the full
card-like pattern (header styling, fullscreen toggle, widths, close icon). Use that pattern; the
snippet here only illustrates the animation-relevant props.

```tsx
import { Drawer } from 'antd';

// ❌ NEVER add `destroyOnClose` — it destroys the content before the close
//    animation runs, so the drawer vanishes instantly instead of sliding out.
//    (component-patterns.md, Drawer Patterns §8.)
<Drawer
  open={isOpen}
  placement="right"
  width={400}
>
  Drawer content
</Drawer>
```

To reset state on close, do it in `onClose` and delay the cleanup ~300ms so the close animation can
finish — see `component-patterns.md`, Drawer Patterns §10. Never reach for `destroyOnClose` just to
reset state.

## List Animations

### Stagger Animation
```tsx
import { List } from 'antd';

const items = data.map((item, index) => (
  <List.Item
    key={item.id}
    style={{
      animation: `fadeIn 250ms ease-out ${index * 50}ms both`
    }}
  >
    {item.content}
  </List.Item>
));
```

## Page Transitions

### Next.js Page Transition
```tsx
// app/layout.tsx — App Router (this codebase uses next/navigation, not the Pages Router)
import { motion, AnimatePresence } from 'framer-motion';

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -20 }}
        transition={{ duration: 0.25 }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
```

## Micro-interactions

### Success Checkmark
```tsx
import { CheckCircleFilled } from '@ant-design/icons';

const SuccessAnimation = () => (
  <CheckCircleFilled 
    className="text-5xl text-success animate-scale-in"
    style={{
      animation: 'scaleIn 350ms cubic-bezier(0.4, 0, 0.2, 1)',
    }}
  />
);
```

### Button Click Ripple
Ant Design buttons already include ripple effects. Keep them enabled:

```tsx
<Button type="primary">
  Click Me
</Button>
```

## Accessibility Considerations

### Respect User Preferences
```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

### Skip Animations Toggle
```tsx
import { useState } from 'react';

const [prefersReducedMotion, setPrefersReducedMotion] = useState(
  window.matchMedia('(prefers-reduced-motion: reduce)').matches
);

// Use this to conditionally apply animations
const animationClass = prefersReducedMotion ? '' : 'animate-fade-in';
```

## Performance Best Practices

1. **Use CSS transforms over position properties** (transform, opacity)
2. **Avoid animating layout properties** (width, height, margin, padding)
3. **Use will-change sparingly**
4. **Debounce scroll/resize animations**
5. **Use requestAnimationFrame for JS animations**

## Animation Checklist (animation only)

Topic-scoped **supplement** to the authoritative component checklist in `SKILL.md`, Step 2 — not a
replacement. Run Step 2 as well; it wins on any conflict.

- [ ] Animation has clear purpose
- [ ] Duration follows standards (150ms/250ms/350ms)
- [ ] Uses approved easing functions
- [ ] Works with reduced motion preferences
- [ ] Does not cause layout shifts
- [ ] Tested on low-end devices
- [ ] Keyboard focus state is visible, via `:focus-visible`
- [ ] No `destroyOnClose` on drawers (component-patterns.md, Drawer Patterns §8)
- [ ] Animations are smooth at 60fps
