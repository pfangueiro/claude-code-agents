# Component Patterns

## Form Components

### Form Structure
All forms should follow this structure:

```tsx
import { Form, Input, Button } from 'antd';
import type { FormProps } from 'antd';

interface FormValues {
  // Define form fields
}

export const ExampleForm = () => {
  const [form] = Form.useForm<FormValues>();

  const onFinish: FormProps<FormValues>['onFinish'] = (values) => {
    console.log('Success:', values);
  };

  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={onFinish}
      autoComplete="off"
      className="max-w-md"
    >
      {/* Form fields here */}
    </Form>
  );
};
```

### Form Fields
```tsx
<Form.Item
  label="Email"
  name="email"
  rules={[
    { required: true, message: 'Please input your email!' },
    { type: 'email', message: 'Please enter a valid email!' }
  ]}
>
  <Input 
    placeholder="Enter your email"
    size="large"
  />
</Form.Item>
```

### Submit Buttons
```tsx
<Form.Item>
  <Button 
    type="primary" 
    htmlType="submit"
    size="large"
    block
    className="mt-4"
  >
    Submit
  </Button>
</Form.Item>
```

### Login Form Pattern
```tsx
import { Form, Input, Button, Checkbox } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';

export const LoginForm = () => {
  const [form] = Form.useForm();

  const onFinish = (values: any) => {
    console.log('Login:', values);
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-neutral-50">
      <div className="w-full max-w-md p-8 bg-white rounded-lg shadow-md">
        <h1 className="text-3xl font-semibold text-center mb-6 text-neutral-900">
          Sign In
        </h1>
        
        <Form
          form={form}
          layout="vertical"
          onFinish={onFinish}
          autoComplete="off"
        >
          <Form.Item
            name="email"
            rules={[
              { required: true, message: 'Please input your email!' },
              { type: 'email', message: 'Please enter a valid email!' }
            ]}
          >
            <Input 
              prefix={<UserOutlined />}
              placeholder="Email"
              size="large"
            />
          </Form.Item>

          <Form.Item
            name="password"
            rules={[{ required: true, message: 'Please input your password!' }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="Password"
              size="large"
            />
          </Form.Item>

          <Form.Item name="remember" valuePropName="checked">
            <Checkbox>Remember me</Checkbox>
          </Form.Item>

          <Form.Item>
            <Button 
              type="primary" 
              htmlType="submit"
              size="large"
              block
              className="mt-2"
            >
              Sign In
            </Button>
          </Form.Item>
        </Form>
      </div>
    </div>
  );
};
```

## Icon Standards

### Navigation Icons (from Sidebar and Dashboard)

All navigation icons should follow this mapping for consistency:

**Main Navigation:**
- **Dashboard**: `<HomeOutlined />` (Ant Design)
- **Projects**: `<FolderGit2 size={16} />` (Lucide React)
- **Roadmap**: `<SquareChartGantt size={16} />` (Lucide React)
- **Delivery**: `<DeliveredProcedureOutlined />` (Ant Design)
- **Requests**: `<Lightbulb size={16} />` (Lucide React)
- **Tech Teams**: `<TeamOutlined />` (Ant Design)

**Analytics:**
- **Performance**: `<LineChartOutlined />` (Ant Design)
- **Capacity**: `<UsergroupAddOutlined />` (Ant Design)
- **JIRA Webhooks**: `<SyncOutlined />` (Ant Design)
- **GitHub Webhooks**: `<GithubOutlined />` (Ant Design)
- **Applications**: `<LaptopOutlined />` (Ant Design)
- **Resources**: `<TeamOutlined />` (Ant Design)

**Dashboard Tabs:**
- **GitHub**: `<GithubOutlined />` (Ant Design)
- **JIRA**: `<JiraIcon />` (Custom component at `@/app/components/icons/JiraIcon`)
- **Projects**: `<FolderGit2 size={16} />` (Lucide React) - **Must match sidebar**
- **Alerts**: `<BellOutlined />` (Ant Design)

