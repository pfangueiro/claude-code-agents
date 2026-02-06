# API Guidelines Skill

## Overview
This skill provides comprehensive guidelines for building secure, consistent, and modern API endpoints in Next.js applications using TypeScript, with MariaDB as the database.

## Core Principles

### 1. Security First
- **Always** validate session tokens
- **Always** check permissions before executing actions
- **Never** expose sensitive data in responses
- **Always** sanitize and validate user input
- **Always** use parameterized queries to prevent SQL injection

### 2. Consistency
- Use consistent naming conventions
- Follow RESTful principles
- Maintain consistent error handling
- Use standard HTTP status codes

### 3. Performance
- Use database indexes appropriately
- Implement pagination for list endpoints
- Use caching where appropriate
- Optimize queries before implementation

## Pre-Development Checklist

Before writing any API endpoint code, **ALWAYS** complete these steps:

### Step 1: Database Schema Verification
Use the MariaDB MCP server to:
```bash
# Check if tables exist
SHOW TABLES LIKE 'table_name';

# Verify table structure
DESCRIBE table_name;

# Check indexes
SHOW INDEX FROM table_name;

# Verify foreign key relationships
SELECT 
  TABLE_NAME,
  COLUMN_NAME,
  CONSTRAINT_NAME,
  REFERENCED_TABLE_NAME,
  REFERENCED_COLUMN_NAME
FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
WHERE TABLE_NAME = 'your_table';
```

### Step 2: Permission Validation
- Identify which permission(s) are required
- Check the `/src/constants/permissions.ts` file for available permissions
- Decide between `withAuth`, `withPermission`, or `withAnyPermission`

### Step 3: Query Planning
- Write the SQL query first
- Test it using the MariaDB MCP server
- Check query performance with `EXPLAIN`
- Verify it returns expected results

## API Endpoint Structure

### File Organization
```
src/app/api/
  ├── resource/
  │   ├── route.ts              # GET (list), POST (create)
  │   └── [id]/
  │       ├── route.ts          # GET (single), PUT (update), DELETE
  │       └── sub-resource/
  │           └── route.ts      # Nested resources
```

### Standard Endpoint Template

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { query } from '@/lib/db';
import { Permissions } from '@/constants/permissions';
import { withPermission } from '@/lib/auth/wrappers';

// Force dynamic rendering
export const dynamic = 'force-dynamic';

// GET /api/resource - List resources
export async function GET(request: NextRequest) {
  return withPermission(Permissions.RESOURCE_VIEW)(async (req, session) => {
    try {
      // 1. Parse and validate query parameters
      const searchParams = request.nextUrl.searchParams;
      const page = parseInt(searchParams.get('page') || '1');
      const pageSize = parseInt(searchParams.get('pageSize') || '50');
      
      // Validate parameters
      if (page < 1 || pageSize < 1 || pageSize > 100) {
        return NextResponse.json(
          { error: 'Invalid pagination parameters' },
          { status: 400 }
        );
      }
      
      // 2. Build query with proper escaping
      const offset = (page - 1) * pageSize;
      
      // 3. Get total count
      const countResult = await query(
        'SELECT COUNT(*) as total FROM resource WHERE is_active = 1'
      );
      const total = countResult[0]?.total || 0;
      
      // 4. Get paginated data
      const data = await query(
        `SELECT id, name, created_at, updated_at
         FROM resource
         WHERE is_active = 1
         ORDER BY created_at DESC
         LIMIT ? OFFSET ?`,
        [pageSize, offset]
      );
      
      // 5. Return structured response
      return NextResponse.json({
        data,
        pagination: {
          total,
          page,
          pageSize,
          totalPages: Math.ceil(total / pageSize)
        }
      });
    } catch (error) {
      console.error('Error fetching resources:', error);
      return NextResponse.json(
        { 
          error: 'Internal server error',
          details: error instanceof Error ? error.message : 'Unknown error'
        },
        { status: 500 }
      );
    }
  })(request);
}

