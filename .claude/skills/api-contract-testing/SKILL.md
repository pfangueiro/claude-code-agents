---
name: api-contract-testing
description: Tools and patterns for API contract testing using OpenAPI, JSON Schema, and contract-first development
---

# API Contract Testing Skill

Provides tools and patterns for API contract testing using OpenAPI, JSON Schema, and contract-first development.

## Purpose

This skill provides:
- OpenAPI specification validation
- JSON Schema contract enforcement
- API versioning strategies
- Consumer-driven contract testing (PACT)
- Mock server generation
- Contract regression testing

## When to Use

- "Validate API against OpenAPI spec"
- "Create API contract tests"
- "Generate mock server from OpenAPI"
- "Test API versioning compatibility"
- "Implement consumer-driven contracts"

## OpenAPI Validation

### OpenAPI 3.0 Specification Example

```yaml
openapi: 3.0.0
info:
  title: User API
  version: 1.0.0
  description: User management API

servers:
  - url: https://api.example.com/v1
    description: Production server
  - url: https://staging-api.example.com/v1
    description: Staging server

paths:
  /users:
    get:
      summary: List all users
      operationId: listUsers
      parameters:
        - name: limit
          in: query
          schema:
            type: integer
            minimum: 1
            maximum: 100
            default: 20
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                type: object
                properties:
                  users:
                    type: array
                    items:
                      $ref: '#/components/schemas/User'
                  total:
                    type: integer

    post:
      summary: Create a new user
      operationId: createUser
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/UserCreate'
      responses:
        '201':
          description: User created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/User'
        '400':
          description: Bad request
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'

  /users/{userId}:
    get:
      summary: Get user by ID
      operationId: getUserById
      parameters:
        - name: userId
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/User'
        '404':
          description: User not found

components:
  schemas:
    User:
      type: object
      required:
        - id
        - email
        - name
      properties:
        id:
          type: string
          format: uuid
          readOnly: true
        email:
          type: string
          format: email
        name:
          type: string
          minLength: 1
          maxLength: 100
        createdAt:
          type: string
          format: date-time
          readOnly: true

    UserCreate:
      type: object
      required:
        - email
        - name
      properties:
        email:
          type: string
          format: email
        name:
          type: string
          minLength: 1
          maxLength: 100
        password:
          type: string
          format: password
          minLength: 8

    Error:
      type: object
      required:
        - message
      properties:
        message:
          type: string
        errors:
          type: array
          items:
            type: object
            properties:
              field:
                type: string
              message:
                type: string
```

## Contract Testing with Vitest

```typescript
// tests/api-contract.test.ts
import { describe, it, expect } from 'vitest'
import express from 'express'
import request from 'supertest'
import * as OpenApiValidator from 'express-openapi-validator'
import SwaggerParser from '@apidevtools/swagger-parser'

const SPEC_PATH = './openapi.yaml'

// Mount the validator on a real app. Constructing the middleware proves nothing —
// the spec is only enforced once a request actually flows through it.
// Body parsers must be registered BEFORE the validated routes.
function buildApp() {
  const app = express()
  app.use(express.json())
  app.use(
    OpenApiValidator.middleware({
      apiSpec: SPEC_PATH,
      validateRequests: true,
      validateResponses: true,
    })
  )

  app.post('/users', (req, res) => {
    res.status(201).json({
      id: '3f0c1f6e-1f4a-4c2e-9c3a-6b6d1f2a7e11',
      email: req.body.email,
      name: req.body.name,
      createdAt: new Date().toISOString(),
    })
  })

  // Deliberately spec-violating handler: User requires `email`, this omits it
  app.get('/users/:userId', (req, res) => {
    res.status(200).json({ id: req.params.userId, name: 'Test User' })
  })

  app.use((err, req, res, next) => {
    res.status(err.status || 500).json({
      message: err.message,
      errors: err.errors,
    })
  })

  return app
}

describe('API Contract Tests', () => {
  it('should have valid OpenAPI specification', async () => {
    const api = await SwaggerParser.validate(SPEC_PATH)
    expect(api).toBeDefined()
    expect(api.openapi).toBe('3.0.0')
  })

  // Control: without this, a validator that rejects everything would look healthy
  it('should accept a request that conforms to the spec', async () => {
    const res = await request(buildApp())
      .post('/users')
      .send({ email: 'test@example.com', name: 'Test User' })

    expect(res.status).toBe(201)
  })

  it('should reject a request that violates the spec', async () => {
    // UserCreate requires `name` -> express-openapi-validator throws BadRequest (400)
    const res = await request(buildApp())
      .post('/users')
      .send({ email: 'test@example.com' })

    expect(res.status).toBe(400)
    expect(res.body.message).toMatch(/name/)
  })

  it('should reject a response that violates the spec', async () => {
    // Handler omits the required `email` -> InternalServerError (500)
    const res = await request(buildApp()).get(
      '/users/3f0c1f6e-1f4a-4c2e-9c3a-6b6d1f2a7e11'
    )

    expect(res.status).toBe(500)
    expect(res.body.message).toMatch(/email/)
  })
})
```