**Icon Library Usage:**
```tsx
// Ant Design icons
import { HomeOutlined, TeamOutlined } from "@ant-design/icons";

// Lucide React icons (for Projects, Roadmap, Requests)
import { FolderGit2, SquareChartGantt, Lightbulb } from "lucide-react";

// Custom icons
import JiraIcon from "@/app/components/icons/JiraIcon";
```

**Consistency Rule:**
Icons used in navigation tabs/headers MUST match the icons in the sidebar for the same page/section.

## Button Patterns

### Primary Action Button
```tsx
<Button type="primary" size="large">
  Primary Action
</Button>
```

### Secondary Action Button
```tsx
<Button size="large">
  Secondary Action
</Button>
```

### Danger Button
```tsx
<Button type="primary" danger size="large">
  Delete
</Button>
```

### Icon Button
```tsx
import { PlusOutlined } from '@ant-design/icons';

<Button type="primary" icon={<PlusOutlined />} size="large">
  Add New
</Button>
```

### Button Groups
```tsx
import { Button, Space } from 'antd';

<Space>
  <Button>Cancel</Button>
  <Button type="primary">Save</Button>
</Space>
```

### Removing Focus Border After Click
**IMPORTANT**: To prevent the orange focus border from persisting after clicking a button, always call `blur()` on the button element:

```tsx
// ✅ CORRECT - Remove focus after action
<Button
  type="text"
  icon={<MenuFoldOutlined />}
  onClick={(e) => {
    handleAction();
    e.currentTarget.blur(); // Remove focus after clicking to avoid orange border
  }}
/>

// ✅ Also correct for theme toggles, collapse buttons, etc.
<Button
  type="text"
  icon={<Sun size={20} />}
  onClick={(e) => {
    setTheme('light');
    e.currentTarget.blur(); // Remove focus after clicking
  }}
/>

// ❌ WRONG - Focus border will persist
<Button
  type="text"
  icon={<MenuFoldOutlined />}
  onClick={handleAction}
/>
```

**When to use this pattern:**
- Toggle buttons (theme switcher, collapse/expand sidebar)
- Icon-only action buttons
- Any button where the focus state should not persist after clicking
- Buttons that trigger state changes but don't navigate away

## Card Components

### Basic Card
```tsx
import { Card } from 'antd';

<Card 
  title="Card Title"
  className="shadow-md"
  bordered={false}
>
  Card content here
</Card>
```

### Card with Actions
```tsx
import { Card, Button } from 'antd';
import { EditOutlined, DeleteOutlined } from '@ant-design/icons';

<Card
  title="Card Title"
  extra={
    <Space>
      <Button type="text" icon={<EditOutlined />} />
      <Button type="text" danger icon={<DeleteOutlined />} />
    </Space>
  }
  className="shadow-md"
  bordered={false}
>
  Card content
</Card>
```

### Stat Card
```tsx
import { Card, Statistic } from 'antd';
import { ArrowUpOutlined } from '@ant-design/icons';

<Card bordered={false} className="shadow-md">
  <Statistic
    title="Total Revenue"
    value={11280}
    precision={2}
    prefix="$"
    valueStyle={{ color: '#52c41a' }}
    suffix={<ArrowUpOutlined />}
  />
</Card>
```

### Activity Heatmap Card
For activity visualization cards (GitHub/JIRA heatmaps):

```tsx
import { Card, Typography, Space, Select, theme } from 'antd';
import { GithubOutlined } from '@ant-design/icons';

const { Text } = Typography;
const { Option } = Select;

const ActivityCard = () => {
  const { token } = theme.useToken();
  const [selectedYear, setSelectedYear] = useState(2025);

  return (
    <Card
      title={
        <div style={{
          fontSize: '14px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <Space>
            <GithubOutlined />
            <Text strong style={{ fontSize: '14px' }}>Activity Title</Text>
            <Select
              value={selectedYear}
              onChange={setSelectedYear}
              style={{ width: 100, marginLeft: 8 }}
              size="small"
            >
              <Option value={2025}>2025</Option>
            </Select>
          </Space>
          <Text type="secondary" style={{ fontSize: '12px' }}>
            1135 activities in {selectedYear}
          </Text>
        </div>
      }
      headStyle={{ background: token.colorFillAlter, padding: '8px 16px', minHeight: 'auto' }} // #F4F7FB with minimal height
      styles={{ body: { padding: '16px', width: '100%' } }}
      style={{ marginBottom: '16px', width: '100%' }}
    >
      {/* Heatmap content */}
    </Card>
  );
};
```

