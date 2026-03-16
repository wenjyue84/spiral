# AI Strategy: Balancing Cost, Quality, and Performance

This document outlines a strategy for building and operating a sophisticated LLM-powered coding agent, focusing on the delicate balance between token efficiency, output quality, and cost management. It provides actionable patterns and implementation context relevant to the Spiral project.

## Executive Summary: The Tiered Agent Strategy

The core strategy is to move away from a single, powerful LLM and toward a **tiered, multi-agent system with a "router"**. This router dynamically assesses task complexity and delegates work to the most appropriate and cost-effective model.

- **Tier 1: Utility/Scaffolding (e.g., GPT-4o-mini, Claude Haiku)**: For simple, repetitive tasks like generating boilerplate, writing unit test shells, or formatting code.
- **Tier 2: Production/Value (e.g., DeepSeek-V3, Claude 3.5 Sonnet)**: The workhorse for most standard coding tasks. `DeepSeek-V3` is the cost leader, while `Claude 3.5 Sonnet` excels at producing clean, maintainable architecture.
- **Tier 3: Frontier/Reasoning (e.g., OpenAI o1-mini, Claude 3.5 Sonnet for complex tasks)**: Reserved for high-complexity tasks like deep debugging, architectural design, or security analysis.

This approach optimizes for the "Cost-Performance Sweet Spot," using the expensive reasoning models only when necessary.

---

## Part 1: Token-Efficient AI Patterns

Reducing token usage is the first and most critical step in managing cost.

### 1. Context Pruning: Send Skeletons, Not Bodies

Instead of sending the full content of dependency files, send only their interfaces or type definitions.

**Example:**
Instead of sending `user.service.ts`, send a "skeleton" `user.service.d.ts`:
```typescript
// Do not send the full 500-line service
// export class UserService { ... full implementation ... }

// Instead, send the interface (or generate it on the fly)
export interface UserService {
  getUser(id: string): Promise<User>;
  updateProfile(id: string, data: Partial<User>): Promise<void>;
  // ... other public methods
}
```
*Implementation*: Use the TypeScript compiler API or a tool like `ts-morph` to extract public interfaces from files before adding them to the LLM context.

### 2. Diff-Based Updates

Instruct the model to return a `diff` or a search/replace block instead of the entire file. This dramatically reduces output tokens, which are the most expensive.

**Prompt Snippet:**
> "Apply the changes to `src/logic.ts`. Provide the output as a standard unified diff. Do not output the full file content."

*Implementation*: The agent can then parse the diff and apply it to the local file.

### 3. Structured Communication with XML

For multi-file contexts, XML tags are more token-efficient and less ambiguous for models like Claude than Markdown.

```xml
<context>
  <file path="src/types.ts">
    export type Status = 'open' | 'closed';
  </file>
  <file path="src/logic.ts">
    import { Status } from './types';
    export const getLabel = (s: Status) => s.toUpperCase();
  </file>
</context>
<task>
  Add a 'pending' state to the Status type and update the getLabel function to handle it.
</task>
```

### 4. Few-Shot Prompting for Architectural Consistency

To ensure the model adheres to Spiral's coding patterns, provide 2-3 examples in the system prompt.

**Example (for NestJS):**
```typescript
// System Prompt:
// Always use the Result<T> wrapper for controller responses.
// Inject services using constructor injection.

// Input: Create a GET endpoint to find a user by ID.
// Output:
@Get(':id')
async findOne(@Param('id') id: string): Promise<Result<UserDto>> {
  const user = await this.userService.findById(id);
  return Result.ok(UserMapper.toDto(user));
}

// --- (New user request comes after this) ---
```

---

## Part 2: Dynamic Model Routing & Complexity Assessment

This is the heart of the cost-saving strategy. We'll create a `LlmRouterService` that first assesses complexity and then calls the appropriate model.

A new file, `lib/llm_router.py`, will be created to house this logic.

---

## Part 3: The Cost vs. Quality Tradeoff (A Practical Framework)

| Task Type | Complexity Score | Recommended Model Tier | Example |
|---|---|---|---|
| **Boilerplate / Scaffolding** | < 20 | **Utility** (GPT-4o-mini) | Generate DTOs, new controller shells. |
| **Simple Logic / Formatting** | 20-40 | **Utility** (GPT-4o-mini) | Write a pure function, format a file. |
| **Standard Feature Work** | 40-70 | **Production/Value** (DeepSeek-V3) | Implement a new API endpoint with business logic. |
| **Refactoring / Clean-Up** | 50-80 | **Production/Value** (Claude 3.5 Sonnet) | Refactor a service to use the Repository pattern. |
| **Complex Debugging** | > 70 | **Frontier/Reasoning** (o1-mini) | Find a race condition in an async process. |
| **New Architecture** | > 80 | **Frontier/Reasoning** (Claude 3.5 Sonnet) | Design a new microservice and its interactions. |

---

## Part 4: Designing a "Cost-Aware" Setup Wizard

A CLI setup wizard should educate the user on these tradeoffs and help them configure their environment.

**Key Principles:**

1.  **Good, Better, Best Presets:** Instead of asking users to pick specific models, offer presets.
    - **`economy`**: "Lowest cost, good for simple tasks. (Default: DeepSeek-V3)"
    - **`balanced`**: "Best for most development, balances cost and quality. (Default: Claude 3.5 Sonnet)"
    - **`quality`**: "Highest quality for complex tasks, higher cost. (Default: o1-mini)"
2.  **Progressive Disclosure:** Hide the model selection behind an "Advanced" option. Most users should just pick a preset.
3.  **Display Estimated Costs:** When asking for an API key, provide a link to the model's pricing page.

A new file, `docs/setup_wizard_example.ts`, will be created to demonstrate this.