// POST /api/resource - Create resource
export async function POST(request: NextRequest) {
  return withPermission(Permissions.RESOURCE_CREATE)(async (req, session) => {
    try {
      // 1. Parse and validate request body
      const body = await req.json();
      const { name, description } = body;
      
      // 2. Validate required fields
      if (!name || name.trim().length === 0) {
        return NextResponse.json(
          { error: 'Name is required' },
          { status: 400 }
        );
      }
      
      // 3. Additional validation
      if (name.length > 255) {
        return NextResponse.json(
          { error: 'Name must be 255 characters or less' },
          { status: 400 }
        );
      }
      
      // 4. Check for duplicates
      const existing = await query(
        'SELECT id FROM resource WHERE name = ? AND is_active = 1',
        [name]
      );
      
      if (existing && existing.length > 0) {
        return NextResponse.json(
          { error: 'Resource with this name already exists' },
          { status: 409 }
        );
      }
      
      // 5. Insert with proper error handling
      const result = await query(
        `INSERT INTO resource (name, description, created_by, created_at)
         VALUES (?, ?, ?, NOW())`,
        [name, description || null, session.jwt.email]
      );
      
      const insertId = (result as any).insertId;
      
      // 6. Fetch and return created resource
      const created = await query(
        'SELECT * FROM resource WHERE id = ?',
        [insertId]
      );
      
      return NextResponse.json({
        success: true,
        message: 'Resource created successfully',
        data: created[0]
      }, { status: 201 });
      
    } catch (error) {
      console.error('Error creating resource:', error);
      return NextResponse.json(
        { error: 'Failed to create resource' },
        { status: 500 }
      );
    }
  })(request);
}
```

### Endpoint with Parameters

```typescript
// PUT /api/resource/[id] - Update resource
export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  return withPermission(Permissions.RESOURCE_UPDATE)(async (req, session) => {
    try {
      // 1. Await and validate params
      const { id } = await params;
      const resourceId = parseInt(id);
      
      if (isNaN(resourceId)) {
        return NextResponse.json(
          { error: 'Invalid resource ID' },
          { status: 400 }
        );
      }
      
      // 2. Check if resource exists
      const existing = await query(
        'SELECT id FROM resource WHERE id = ? AND is_active = 1',
        [resourceId]
      );
      
      if (!existing || existing.length === 0) {
        return NextResponse.json(
          { error: 'Resource not found' },
          { status: 404 }
        );
      }
      
      // 3. Parse and validate body
      const body = await req.json();
      
      // 4. Build dynamic update query
      const updates: string[] = [];
      const values: any[] = [];
      
      if (body.name !== undefined) {
        updates.push('name = ?');
        values.push(body.name);
      }
      
      if (body.description !== undefined) {
        updates.push('description = ?');
        values.push(body.description);
      }
      
      if (updates.length === 0) {
        return NextResponse.json(
          { error: 'No fields to update' },
          { status: 400 }
        );
      }
      
      // Always update metadata
      updates.push('updated_at = NOW()');
      updates.push('updated_by = ?');
      values.push(session.jwt.email);
      
      // Add WHERE clause parameter
      values.push(resourceId);
      
      // 5. Execute update
      await query(
        `UPDATE resource SET ${updates.join(', ')} WHERE id = ?`,
        values
      );
      
      // 6. Return updated resource
      const updated = await query(
        'SELECT * FROM resource WHERE id = ?',
        [resourceId]
      );
      
      return NextResponse.json({
        success: true,
        message: 'Resource updated successfully',
        data: updated[0]
      });
      
    } catch (error) {
      console.error('Error updating resource:', error);
      return NextResponse.json(
        { error: 'Failed to update resource' },
        { status: 500 }
      );
    }
  })(request);
}

// DELETE /api/resource/[id] - Delete resource
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  return withPermission(Permissions.RESOURCE_DELETE)(async (req, session) => {
    try {
      const { id } = await params;
      const resourceId = parseInt(id);
      
      if (isNaN(resourceId)) {
        return NextResponse.json(
          { error: 'Invalid resource ID' },
          { status: 400 }
        );
      }
      
      // Check if resource exists
      const existing = await query(
        'SELECT id FROM resource WHERE id = ? AND is_active = 1',
        [resourceId]
      );
      
      if (!existing || existing.length === 0) {
        return NextResponse.json(
          { error: 'Resource not found' },
          { status: 404 }
        );
      }
      
      // Soft delete (preferred) or hard delete
      await query(
        'UPDATE resource SET is_active = 0, updated_by = ?, updated_at = NOW() WHERE id = ?',
        [session.jwt.email, resourceId]
      );
      
      // OR for hard delete:
      // await query('DELETE FROM resource WHERE id = ?', [resourceId]);
      
      return NextResponse.json({
        success: true,
        message: 'Resource deleted successfully'
      });
      
    } catch (error) {
      console.error('Error deleting resource:', error);
      return NextResponse.json(
        { error: 'Failed to delete resource' },
        { status: 500 }
      );
    }
  })(request);
}
```

## Security Guidelines

### 1. Authentication & Authorization

#### Use the Right Wrapper
```typescript
// No permissions required (just authentication)
import { withAuth } from '@/lib/auth/wrappers';
export const GET = withAuth(async (request, session) => {
  // session contains user info and permissions
});