**Key Requirements:**
- **Header background**: Use `token.colorFillAlter` (#F4F7FB) via `headStyle`
- **Header padding**: `8px 16px` for minimal compact height
- **Header minHeight**: Set to `'auto'` to prevent default height constraints
- **Title font size**: 14px with `<Text strong>` or `fontWeight: 600`
- **Statistics font size**: 12px with `type="secondary"`
- **Icon spacing**: `marginLeft: 8px` for selects after title
- **Alignment**: Use `alignItems: 'center'` for proper vertical centering

## Table Patterns

### Font Size Requirement
**MANDATORY**: All tables MUST use 12px font size. This is achieved using ConfigProvider with theme customization.

### Basic Table with 12px Font
```tsx
import { Table, ConfigProvider, theme } from 'antd';
import type { ColumnsType } from 'antd/es/table';

const { token } = theme.useToken();

interface DataType {
  key: string;
  name: string;
  age: number;
  address: string;
}

const columns: ColumnsType<DataType> = [
  {
    title: 'Name',
    dataIndex: 'name',
    key: 'name',
  },
  {
    title: 'Age',
    dataIndex: 'age',
    key: 'age',
  },
  {
    title: 'Address',
    dataIndex: 'address',
    key: 'address',
  },
];

// MANDATORY: Wrap Table in ConfigProvider with 12px fontSize
<ConfigProvider
  theme={{
    components: {
      Table: {
        headerBg: token.colorBgContainer,
        headerColor: token.colorText,
        fontSize: 12, // REQUIRED: 12px font size for all tables
      },
    },
  }}
>
  <Table
    columns={columns}
    dataSource={data}
    pagination={{ pageSize: 10 }}
    size="small"
  />
</ConfigProvider>
```

**Key Requirements:**
- **Font size**: 12px (set via ConfigProvider theme)
- **Table size**: Use `size="small"` for compact layout
- **Header background**: `token.colorBgContainer` for theme consistency
- **Header color**: `token.colorText` for proper text color in dark mode

### Table with Actions
```tsx
{
  title: 'Action',
  key: 'action',
  render: (_, record) => (
    <Space size="middle">
      <Button type="link">Edit</Button>
      <Button type="link" danger>Delete</Button>
    </Space>
  ),
}
```

### Full Page Table (with scrolling)
```tsx
<ConfigProvider
  theme={{
    components: {
      Table: {
        headerBg: token.colorBgContainer,
        headerColor: token.colorText,
        fontSize: 12,
      },
    },
  }}
>
  <Table
    columns={columns}
    dataSource={data}
    rowKey="id"
    pagination={false}
    size="small"
    scroll={{
      y: 'calc(100vh - 220px)', // Adjust based on page layout
      x: 'max-content'
    }}
    style={{
      flex: 1,
      minHeight: 0
    }}
  />
</ConfigProvider>
```

## Drawer Patterns

### Side Drawer (Card-like Style)

**MANDATORY**: All side drawers MUST use this exact pattern for consistency across the application.

This is the standard pattern for side drawers that slide in from the right with a card-like appearance, rounded corners, proper alignment, and fullscreen capability.

#### KEY REQUIREMENTS (MUST FOLLOW):

1. **Header must be EXACT same height as main page Card headers**
   - Use `padding: '8px 16px'` (NOT '12px' or '16px')
   - Use `minHeight: 'auto'` (REQUIRED to remove default height)
   - Use `background: token.colorFillAlter` (matches Card headers)
   - Title must be plain text in a div, NOT wrapped in `<Text>` component

2. **Fullscreen button MUST be included**
   - Left side of title with `<PanelLeftClose size={16} />` icon
   - Toggle between `PanelLeftClose` and `PanelLeftOpen`
   - Button padding: `4px` exactly
   - Fullscreen width: `calc(100vw - 80px)` (80px = collapsed sidebar)

3. **Close icon must be compact**
   - Use `<X size={16} />` from lucide-react
   - NOT the default Ant Design close icon

4. **Content must have card-like styling**
   - Rounded left corners: `borderRadius: '12px 0 0 12px'`
   - Custom shadow: `boxShadow: '-4px 0 24px rgba(0, 0, 0, 0.12)'`
   - Proper margins: `margin: '16px 16px 24px 0'`

#### Complete Pattern (COPY THIS EXACTLY):

```tsx
import { Drawer, Table, ConfigProvider, Space, Spin, theme, Button, Tooltip } from 'antd';
import { PanelLeftClose, PanelLeftOpen, X } from 'lucide-react';
import { useState } from 'react';

const ExampleDrawer = () => {
  const { token } = theme.useToken();
  const [open, setOpen] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [loading, setLoading] = useState(false);

  return (
    <Drawer
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <Tooltip title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}>
            <Button
              type="text"
              icon={isFullscreen ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
              onClick={() => setIsFullscreen(!isFullscreen)}
              style={{ padding: '4px' }}
            />
          </Tooltip>
          <Space>
            {/* IMPORTANT: Use plain text, NOT <Text> component */}
            Drawer Title Here
          </Space>
        </div>
      }
      open={open}
      onClose={() => {
        setOpen(false);
        setIsFullscreen(false); // ALWAYS reset fullscreen on close
      }}
      closeIcon={<X size={16} />}
      placement="right"                           // CRITICAL: Must be before styles
      width={isFullscreen ? 'calc(100vw - 80px)' : 1000}  // CRITICAL: 80px = collapsed sidebar width
      styles={{
        wrapper: {
          boxShadow: 'none'
        },
        header: {
          background: token.colorFillAlter,  // MANDATORY for correct header color
          padding: '8px 16px',                // MANDATORY for correct header height
          minHeight: 'auto'                   // MANDATORY to remove default height
        },
        content: {
          borderRadius: '12px 0 0 12px',
          boxShadow: '-4px 0 24px rgba(0, 0, 0, 0.12)',
          margin: '16px 16px 24px 0',
          height: 'calc(100vh - 36px)'
        },
        mask: {
          backgroundColor: 'rgba(0, 0, 0, 0.25)'
        }
      }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: '20px' }}>
          <Spin size="large" />
        </div>
      ) : (
        <ConfigProvider
          theme={{
            components: {
              Table: {
                headerBg: token.colorBgContainer,
                headerColor: token.colorText,
                fontSize: 12,
              },
            },
          }}
        >
          <Table
            dataSource={data}
            columns={columns}
            rowKey="id"
            pagination={false}
            size="small"
            scroll={{ y: 'calc(100vh - 150px)' }}
          />
        </ConfigProvider>
      )}
    </Drawer>
  );
};
```

#### MANDATORY Requirements (DO NOT DEVIATE):

**1. Title Structure (EXACT PATTERN):**
```tsx
title={
  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
    <Tooltip title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}>
      <Button
        type="text"
        icon={isFullscreen ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        onClick={() => setIsFullscreen(!isFullscreen)}
        style={{ padding: '4px' }}
      />
    </Tooltip>
    <Space>
      {/* Use plain text or JSX, NOT <Text strong> component */}
      Your Title Here
    </Space>
  </div>
}
```

**CRITICAL:**
- ✅ Use **plain text** in title (e.g., `Edit User: {user.name}`)
- ❌ **DO NOT** wrap in `<Text strong>` component (makes header too tall)
- ✅ Icon changes based on state: `PanelLeftClose` → `PanelLeftOpen`
- ✅ Tooltip text changes: "Fullscreen" → "Exit fullscreen"
- ✅ Button padding: `4px` (no more, no less)

**2. Header Styling (MANDATORY - ALL THREE REQUIRED):**
```tsx
header: {
  background: token.colorFillAlter,  // Theme color (#F4F7FB)
  padding: '8px 16px',                // Compact height (DO NOT CHANGE)
  minHeight: 'auto'                   // Remove default constraint (REQUIRED)
}
```

**Why this matters:**
- Without `minHeight: 'auto'`, header will be too tall
- Without exact `padding: '8px 16px'`, height won't match design
- Without `token.colorFillAlter`, background color will be wrong

**3. Fullscreen State Management:**
```tsx
const [isFullscreen, setIsFullscreen] = useState(false);

// Width changes dynamically
// CRITICAL: Use 80px (collapsed sidebar width) for maximum space
width={isFullscreen ? 'calc(100vw - 80px)' : 1000}

// ALWAYS reset fullscreen on close
onClose={() => {
  setOpen(false);
  setIsFullscreen(false);  // REQUIRED
}}
```

**4. Close Icon:**
```tsx
closeIcon={<X size={16} />}  // Lucide X icon, size 16
```

**5. Content Styling (Card-like):**
```tsx
content: {
  borderRadius: '12px 0 0 12px',               // Rounded left edge only
  boxShadow: '-4px 0 24px rgba(0, 0, 0, 0.12)', // Custom shadow
  margin: '16px 16px 24px 0',                  // Top/Right/Bottom margins
  height: 'calc(100vh - 36px)'                 // Full height minus margins
}
```

**6. Default Widths:**
- **Tables/Data**: `1000px` (fullscreen: `calc(100vw - 80px)`)
- **Forms**: `720px` (fullscreen: `calc(100vw - 80px)`)
- **Small Forms**: `600px` (fullscreen: `calc(100vw - 80px)`)

**CRITICAL:** Always use `80px` for fullscreen mode (collapsed sidebar width) to maximize drawer space regardless of sidebar state.

**7. Tables Inside Drawer:**
- **ALWAYS** wrap in `ConfigProvider` with `fontSize: 12`
- Use `scroll={{ y: 'calc(100vh - 150px)' }}` for internal scrolling
- Set `pagination={false}` for drawers (they show filtered/specific data)

**8. Slide Animation (CRITICAL):**
```tsx
// ❌ DO NOT USE destroyOnClose - it prevents slide animation
<Drawer destroyOnClose>  // WRONG - drawer will disappear instantly

// ✅ CORRECT - omit destroyOnClose for smooth slide animation
<Drawer>  // CORRECT - drawer slides out to the right when closing
```

**Why this matters:**
- Without `destroyOnClose`, the drawer slides out smoothly to the right
- With `destroyOnClose`, the drawer disappears instantly (bad UX)
- The slide animation is part of the consistent drawer experience

**If you need to reset state:**
- Reset state manually in `onClose` callback
- Use React keys to force remount if necessary
- Never use `destroyOnClose` just to reset state

**9. Prop Order (CRITICAL FOR ANIMATION):**
```tsx
// ✅ CORRECT PROP ORDER (MUST FOLLOW THIS EXACT ORDER):
<Drawer
  title={...}
  open={visible}
  onClose={...}
  closeIcon={<X size={16} />}
  placement="right"        // MUST be before styles
  width={...}              // MUST be before styles
  styles={{...}}           // MUST be after placement and width
>

// ❌ WRONG - placement/width AFTER styles breaks animation
<Drawer
  title={...}
  placement="right"
  width={1000}
  open={visible}
  onClose={...}
  closeIcon={<X size={16} />}
  styles={{...}}           // WRONG ORDER
>
```

**Why prop order matters:**
- If `placement` and `width` come AFTER `styles`, the drawer will disappear instantly instead of sliding
- The exact order is: `title` → `open` → `onClose` → `closeIcon` → `placement` → `width` → `styles`
- This is a React/Ant Design quirk - prop order affects the animation behavior

**10. State Management (CRITICAL FOR ANIMATION):**
```tsx
// ❌ WRONG - Clearing state immediately breaks animation
<Drawer
  open={visible}
  user={selectedUser}
  onClose={() => {
    setVisible(false);
    setSelectedUser(null);  // WRONG - drawer still animating, data becomes null
  }}
/>

// ✅ CORRECT - Delay state cleanup to allow animation to complete
<Drawer
  open={visible}
  user={selectedUser}
  onClose={() => {
    setVisible(false);
    // Wait 300ms for drawer close animation before clearing data
    setTimeout(() => setSelectedUser(null), 300);
  }}
/>
```

**Why delayed cleanup matters:**
- The drawer close animation takes ~300ms
- If you clear the data (like `user={null}`) immediately, React re-renders the drawer with null props
- This causes the drawer to disappear instantly instead of sliding out
- Always delay state cleanup by 300ms to allow the animation to complete

**Pattern for parent components:**
```tsx
const ParentComponent = () => {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedItem, setSelectedItem] = useState(null);

  return (
    <Drawer
      open={drawerOpen}
      data={selectedItem}
      onClose={() => {
        setDrawerOpen(false);
        setTimeout(() => setSelectedItem(null), 300);  // CRITICAL
      }}
    />
  );
};
```

#### Real-World Example (JIRA Activity Drawer):

```tsx
import { Drawer, Table, ConfigProvider, theme, Button, Tooltip, Space, Spin } from 'antd';
import { PanelLeftClose, PanelLeftOpen, X } from 'lucide-react';
import dayjs from 'dayjs';

const JiraActivityDrawer = () => {
  const { token } = theme.useToken();
  const [open, setOpen] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [activityType, setActivityType] = useState<'created' | 'commented' | 'updated'>('created');
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [details, setDetails] = useState([]);
  const [loading, setLoading] = useState(false);

  return (
    <Drawer
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <Tooltip title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}>
            <Button
              type="text"
              icon={isFullscreen ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
              onClick={() => setIsFullscreen(!isFullscreen)}
              style={{ padding: '4px' }}
            />
          </Tooltip>
          <Space>
            {activityType === 'created' && <>Tickets Created</>}
            {activityType === 'commented' && <>Tickets Commented</>}
            {activityType === 'updated' && <>Tickets Updated</>}
            {selectedDate && ` - ${dayjs(selectedDate).format('MMMM D, YYYY')}`}
          </Space>
        </div>
      }
      open={open}
      onClose={() => {
        setOpen(false);
        setDetails([]);
        setIsFullscreen(false);
      }}
      closeIcon={<X size={16} />}
      placement="right"
      width={isFullscreen ? 'calc(100vw - 220px)' : 1000}
      styles={{
        wrapper: { boxShadow: 'none' },
        header: {
          background: token.colorFillAlter,
          padding: '8px 16px',
          minHeight: 'auto'
        },
        content: {
          borderRadius: '12px 0 0 12px',
          boxShadow: '-4px 0 24px rgba(0, 0, 0, 0.12)',
          margin: '16px 16px 24px 0',
          height: 'calc(100vh - 36px)'
        },
        mask: { backgroundColor: 'rgba(0, 0, 0, 0.25)' }
      }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: '20px' }}>
          <Spin size="large" />
        </div>
      ) : (
        <ConfigProvider
          theme={{
            components: {
              Table: {
                headerBg: token.colorBgContainer,
                headerColor: token.colorText,
                fontSize: 12,
              },
            },
          }}
        >
          <Table
            dataSource={details}
            columns={columns}
            rowKey="id"
            pagination={false}
            size="small"
            scroll={{ y: 'calc(100vh - 150px)' }}
          />
        </ConfigProvider>
      )}
    </Drawer>
  );
};
```

#### Visual Effect:
- Drawer slides in from right as a card-like panel
- Doesn't cover entire viewport height (has margins)
- Rounded corners on left edge only
- Custom shadow for depth
- Compact header (same height as card headers)
- Fullscreen button expands to full content width
- Icon animates between PanelLeftClose ↔ PanelLeftOpen

## Modal Patterns

### Basic Modal
```tsx
import { Modal, Button } from 'antd';
import { useState } from 'react';

const [isModalOpen, setIsModalOpen] = useState(false);

<Modal
  title="Modal Title"
  open={isModalOpen}
  onOk={() => setIsModalOpen(false)}
  onCancel={() => setIsModalOpen(false)}
  okText="Confirm"
  cancelText="Cancel"
>
  Modal content here
</Modal>
```

### Confirm Modal
```tsx
import { Modal } from 'antd';
import { ExclamationCircleOutlined } from '@ant-design/icons';

Modal.confirm({
  title: 'Are you sure?',
  icon: <ExclamationCircleOutlined />,
  content: 'This action cannot be undone.',
  okText: 'Yes',
  okType: 'danger',
  cancelText: 'No',
  onOk() {
    // Handle confirm
  },
});
```

**Note:** For side panels showing detailed data, prefer using the **Side Drawer (Card-like Style)** pattern above instead of modals. Modals should only be used for confirmations, forms, and alerts.

## Loading Indicators

### Spinner
```tsx
import { Spin } from 'antd';

// Full page loading
<div className="flex items-center justify-center min-h-screen">
  <Spin size="large" />
</div>

// Inline loading
<Spin spinning={loading}>
  <div>Your content here</div>
</Spin>
```

### Skeleton
```tsx
import { Skeleton } from 'antd';

<Skeleton active paragraph={{ rows: 4 }} />
```

### Progress Bar
```tsx
import { Progress } from 'antd';

<Progress percent={60} status="active" />
```

## Notification Patterns

### Success Notification
```tsx
import { notification } from 'antd';

notification.success({
  message: 'Success',
  description: 'Your changes have been saved successfully.',
  placement: 'topRight',
  duration: 3,
});
```

### Error Notification
```tsx
notification.error({
  message: 'Error',
  description: 'Something went wrong. Please try again.',
  placement: 'topRight',
  duration: 4,
});
```

### Message (Toast)
```tsx
import { message } from 'antd';

message.success('Operation completed successfully');
message.error('Operation failed');
message.warning('Warning message');
message.info('Information message');
```

## Layout Patterns

### Dashboard/Page Header with Avatar

For user profile headers (dashboard, user pages):

```tsx
<div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
  <Avatar size={40} src={profilePic} />
  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
    <Text strong style={{ fontSize: '16px', lineHeight: '20px' }}>
      João Carvalhosa
    </Text>
    <Text type="secondary" style={{ fontSize: '12px', lineHeight: '16px' }}>
      Friday, October 24, 2025 • Week 43
    </Text>
  </div>
</div>
```

**Key Requirements:**
- **Avatar size**: 40px
- **Name font**: 16px strong with 20px line-height
- **Date/metadata font**: 12px secondary with 16px line-height
- **Layout**: Flexbox with `alignItems: 'center'` for proper vertical alignment
- **Gap**: 12px between avatar and text, 2px between name and date
- **NO Title component**: Use `<Text strong>` instead to avoid oversized fonts

### Page Container
```tsx
<div className="min-h-screen bg-neutral-50 p-6">
  <div className="max-w-7xl mx-auto">
    {/* Page content */}
  </div>
</div>
```

### Two Column Layout
```tsx
import { Row, Col } from 'antd';

<Row gutter={[24, 24]}>
  <Col xs={24} md={16}>
    {/* Main content */}
  </Col>
  <Col xs={24} md={8}>
    {/* Sidebar */}
  </Col>
</Row>
```

### Grid Layout
```tsx
<Row gutter={[16, 16]}>
  <Col xs={24} sm={12} lg={8}>
    <Card>Card 1</Card>
  </Col>
  <Col xs={24} sm={12} lg={8}>
    <Card>Card 2</Card>
  </Col>
  <Col xs={24} sm={12} lg={8}>
    <Card>Card 3</Card>
  </Col>
</Row>
```
