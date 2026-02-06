# Real-World Component Patterns from Codebase

## Table Patterns

### Standard Data Table with Filters
```tsx
import { Table, Input, Select, Button, Space, ConfigProvider, theme } from "antd";
import { SearchOutlined, PlusOutlined } from "@ant-design/icons";
import useSWR from "swr";

export default function DataTable() {
  const { token } = theme.useToken();
  const [searchInput, setSearchInput] = useState("");
  const [selectedFilter, setSelectedFilter] = useState<string | undefined>();
  
  // SWR for data fetching
  const { data, error, isLoading, mutate } = useSWR(apiUrl, fetcher);
  
  return (
    <div style={{ 
      height: "100%", 
      display: "flex", 
      flexDirection: "column",
      overflow: "hidden"
    }}>
      {/* Filters Row */}
      <div style={{ 
        marginBottom: 16, 
        display: "flex", 
        justifyContent: "space-between",
        alignItems: "center",
        gap: "16px"
      }}>
        <div style={{ display: "flex", gap: "8px", flex: 1 }}>
          <Input
            placeholder="Search..."
            value={searchInput}
            onChange={handleSearchChange}
            prefix={<SearchOutlined />}
            style={{ flex: 1 }}
            allowClear
          />
          <Select
            style={{ flex: 1 }}
            value={selectedFilter}
            onChange={setSelectedFilter}
            placeholder="All Items"
            allowClear
          >
            {/* Options */}
          </Select>
        </div>
        
        <div style={{ display: "flex", gap: "8px" }}>
          <Button 
            type="default" 
            icon={<PlusOutlined />}
            onClick={() => setIsAddModalOpen(true)}
          />
        </div>
      </div>

      {/* Table with theme customization */}
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
          loading={isLoading}
          pagination={false}
          size="small"
          scroll={{
            y: 'calc(100vh - 220px)',
            x: 'max-content'
          }}
          style={{
            flex: 1,
            minHeight: 0
          }}
        />
      </ConfigProvider>
    </div>
  );
}
```

### Table Column Definitions
```tsx
import { ColumnsType } from "antd/es/table";
import { Tag, Typography, Avatar, Tooltip } from "antd";
import { useRouter } from "next/navigation";

const { Text } = Typography;

const columns: ColumnsType<DataType> = [
  {
    title: "Name",
    dataIndex: "name",
    key: "name",
    width: 350,
    render: (text: string, record) => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <Text
          strong
          style={{ cursor: 'pointer', fontSize: 12 }}
          onClick={() => router.push(`/items/${record.id}`)}
        >
          {text}
        </Text>
        <Text type="secondary" style={{ fontSize: '11px' }}>
          {record.subtitle}
        </Text>
      </div>
    ),
  },
  {
    title: "Status",
    dataIndex: "status",
    key: "status",
    width: 120,
    render: (_, record) => (
      <Tag
        color={record.status_color || "#d9d9d9"}
        style={{
          borderRadius: "8px",
          fontSize: 12,
        }}
      >
        {record.status_name || "Not Set"}
      </Tag>
    ),
  },
];
```

## Modal Patterns

### Standard Form Modal
```tsx
import { Modal, Form, Input, Button, Select, message } from "antd";
import { useState } from "react";

interface AddModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export default function AddModal({ isOpen, onClose, onSuccess }: AddModalProps) {
  const [form] = Form.useForm();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setIsSubmitting(true);
      
      const response = await axiosInstance.post("/api/endpoint", values);
      
      if (response.status === 201) {
        message.success("Created successfully");
        form.resetFields();
        onSuccess();
        onClose();
      }
    } catch (error: any) {
      if (error.response?.data?.error) {
        message.error(error.response.data.error);
      } else {
        message.error("Failed to create");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      title="Add New Item"
      open={isOpen}
      onCancel={onClose}
      footer={null}
      maskClosable={true}
      width={600}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
      >
        <Form.Item
          name="name"
          label="Name"
          rules={[{ required: true, message: "Please enter a name" }]}
        >
          <Input placeholder="Enter name" />
        </Form.Item>

        <Form.Item
          name="description"
          label="Description"
        >
          <Input.TextArea
            placeholder="Enter description"
            rows={4}
            maxLength={500}
          />
        </Form.Item>

        <Form.Item style={{ marginBottom: 0, marginTop: 16, textAlign: "right" }}>
          <Button onClick={onClose} style={{ marginRight: 8 }}>
            Cancel
          </Button>
          <Button htmlType="submit" loading={isSubmitting}>
            Create
          </Button>
        </Form.Item>
      </Form>
    </Modal>
  );
}
```

## Card Patterns

### Stream/Category Cards
```tsx
import { Avatar, Typography, theme } from "antd";
import { RocketOutlined } from "@ant-design/icons";

const { Text } = Typography;

// Horizontal scrolling card layout
<div style={{
  display: "flex",
  gap: "12px",
  marginBottom: "12px",
  width: "100%",
  overflowX: "auto",
  paddingBottom: "4px",
}}>
  {items.map((item) => {
    const isSelected = selectedItem === item.id.toString();
    return (
      <div
        key={item.id}
        onClick={() => setSelectedItem(isSelected ? undefined : item.id.toString())}
        style={{
          flex: 1,
          minWidth: '200px',
          maxWidth: '280px',
          padding: '12px',
          cursor: 'pointer',
          borderRadius: '8px',
          border: isSelected
            ? '1px solid #F79400'
            : `1px solid ${token.colorBorder}`,
          backgroundColor: isSelected
            ? token.colorFillSecondary
            : token.colorBgContainer,
          boxShadow: '0 1px 2px rgba(0, 0, 0, 0.04)',
        }}
      >
        {/* Header */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          marginBottom: '8px'
        }}>
          <RocketOutlined style={{
            fontSize: '16px',
            color: isSelected ? '#F79400' : token.colorTextSecondary,
          }} />
          <Text strong style={{
            fontSize: '14px',
            flex: 1,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap'
          }}>
            {item.name}
          </Text>
          <Text style={{
            fontSize: '16px',
            fontWeight: 600,
            color: isSelected ? '#F79400' : token.colorText,
          }}>
            {item.count}
          </Text>
        </div>

        {/* Owner info with avatar */}
        {item.owner_name && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            paddingTop: '6px',
            borderTop: `1px solid ${token.colorBorderSecondary}`
          }}>
            <Avatar size={24} src={item.owner_pic} />
            <div style={{ flex: 1, overflow: 'hidden' }}>
              <Text style={{
                fontSize: '12px',
                lineHeight: '18px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                display: 'block'
              }}>
                {item.owner_name}
              </Text>
              <Text type="secondary" style={{
                fontSize: '11px',
                color: token.colorTextTertiary
              }}>
                Owner
              </Text>
            </div>
          </div>
        )}
      </div>
    );
  })}
</div>
```

