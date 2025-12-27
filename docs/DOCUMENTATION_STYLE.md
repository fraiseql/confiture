# Confiture Documentation Style Guide

**Establish consistent, professional standards across all Confiture documentation.**

---

## 🎯 Purpose

This guide ensures all documentation is:
- **Consistent** - Same structure and format across all files
- **Professional** - Clear, polished, cohesive appearance
- **Discoverable** - Easy to navigate and find information
- **Accessible** - Written for different audience levels

---

## 📋 Standard Guide Structure

All guides should follow this structure to help readers know what to expect:

### 1. **Title & Subtitle** (h1 + tagline)

```markdown
# Medium 1: Build from DDL

**Build fresh PostgreSQL databases from source DDL files in <1 second**
```

- **Line 1**: h1 title (e.g., `# Guide Name`)
- **Line 3**: Bold tagline describing what readers will learn
- Format: `**[What you'll do] in [time/benefit]**`

### 2. **Overview Section** (h2)

```markdown
## What is [Topic]?

[1-3 paragraph explanation]

### Key Concept

> **"[Quote that captures the essence]"**

[Optional: comparison or diagram]
```

**Purpose**: Help readers immediately understand if this guide is for them.

**Content**:
- Clear definition of the concept
- 1-2 sentence summary
- Key concept in blockquote (philosophical/memorable quote)
- Optional: comparison to alternatives

### 3. **When to Use** / **Use Cases** (h2)

```markdown
## When to Use [Feature]

### ✅ Perfect For

- **Scenario 1** - Short description
- **Scenario 2** - Short description

### ❌ Not For

- **Scenario 1** - Short reason why
- **Scenario 2** - Short reason why
```

**Purpose**: Help readers decide if this is the right approach.

**Format**:
- ✅ for positive use cases (with bold header + description)
- ❌ for negative cases
- Short, scannable bullets

### 4. **How It Works** / **Mechanism** (h2)

```markdown
## How [Feature] Works

### The [Process/Architecture/Flow]

[Visual diagram or numbered steps]

### [Specific Aspect 1]

[Detailed explanation]

### [Specific Aspect 2]

[Detailed explanation]
```

**Purpose**: Help readers understand the mechanics.

**Format**:
- ASCII diagrams for architecture/flow
- Numbered steps for processes
- Multiple h3 subsections for complex topics

### 5. **Commands & Usage** / **Getting Started** (h2)

```markdown
## Commands and Usage

### Basic [Operation]

```bash
# Command with inline comment
confiture [command] --flag value
```

**Output**:
```
Expected output here
```

**Explanation**: Brief note on what this does and when to use it.
```

**Purpose**: Provide copy-paste ready examples.

**Format**:
- Code block with language specified (bash, python, yaml, sql)
- Inline comments for clarity
- Always include **Output** section showing expected result
- Always include **Explanation** describing what this does

### 6. **Examples** / **Practical Examples** (h2)

```markdown
## Example: [Scenario]

**Situation**: [Context for why you'd do this]

**Code**:
```python
# filename.py (if applicable)
[working code example]
```

**Output**:
```
✅ Expected success output
```

**Explanation**: [What this demonstrates and when you'd use it]

---

**Next Example**: [Link to another example or related guide]
```

**Purpose**: Show real-world usage patterns.

**Format**:
- h3 subsection for each example
- Start with situation/context
- Include working code
- Show expected output
- Brief explanation
- Link to next steps

### 7. **Common Patterns & Best Practices** (h2)

```markdown
## Best Practices

### 1. [Pattern Name]

**Good**:
```python
[recommended approach]
```

**Bad**:
```python
[anti-pattern]
```

**Why**: [Brief explanation]
```

**Purpose**: Help readers avoid mistakes and use features correctly.

**Format**:
- Numbered practices
- Show "Good" vs "Bad" side-by-side
- Brief explanation of why

### 8. **Troubleshooting** (h2)

```markdown
## Troubleshooting

### ❌ Error: [Error Message]

**Cause**: [Root cause of the error]

**Solution**: [How to fix it]

```bash
# Solution code
confiture [fixed command]
```

**Explanation**: [Why this fixes it]
```