## Consumer-Driven Contract Testing (PACT)

### Provider Test (API Server)

```typescript
// tests/pact-provider.test.ts
import { Verifier } from '@pact-foundation/pact'
import path from 'path'

describe('Pact Provider Verification', () => {
  it('should validate against consumer contracts', async () => {
    const opts = {
      provider: 'UserAPI',
      providerBaseUrl: 'http://localhost:3000',
      pactUrls: [
        path.resolve(__dirname, '../pacts/consumer-userapi.json'),
      ],
      stateHandlers: {
        'user exists': async () => {
          // Setup test data
          await db.users.create({
            id: 'test-user-id',
            email: 'test@example.com',
            name: 'Test User',
          })
        },
      },
    }

    await new Verifier(opts).verifyProvider()
  })
})
```

### Consumer Test (Frontend)

```typescript
// tests/pact-consumer.test.ts
import { PactV3, MatchersV3 } from '@pact-foundation/pact'
import { getUserById } from '../api/users'

const { like, iso8601DateTime } = MatchersV3

describe('User API Consumer', () => {
  const provider = new PactV3({
    consumer: 'WebApp',
    provider: 'UserAPI',
  })

  it('should get user by ID', async () => {
    await provider
      .given('user exists')
      .uponReceiving('a request for user by ID')
      .withRequest({
        method: 'GET',
        path: '/users/test-user-id',
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: {
          id: 'test-user-id',
          email: like('test@example.com'),
          name: like('Test User'),
          createdAt: iso8601DateTime(),
        },
      })
      .executeTest(async (mockServer) => {
        const user = await getUserById('test-user-id', mockServer.url)
        expect(user.id).toBe('test-user-id')
        expect(user.email).toMatch(/^.+@.+\..+$/)
      })
  })
})
```

## Mock Server Generation

### Using Prism (OpenAPI Mock Server)

```bash
# Install Prism
npm install -g @stoplight/prism-cli

# Start mock server from OpenAPI spec
prism mock openapi.yaml --port 4010

# Mock server with dynamic examples
prism mock openapi.yaml --dynamic

# Validate requests only (proxy to real API)
prism proxy openapi.yaml https://api.example.com
```

### Postman Collection from OpenAPI

```typescript
// scripts/generate-postman.ts
import { convert } from 'openapi-to-postmanv2'
import fs from 'fs'

const openapiSpec = JSON.parse(fs.readFileSync('./openapi.json', 'utf8'))

convert(
  { type: 'json', data: openapiSpec },
  {},
  (err, conversionResult) => {
    if (!conversionResult.result) {
      console.error('Conversion failed:', conversionResult.reason)
      return
    }

    const collection = conversionResult.output[0].data
    fs.writeFileSync(
      './postman-collection.json',
      JSON.stringify(collection, null, 2)
    )
  }
)
```

## API Versioning Strategies

### URL Versioning

```typescript
// v1/routes.ts
export const v1Routes = {
  '/users': getUsersV1,
  '/users/:id': getUserByIdV1,
}

// v2/routes.ts (breaking change)
export const v2Routes = {
  '/users': getUsersV2, // Returns different schema
  '/users/:id': getUserByIdV2,
}

// app.ts
app.use('/v1', v1Routes)
app.use('/v2', v2Routes)
```

### Header Versioning

```typescript
// middleware/version.ts
export function versionMiddleware(req, res, next) {
  const version = req.headers['api-version'] || '1.0'

  if (version === '1.0') {
    req.apiVersion = 'v1'
  } else if (version === '2.0') {
    req.apiVersion = 'v2'
  } else {
    return res.status(400).json({ error: 'Unsupported API version' })
  }

  next()
}
```

## Contract Regression Testing