## Select/Dropdown Patterns

### Select with Avatar Options
```tsx
<Select
  style={{ flex: 1 }}
  value={selectedOwner}
  onChange={setSelectedOwner}
  placeholder="All Owners"
  allowClear
  showSearch
  optionFilterProp="label"
  filterOption={(input, option) =>
    (option?.label ?? '').toString().toLowerCase().includes(input.toLowerCase())
  }
  labelRender={(props) => {
    const selectedItem = items.find((o) => o.email === props.value);
    if (!selectedItem) return props.label;
    
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Avatar size={20} src={selectedItem.pic} />
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {selectedItem.name}
        </span>
      </div>
    );
  }}
>
  {items.map((item) => (
    <Option key={item.email} value={item.email} label={item.name}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%' }}>
        <Avatar size={20} src={item.pic} />
        <span style={{ flex: 1 }}>
          {item.name}
        </span>
        <Text type="secondary" style={{ fontSize: '11px' }}>
          {item.count} items
        </Text>
      </div>
    </Option>
  ))}
</Select>
```

## Avatar Patterns

### Consistent Avatar Color Generation
```tsx
// Generate consistent colors based on name
const getAvatarColor = (name: string): string => {
  const safeName = name || 'unknown';
  let hash = 0;
  for (let i = 0; i < safeName.length; i++) {
    hash = safeName.charCodeAt(i) + ((hash << 5) - hash);
  }
  
  const colors = [
    '#f56a00', '#7265e6', '#ffbf00', '#00a2ae', '#1890ff',
    '#52c41a', '#eb2f96', '#faad14', '#722ed1', '#13c2c2'
  ];
  
  const index = Math.abs(hash) % colors.length;
  return colors[index];
};

// Usage
<Avatar 
  size={24} 
  style={{ backgroundColor: getAvatarColor(user.name) }}
>
  {user.name.charAt(0).toUpperCase()}
</Avatar>

// With image fallback
{user.profilePic ? (
  <Avatar size={24} src={getCachedAvatarUrl(user.profilePic)} />
) : (
  <Avatar size={24} style={{ backgroundColor: getAvatarColor(user.name) }}>
    {user.name.charAt(0).toUpperCase()}
  </Avatar>
)}
```

## Typography Patterns

### Text Hierarchy
```tsx
// Primary text with link
<Text
  strong
  style={{ cursor: 'pointer', fontSize: 12 }}
  onClick={() => router.push(`/path/${id}`)}
>
  Title Text
</Text>

// Secondary text
<Text type="secondary" style={{ fontSize: '11px' }}>
  Subtitle or metadata
</Text>

// Tertiary text
<Text style={{ fontSize: '11px', color: token.colorTextTertiary }}>
  Additional info
</Text>
```

## Status Indicators

### Status Tags with Colors
```tsx
<Tag
  color={record.status_color || "#d9d9d9"}
  style={{
    borderRadius: "8px",
    fontSize: 12,
  }}
>
  {record.status_name || "Not Set"}
</Tag>
```

### Overdue Indicator
```tsx
{isOverdue && (
  <Tooltip title={`Overdue since ${formatDate(record.end_date!)}`}>
    <div style={{
      width: '6px',
      height: '6px',
      borderRadius: '50%',
      backgroundColor: '#ff4d4f',
      flexShrink: 0
    }} />
  </Tooltip>
)}
```

## Loading States

### Skeleton Loading for Cards
```tsx
{data === undefined ? (
  <>
    {[1, 2, 3, 4, 5].map(i => (
      <Card key={i} loading style={{ flex: 1, minWidth: '200px' }} />
    ))}
  </>
) : (
  // Actual content
)}
```

### Table Loading
```tsx
<Table
  loading={isLoading}
  dataSource={data}
  // ...other props
/>
```

## Page Layout Pattern

### Full-height Flex Layout
```tsx
export default function Page() {
  return (
    <div style={{ 
      height: "100%", 
      display: "flex", 
      flexDirection: "column",
      overflow: "hidden",
      padding: "24px 40px 24px 24px"
    }}>
      {/* Page content with proper scroll */}
    </div>
  );
}
```

## Data Fetching Pattern

### SWR with Options
```tsx
import useSWR from "swr";
import { fetcher } from "@/lib/axios";

const { data, error, isLoading, mutate } = useSWR(
  apiUrl,
  fetcher,
  {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
  }
);
```

## Theme Usage

### Using Ant Design Theme Tokens
```tsx
import { theme } from "antd";

const { token } = theme.useToken();

// Then use tokens
<div style={{
  backgroundColor: token.colorBgContainer,
  borderColor: token.colorBorder,
  color: token.colorText,
}}>
```