**Purpose**: Help readers solve problems.

**Format**:
- h3 for each error
- Use ❌ emoji for errors
- List cause and solution
- Include code to fix
- Brief explanation

### 9. **Related Topics** / **See Also** (h2)

```markdown
## See Also

- [Topic 1](./guide-1.md) - Brief description
- [Topic 2](../api/guide-2.md) - Brief description
- [Topic 3](../glossary.md#term) - Brief description
```

**Purpose**: Help readers discover related content.

**Format**:
- Bullet list with links and descriptions
- Links to glossary for key terms
- Links to next guides in learning path

### 10. **Next Steps** (h2)

```markdown
## 🎯 Next Steps

**Ready to use [feature]?**
- ✅ You now understand: [3 key takeaways]

**What to do next:**

1. **[Guide 1](./guide-1.md)** - [What it covers]
2. **[Guide 2](./guide-2.md)** - [What it covers]
3. **[Guide 3](./guide-3.md)** - [What it covers]

**Got questions?**
- **[FAQ](./faq.md)** - Common questions
- **[Glossary](./glossary.md)** - Term definitions
- **[Troubleshooting](./troubleshooting.md)** - Common issues
```

**Purpose**: Guide readers to next learning steps.

**Format**:
- "Ready to use...?" section with key takeaways
- Numbered list of next steps with brief descriptions
- "Got questions?" section pointing to help resources

---

## 🎨 Code Block Formatting Standards

### Standard Code Example Format

```markdown
### Example: [What This Does]

\`\`\`[language]
# [filename] or [description]
[code]
\`\`\`

**Output**:
\`\`\`
[Expected output]
\`\`\`

**Explanation**: [What this code does and when to use it]
```

### Examples by Language

#### Python

```markdown
\`\`\`python
# confiture/core/builder.py
async def build(env: str) -> str:
    """Build schema from DDL files."""
    builder = SchemaBuilder(env=env)
    return await builder.build()
\`\`\`

**Output**:
\`\`\`
✅ Schema built in 0.89 seconds
Generated: 15,234 bytes of SQL
\`\`\`

**Explanation**:
The `build()` function concatenates all SQL files from the schema
directory and returns the combined schema.
```

#### Bash / CLI

```markdown
\`\`\`bash
# Build default environment
confiture build --env local

# Or build specific environment
confiture build --env production
\`\`\`

**Output**:
\`\`\`
✅ Building database schema...
📁 Found 15 SQL files in db/schema/
⚙️  Concatenating files... done
🗄️  Executing DDL... done
✅ Build complete in 0.89s
\`\`\`

**Explanation**:
The `confiture build` command reads all SQL files from your schema
directory and executes them on the target database.
```

#### SQL

```markdown
\`\`\`sql
-- db/schema/10_tables/users.sql
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
\`\`\`

**Explanation**:
This creates the users table with email as a unique constraint.
Use `IF NOT EXISTS` to make the migration idempotent.
```

#### YAML

```markdown
\`\`\`yaml
# db/environments/local.yaml
name: local
database:
  host: localhost
  port: 5432
  database: confiture_local
include_dirs:
  - db/schema
  - db/seeds/development
\`\`\`

**Explanation**:
This configuration tells Confiture which directories to include
when building the local development database.
```

### Code Comment Guidelines

- **Use inline comments sparingly** - Only for non-obvious logic
- **Line comments** for "why" not "what"
- **Function docstrings** for public APIs
- **Don't comment obvious code**:
  ```python
  ✅ Good:
  # Validate email format before inserting
  if not is_valid_email(user.email):
      raise ValueError("Invalid email")

  ❌ Bad:
  # Check if email is valid
  if not is_valid_email(user.email):  # This checks validity
      raise ValueError("Invalid email")  # Raise error
  ```

---

## 📐 Heading Hierarchy

Use consistent heading levels throughout all guides:

```markdown
# Main Title (h1)
**Tagline that summarizes guide**

## Major Section (h2)
Introductory paragraph

### Subsection (h3)
Details about the subsection

#### Details (h4)
More specific information

##### Very Specific (h5)
Use rarely - indicates too much nesting
```