```typescript
// tests/contract-regression.test.ts
import { describe, it, expect } from 'vitest'
import SwaggerParser from '@apidevtools/swagger-parser'

describe('API Contract Regression', () => {
  it('should not introduce breaking changes', async () => {
    const previousSpec = await SwaggerParser.validate('./previous-openapi.yaml')
    const currentSpec = await SwaggerParser.validate('./openapi.yaml')

    const prevPaths = previousSpec.paths ?? {}
    const currPaths = currentSpec.paths ?? {}

    // Fail closed. A loop over an empty object asserts nothing and reports green,
    // so an unparsed or empty previous spec would silently certify "no breaking
    // changes". Assert there is something to compare BEFORE comparing it.
    expect(
      Object.keys(prevPaths).length,
      'previous spec declares no paths — nothing was compared'
    ).toBeGreaterThan(0)

    // A path item also holds non-operation keys ($ref, summary, description,
    // servers, parameters). Iterating them blindly reports false breakages.
    const HTTP_METHODS = ['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace']

    // Check that all previous endpoints still exist
    for (const path of Object.keys(prevPaths)) {
      expect(currPaths[path], `path "${path}" was removed`).toBeDefined()

      const prevMethods = Object.keys(prevPaths[path]).filter((k) => HTTP_METHODS.includes(k))
      for (const method of prevMethods) {
        const label = `${method.toUpperCase()} ${path}`
        expect(currPaths[path][method], `${label} was removed`).toBeDefined()

        // Verify response schemas are compatible
        const prevResponses = prevPaths[path][method].responses ?? {}
        const currResponses = currPaths[path][method].responses ?? {}

        for (const statusCode of Object.keys(prevResponses)) {
          expect(
            currResponses[statusCode],
            `${label} no longer documents response ${statusCode}`
          ).toBeDefined()
        }
      }
    }
  })

  it('should maintain backward compatibility for required fields', async () => {
    const previousSpec = await SwaggerParser.validate('./previous-openapi.yaml')
    const currentSpec = await SwaggerParser.validate('./openapi.yaml')

    const prevSchemas = previousSpec.components?.schemas ?? {}
    const currSchemas = currentSpec.components?.schemas ?? {}

    // Fail closed: with no schemas to compare, every assertion below is vacuous
    expect(
      Object.keys(prevSchemas).length,
      'previous spec exposed no schemas'
    ).toBeGreaterThan(0)

    // Never guard the comparison behind `if (prev.required && curr?.required)` —
    // that skips (and so silently passes) the two most common breaking changes.
    for (const schemaName of Object.keys(prevSchemas)) {
      const prevSchema = prevSchemas[schemaName]
      const currSchema = currSchemas[schemaName]

      // Breaking: the schema was removed outright
      expect(currSchema, `schema "${schemaName}" was removed`).toBeDefined()

      const prevRequired = prevSchema.required ?? []
      const currRequired = currSchema.required ?? []

      // Breaking: a field consumers relied on is no longer guaranteed
      for (const field of prevRequired) {
        expect(
          currRequired,
          `"${schemaName}.${field}" is no longer required`
        ).toContain(field)
      }

      // Breaking: a newly required field rejects requests from existing clients.
      // Conservative by design — whitelist a deliberate addition explicitly
      // rather than loosening this into a conditional.
      const addedRequired = currRequired.filter((f) => !prevRequired.includes(f))
      expect(
        addedRequired,
        `"${schemaName}" added required fields`
      ).toEqual([])
    }
  })
})
```

## Best Practices

1. **Contract-First Development**
   - Define OpenAPI spec before implementation
   - Generate types from spec
   - Validate during development

2. **Versioning**
   - Use semantic versioning
   - Deprecate endpoints gradually
   - Document breaking changes

3. **Testing**
   - Test both provider and consumer sides
   - Automate contract validation in CI/CD
   - Run regression tests on spec changes

4. **Documentation**
   - Keep OpenAPI spec in sync with code
   - Generate interactive API docs
   - Provide migration guides for version changes

## Integration with Agents

Works best with:
- **api-backend** agent - Generates OpenAPI specs and validation
- **test-automation** agent - Creates contract tests
- **architecture-planner** agent - Designs API versioning strategy

## Tools & Libraries

- **OpenAPI Validation**: `express-openapi-validator`, `swagger-parser`
- **Contract Testing**: `@pact-foundation/pact`
- **Mock Servers**: `@stoplight/prism-cli`, `json-server`
- **Code Generation**: `openapi-generator`, `swagger-codegen`

## References

- [OpenAPI Specification](https://swagger.io/specification/)
- [Pact Contract Testing](https://docs.pact.io/)
- [API Versioning Best Practices](https://www.postman.com/api-platform/api-versioning/)