// Single permission required
import { withPermission } from '@/lib/auth/wrappers';
export const POST = withPermission(Permissions.RESOURCE_CREATE)(
  async (request, session) => {
    // Only executes if user has permission
  }
);

// Any of multiple permissions
import { withAnyPermission } from '@/lib/auth/wrappers';
export const PUT = withAnyPermission(
  Permissions.RESOURCE_UPDATE,
  Permissions.ADMIN
)(async (request, session) => {
  // Executes if user has either permission
});
```

### 2. Input Validation

```typescript
// Always validate input
function validateEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

function validateDateFormat(date: string): boolean {
  const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
  return dateRegex.test(date);
}

// Example usage
if (body.email && !validateEmail(body.email)) {
  return NextResponse.json(
    { error: 'Invalid email format' },
    { status: 400 }
  );
}

// Validate numeric inputs
const id = parseInt(params.id);
if (isNaN(id) || id < 1) {
  return NextResponse.json(
    { error: 'Invalid ID' },
    { status: 400 }
  );
}

// Validate enums
const validStatuses = ['active', 'inactive', 'pending'];
if (body.status && !validStatuses.includes(body.status)) {
  return NextResponse.json(
    { error: `Status must be one of: ${validStatuses.join(', ')}` },
    { status: 400 }
  );
}
```

### 3. SQL Injection Prevention

```typescript
// ✅ CORRECT - Use parameterized queries
const result = await query(
  'SELECT * FROM users WHERE email = ? AND status = ?',
  [email, status]
);

// ❌ WRONG - Never concatenate user input
const result = await query(
  `SELECT * FROM users WHERE email = '${email}'` // DANGEROUS!
);

// ✅ CORRECT - Dynamic WHERE clauses
const whereClauses: string[] = [];
const params: any[] = [];

if (search) {
  whereClauses.push('name LIKE ?');
  params.push(`%${search}%`);
}

if (status) {
  whereClauses.push('status = ?');
  params.push(status);
}

const whereClause = whereClauses.length > 0
  ? `WHERE ${whereClauses.join(' AND ')}`
  : '';

const result = await query(
  `SELECT * FROM users ${whereClause}`,
  params
);
```

### 4. Data Exposure Prevention

```typescript
// ❌ WRONG - Exposing sensitive data
return NextResponse.json({
  user: {
    id: user.id,
    email: user.email,
    password: user.password, // NEVER!
    ssn: user.ssn // NEVER!
  }
});

// ✅ CORRECT - Only expose necessary fields
return NextResponse.json({
  user: {
    id: user.id,
    email: user.email,
    name: user.name,
    role: user.role
  }
});

// ✅ CORRECT - Use SELECT to limit fields
const users = await query(
  `SELECT id, email, name, role, created_at
   FROM users
   WHERE is_active = 1`
);
```

## Database Best Practices

### 1. Use Transactions for Multiple Operations

```typescript
import pool from '@/lib/db';

async function createProjectWithTasks(projectData, tasks) {
  const connection = await pool.getConnection();
  
  try {
    await connection.beginTransaction();
    
    // Insert project
    const [projectResult] = await connection.query(
      'INSERT INTO projects (title, created_by) VALUES (?, ?)',
      [projectData.title, projectData.created_by]
    );
    
    const projectId = (projectResult as any).insertId;
    
    // Insert tasks
    for (const task of tasks) {
      await connection.query(
        'INSERT INTO tasks (project_id, title) VALUES (?, ?)',
        [projectId, task.title]
      );
    }
    
    await connection.commit();
    return projectId;
    
  } catch (error) {
    await connection.rollback();
    throw error;
  } finally {
    connection.release();
  }
}
```

### 2. Optimize Queries

```typescript
// Before implementing, check query performance
// Use MariaDB MCP server:
EXPLAIN SELECT ... FROM ... WHERE ...;

// Add indexes for frequently queried columns
CREATE INDEX idx_user_email ON users(email);
CREATE INDEX idx_project_status ON projects(status_id);
CREATE INDEX idx_created_at ON projects(created_at);

// Use LIMIT for large datasets
const results = await query(
  'SELECT * FROM large_table ORDER BY created_at DESC LIMIT 100'
);