**Rules**:
- ✅ Every guide starts with single `# Title`
- ✅ Use `##` for major sections
- ✅ Use `###` for subsections
- ✅ Use `####` for details within subsections
- ❌ Never skip levels (no `# → ####`)
- ❌ Don't use h5 or h6 (indicates over-nesting)
- ✅ One h1 per document

---

## 🎯 Inline Formatting Standards

### Text Formatting

```markdown
**Bold** - Important terms, button names, emphasis
*Italic* - Book titles, terms being defined
`Code` - Variable names, file paths, commands
[Links](./target.md) - Cross-references, external URLs
> Blockquotes - Important concepts, quotes
```

### Emoji Usage

Use emoji strategically for scannability:

```markdown
✅ - Success, positive use cases, working examples
❌ - Failures, negative use cases, what not to do
⚠️ - Warnings, caution, be careful
🎯 - Goals, objectives, targets
📋 - Lists, examples, checklists
🚀 - Advanced topics, optimization
🔍 - Details, technical specifics
💡 - Tips, insights, best practices
```

**Rules**:
- ✅ Use emoji at start of bullet points
- ✅ Use sparingly (don't overdo it)
- ✅ Use consistently (same emoji for same meaning)
- ❌ Don't use emoji in code blocks
- ❌ Don't use multiple emoji per line

### Lists and Bullets

```markdown
✅ Unordered list item
✅ Another item
✅ Third item

1. **First step** - Description
2. **Second step** - Description
3. **Third step** - Description

| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Content  | Content  | Content  |
```

**Rules**:
- ✅ Use emoji for unordered lists (scannability)
- ✅ Use numbers for steps/sequences
- ✅ Tables for comparisons
- ✅ Brief descriptions after list items
- ❌ Don't nest lists more than 2 levels deep

---

## 🔗 Linking Standards

### Internal Links

```markdown
# Same directory (guides/)
[Guide Name](./another-guide.md)

# Parent directory (docs/)
[Getting Started](../getting-started.md)

# Glossary definitions
[DDL](../glossary.md#ddl)

# API documentation
[Builder API](../api/builder.md)
```

**Rules**:
- ✅ Use relative paths for internal links
- ✅ Link glossary terms on first mention
- ✅ Use descriptive link text (not "click here")
- ✅ One glossary link per guide for each term
- ❌ Don't use `file:///` absolute paths

### External Links

```markdown
[External Resource](https://example.com)
[PostgreSQL Docs](https://www.postgresql.org/docs/)
```

**Rules**:
- ✅ Use full HTTPS URLs
- ✅ Link to official documentation
- ❌ Don't link to blog posts or unstable URLs

---

## ✏️ Writing Standards

### Tone & Voice

- **Professional but friendly** - Not stiff, not casual
- **Clear and direct** - Avoid jargon where possible
- **Active voice** - "Build the database" not "The database is built"
- **Second person** - "You can configure..." not "One can configure..."

### Sentence & Paragraph Structure

- **Sentences**: 15-20 words average
- **Paragraphs**: 3-5 sentences maximum
- **Use short sentences for clarity**
- **Break up dense information**

**Example - Before** (Dense):
```
The Foreign Data Wrapper (FDW) strategy performs zero-downtime
migrations by creating a shadow schema on the target database using
PostgreSQL's FDW feature to read from the source schema, allows
concurrent modifications to happen on the source while data is being
transferred, and uses logical replication for incremental changes
until cutover.
```

**Example - After** (Readable):
```
The Foreign Data Wrapper (FDW) strategy enables zero-downtime
migrations. Here's how it works:

1. Create a shadow schema on the target database
2. Use FDW to read live data from the source
3. Allow concurrent changes on the source
4. Sync incrementally until ready
5. Cutover with zero downtime
```

### Technical Accuracy

- ✅ Use correct terminology (link to glossary if needed)
- ✅ Verify all code examples work
- ✅ Test all CLI commands before documenting
- ✅ Update docs when features change
- ❌ Don't use placeholder terminology

---

## 📊 File Organization

### Directory Structure

```
docs/
├── README.md              # Main entry point
├── glossary.md            # Term definitions
├── getting-started.md     # Beginner guide
├── DOCUMENTATION_STYLE.md # This file
│
├── guides/                # User guides (how-to)
│   ├── medium-1-*.md
│   ├── medium-2-*.md
│   ├── medium-3-*.md
│   ├── medium-4-*.md
│   └── migration-decision-tree.md
│
├── api/                   # API documentation
│   ├── builder.md
│   ├── migrator.md
│   └── syncer.md
│
├── reference/             # Reference docs
│   ├── cli.md
│   └── configuration.md
│
└── examples/              # Real-world examples
    ├── example-1/
    ├── example-2/
    └── README.md
```

### Naming Conventions

```
✅ medium-1-build-from-ddl.md      (guide: lowercase, hyphens)
✅ api-builder.md                  (API: api- prefix)
✅ cli-reference.md                (Reference: specific name)
✅ DOCUMENTATION_STYLE.md          (System files: UPPERCASE)

❌ medium_1_build_from_ddl.md      (Use hyphens, not underscores)
❌ Medium1BuildFromDDL.md          (Use lowercase for guides)
❌ guide-1.md                      (Use descriptive names)
```

---

## ✅ Pre-Publication Checklist

Before committing documentation changes:

- [ ] **Title & Tagline**: Clear one-liner about what readers will learn
- [ ] **Overview**: Explains "what" and "why"
- [ ] **Use Cases**: Clear "Perfect For" / "Not For" sections
- [ ] **How It Works**: Mechanism or architecture explained
- [ ] **Examples**: At least 1 working copy-paste example
- [ ] **Code blocks**: All have language specified, output shown
- [ ] **Glossary links**: Key terms linked on first mention
- [ ] **Cross-links**: Related guides linked in "See Also"
- [ ] **Next Steps**: Guide readers to next learning steps
- [ ] **Heading hierarchy**: No skipped levels
- [ ] **Spelling & grammar**: No obvious typos
- [ ] **Links**: All relative links work (no 404s)
- [ ] **Code examples**: All tested and working
- [ ] **Consistency**: Follows this style guide

---

## 🚀 Common Template

Copy this template for new guides:

```markdown
# [Guide Title]

**[One-sentence description of what readers will learn]**

---

## What is [Topic]?

[Explanation paragraph]

### Key Concept

> **"[Memorable quote capturing essence]"**

---

## When to Use [Feature]

### ✅ Perfect For

- **Scenario 1** - [Brief description]
- **Scenario 2** - [Brief description]

### ❌ Not For

- **Scenario 1** - [Why not]

---

## How [Feature] Works

### [Aspect 1]

[Explanation with optional diagram]

### [Aspect 2]

[Explanation]

---

## Commands and Usage

### [Operation]

\`\`\`bash
confiture [command]
\`\`\`

**Output**:
\`\`\`
[Expected output]
\`\`\`

**Explanation**: [What this does]

---

## Example: [Scenario]

**Situation**: [Context]

\`\`\`python
[Working code]
\`\`\`

**Explanation**: [What this demonstrates]

---

## Best Practices

### [Practice 1]

**Good**:
\`\`\`
[Recommended approach]
\`\`\`

**Bad**:
\`\`\`
[Anti-pattern]
\`\`\`

---

## Troubleshooting

### ❌ Error: [Error Message]

**Cause**: [Root cause]

**Solution**: [How to fix]

---

## See Also

- [Related Guide](./link.md) - Description
- [API Reference](../api/api.md) - Description

---

## 🎯 Next Steps

**Ready to use [feature]?**
- ✅ You now understand: [3 key takeaways]

**What to do next:**

1. **[Next Guide](./guide.md)** - Description
2. **[Concept Guide](./guide.md)** - Description
3. **[API Reference](../api/api.md)** - Description

---

*Part of Confiture documentation* 🍓

*Making migrations sweet and simple*
```

---

## Questions?

If you have questions about documentation style:

1. Check this guide first
2. Look at recent commits to see examples
3. Ask in project discussions

**Most Important**: Consistency > Perfection. When in doubt, match the style of existing guides.

---

**Last Updated**: December 27, 2025
**Status**: Active Guide
**Version**: 1.0

