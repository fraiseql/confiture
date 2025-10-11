# Confiture Examples

Practical examples demonstrating Confiture's migration workflows.

## Available Examples

### [Basic: Blog Application](./basic/)

**Perfect for**: Learning Confiture basics

A simple blog application with users, posts, and comments.

**What you'll learn**:
- ✅ Project initialization
- ✅ Schema organization
- ✅ Migration generation
- ✅ Applying and rolling back migrations
- ✅ Testing migrations locally

**Database**: 3 tables (users, posts, comments)

**Time to complete**: 15 minutes

[→ Go to Basic Example](./basic/README.md)

---

## Coming Soon

### Advanced: E-commerce Platform

**Perfect for**: Complex schemas and data transformations

An e-commerce platform with products, orders, payments, and inventory.

**What you'll learn**:
- ✅ Complex foreign key relationships
- ✅ Data migrations (transforming existing data)
- ✅ Handling large datasets
- ✅ Production deployment strategies

**Database**: 10+ tables

---

### FraiseQL Integration

**Perfect for**: GraphQL-first development

Integrate Confiture with FraiseQL to automatically generate migrations from GraphQL schema changes.

**What you'll learn**:
- ✅ GraphQL → PostgreSQL mapping
- ✅ Automatic migration generation
- ✅ Type-safe database queries
- ✅ Full-stack GraphQL app

---

## Quick Start

Each example includes:

1. **README.md** - Complete tutorial
2. **Schema files** - DDL in `db/schema/`
3. **Migrations** - Pre-written migrations in `db/migrations/`
4. **Configuration** - Environment configs in `db/environments/`
5. **Sample data** - SQL scripts to populate database

### Running an Example

```bash
# 1. Navigate to example
cd examples/basic

# 2. Create database
createdb blog_app_local

# 3. Apply migrations
confiture migrate up --config db/environments/local.yaml

# 4. Verify
psql blog_app_local -c "\dt"
```

## Example Structure

All examples follow this structure:

```
example-name/
├── README.md                       # Tutorial and documentation
├── db/
│   ├── schema/                     # DDL source files
│   │   ├── 00_common/              # Extensions, types
│   │   └── 10_tables/              # Table definitions
│   ├── migrations/                 # Python migrations
│   │   ├── 001_initial.py
│   │   └── 002_add_feature.py
│   └── environments/               # Configuration
│       ├── local.yaml
│       └── production.yaml
├── sample_data/                    # SQL scripts
│   └── seed.sql
└── .gitignore
```

## Learning Path

### Beginner

1. **[Basic Example](./basic/)** - Start here!
2. Read [Getting Started Guide](../docs/getting-started.md)
3. Read [CLI Reference](../docs/cli-reference.md)

### Intermediate

1. Review [Migration Strategies](../docs/migration-strategies.md)
2. Practice with your own project
3. Test production deployment

### Advanced

1. Study [FraiseQL Integration](../docs/fraiseql-integration.md) *(coming soon)*
2. Implement zero-downtime migrations
3. Use advanced diff features

## Tips for Learning

### 1. Follow the README

Each example has a detailed README with:
- Step-by-step instructions
- Expected output
- Troubleshooting tips
- Common operations

### 2. Experiment Freely

```bash
# Try things out
confiture migrate up
confiture migrate down
confiture migrate status

# Break things!
# Then fix them:
confiture migrate down
confiture migrate up
```

### 3. Read the Migrations

Open the migration files and understand:
- How `up()` applies changes
- How `down()` rolls back
- SQL best practices
- Transaction handling

### 4. Check the Database

```bash
# Connect to database
psql blog_app_local

# Explore schema
\dt                    # List tables
\d users              # Describe table
\di                   # List indexes

# Check migrations
SELECT * FROM confiture_migrations;
```

## Contributing Examples

Have a great example to share? We'd love to include it!

Requirements:
- Complete README with tutorial
- Working schema and migrations
- Sample data (optional)
- Tested on PostgreSQL 12+

Submit a PR to: https://github.com/fraiseql/confiture

## Resources

- **[Documentation](../docs/)** - Complete guides
- **[GitHub](https://github.com/fraiseql/confiture)** - Source code
- **[FraiseQL](https://github.com/fraiseql/fraiseql)** - GraphQL framework

---

**Part of the FraiseQL family** 🍓

*Vibe-engineered with ❤️ by [evoludigit](https://github.com/evoludigit)*