// Implement pagination
const offset = (page - 1) * pageSize;
const results = await query(
  'SELECT * FROM table ORDER BY id DESC LIMIT ? OFFSET ?',
  [pageSize, offset]
);
```

### 3. Handle NULL Values Properly

```typescript
// Use COALESCE for default values
const results = await query(
  `SELECT 
    id,
    name,
    COALESCE(description, '') as description,
    COALESCE(priority, 'Medium') as priority
   FROM tasks`
);

// Handle NULL in INSERT/UPDATE
await query(
  'INSERT INTO projects (title, description) VALUES (?, ?)',
  [title, description || null] // Convert empty string to NULL
);
```

### 4. Date Handling

```typescript
// Format dates for MySQL
function formatDateForMySQL(dateValue: string | null): string | null {
  if (!dateValue) return null;
  
  // Validate format
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateValue)) {
    const date = new Date(dateValue);
    if (isNaN(date.getTime())) return null;
    return date.toISOString().split('T')[0];
  }
  
  return dateValue;
}

// Use NOW() for timestamps
await query(
  'UPDATE resource SET updated_at = NOW() WHERE id = ?',
  [id]
);

// Use CURRENT_TIMESTAMP as default in schema
CREATE TABLE example (
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

## Error Handling

### Standard Error Response Format

```typescript
// Client errors (4xx)
return NextResponse.json(
  {
    error: 'User-friendly error message',
    details: 'More specific details if needed',
    code: 'ERROR_CODE' // Optional
  },
  { status: 400 } // or 401, 403, 404, 409, etc.
);

// Server errors (5xx)
return NextResponse.json(
  {
    error: 'Internal server error',
    details: process.env.NODE_ENV === 'development' 
      ? error.message 
      : undefined
  },
  { status: 500 }
);
```

### HTTP Status Codes

- **200 OK**: Successful GET, PUT, PATCH
- **201 Created**: Successful POST
- **204 No Content**: Successful DELETE (no body)
- **400 Bad Request**: Invalid input
- **401 Unauthorized**: Missing/invalid authentication
- **403 Forbidden**: Valid auth but insufficient permissions
- **404 Not Found**: Resource doesn't exist
- **409 Conflict**: Duplicate resource
- **422 Unprocessable Entity**: Validation failed
- **500 Internal Server Error**: Server error
- **503 Service Unavailable**: Service temporarily unavailable

## Testing Your API

### 1. Manual Testing Checklist

- [ ] Test with valid data
- [ ] Test with missing required fields
- [ ] Test with invalid data types
- [ ] Test with SQL injection attempts
- [ ] Test with XSS attempts
- [ ] Test with extremely long strings
- [ ] Test without authentication
- [ ] Test with wrong permissions
- [ ] Test with non-existent IDs
- [ ] Test pagination edge cases
- [ ] Test concurrent requests

### 2. Using MariaDB MCP for Verification

```bash
# Verify data was inserted
SELECT * FROM table_name WHERE id = last_insert_id;

# Check relationships
SELECT t1.*, t2.*
FROM table1 t1
LEFT JOIN table2 t2 ON t1.id = t2.table1_id
WHERE t1.id = ?;

# Verify soft deletes
SELECT * FROM table_name WHERE is_active = 0;

# Check data integrity
SELECT COUNT(*) FROM table_name WHERE field IS NULL;
```

## Common Patterns

### Pattern 1: Batch Operations

```typescript
export async function POST(request: NextRequest) {
  return withPermission(Permissions.BATCH_UPDATE)(async (req, session) => {
    const { items } = await req.json();
    
    if (!Array.isArray(items) || items.length === 0) {
      return NextResponse.json(
        { error: 'Items array is required' },
        { status: 400 }
      );
    }
    
    // Validate all items first
    for (const item of items) {
      if (!item.id || !item.value) {
        return NextResponse.json(
          { error: 'Each item must have id and value' },
          { status: 400 }
        );
      }
    }
    
    // Use transaction for batch
    const connection = await pool.getConnection();
    try {
      await connection.beginTransaction();
      
      for (const item of items) {
        await connection.query(
          'UPDATE table SET value = ? WHERE id = ?',
          [item.value, item.id]
        );
      }
      
      await connection.commit();
      
      return NextResponse.json({
        success: true,
        message: `Updated ${items.length} items`
      });
      
    } catch (error) {
      await connection.rollback();
      throw error;
    } finally {
      connection.release();
    }
  })(request);
}
```

### Pattern 2: Filtered List with Search

```typescript
export async function GET(request: NextRequest) {
  return withPermission(Permissions.VIEW_LIST)(async (req, session) => {
    const searchParams = request.nextUrl.searchParams;
    const search = searchParams.get('search');
    const status = searchParams.get('status');
    const page = parseInt(searchParams.get('page') || '1');
    const pageSize = parseInt(searchParams.get('pageSize') || '50');
    
    // Build dynamic query
    const whereClauses: string[] = ['is_active = 1'];
    const params: any[] = [];
    
    if (search) {
      whereClauses.push('(name LIKE ? OR description LIKE ?)');
      params.push(`%${search}%`, `%${search}%`);
    }
    
    if (status) {
      whereClauses.push('status = ?');
      params.push(status);
    }
    
    const whereClause = whereClauses.join(' AND ');
    
    // Get count
    const countResult = await query(
      `SELECT COUNT(*) as total FROM resource WHERE ${whereClause}`,
      params
    );
    const total = countResult[0]?.total || 0;
    
    // Get data
    const offset = (page - 1) * pageSize;
    const data = await query(
      `SELECT * FROM resource 
       WHERE ${whereClause}
       ORDER BY created_at DESC
       LIMIT ? OFFSET ?`,
      [...params, pageSize, offset]
    );
    
    return NextResponse.json({
      data,
      pagination: {
        total,
        page,
        pageSize,
        totalPages: Math.ceil(total / pageSize)
      }
    });
  })(request);
}
```

### Pattern 3: Hierarchical Data

```typescript
// Get parent with children
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  return withPermission(Permissions.VIEW_DETAILS)(async (req, session) => {
    const { id } = await params;
    const parentId = parseInt(id);
    
    // Get parent
    const parent = await query(
      'SELECT * FROM parent_table WHERE id = ?',
      [parentId]
    );
    
    if (!parent || parent.length === 0) {
      return NextResponse.json(
        { error: 'Parent not found' },
        { status: 404 }
      );
    }
    
    // Get children
    const children = await query(
      'SELECT * FROM child_table WHERE parent_id = ? ORDER BY display_order',
      [parentId]
    );
    
    return NextResponse.json({
      data: {
        ...parent[0],
        children
      }
    });
  })(request);
}
```

## Checklist Before Committing

- [ ] Verified database schema using MariaDB MCP
- [ ] Checked all tables and columns exist
- [ ] Verified foreign key relationships
- [ ] Tested SQL queries with EXPLAIN
- [ ] Added appropriate indexes
- [ ] Used parameterized queries (no SQL injection)
- [ ] Validated all user inputs
- [ ] Added permission checks
- [ ] Used correct HTTP status codes
- [ ] Handled errors properly
- [ ] Added descriptive error messages
- [ ] Implemented pagination if listing data
- [ ] Used transactions for multi-step operations
- [ ] Tested with various inputs (valid, invalid, edge cases)
- [ ] Removed console.logs (except error logging)
- [ ] Added comments for complex logic
- [ ] Verified no sensitive data exposure

## Quick Reference

### Essential Imports
```typescript
import { NextRequest, NextResponse } from 'next/server';
import { query } from '@/lib/db';
import { Permissions } from '@/constants/permissions';
import { withAuth, withPermission, withAnyPermission } from '@/lib/auth/wrappers';
import pool from '@/lib/db'; // For transactions
```

### Common Query Patterns
```typescript
// Single row
const [row] = await query('SELECT * FROM table WHERE id = ?', [id]);

// Multiple rows
const rows = await query('SELECT * FROM table WHERE status = ?', [status]);

// Insert
const result = await query('INSERT INTO table (field) VALUES (?)', [value]);
const insertId = (result as any).insertId;

// Update
await query('UPDATE table SET field = ? WHERE id = ?', [value, id]);

// Delete/Soft Delete
await query('UPDATE table SET is_active = 0 WHERE id = ?', [id]);
await query('DELETE FROM table WHERE id = ?', [id]);
```

### Response Templates
```typescript
// Success with data
return NextResponse.json({ data, success: true });

// Success with message
return NextResponse.json({ success: true, message: 'Operation completed' });

// Created
return NextResponse.json({ data, success: true }, { status: 201 });

// Error
return NextResponse.json({ error: 'Error message' }, { status: 400 });
```

## Remember

1. **Security is not optional** - Always validate, always check permissions
2. **Test your queries** - Use MariaDB MCP before writing code
3. **Think about scale** - Use pagination, indexes, and efficient queries
4. **Handle errors gracefully** - Users should get helpful messages
5. **Be consistent** - Follow these patterns across all endpoints
6. **Document as you go** - Add comments for complex logic

This skill ensures every API endpoint you create is secure, performant, and maintainable.
