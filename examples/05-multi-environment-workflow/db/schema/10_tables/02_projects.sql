-- Projects table
-- Stores user projects and workspaces

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',  -- Added via migration 002_add_project_status
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT projects_name_length CHECK (char_length(name) >= 3 AND char_length(name) <= 100),
    CONSTRAINT projects_status_valid CHECK (status IN ('active', 'archived', 'deleted')),
    CONSTRAINT projects_owner_name_unique UNIQUE (owner_id, name)
);

-- Table and column comments
COMMENT ON TABLE projects IS 'User projects and workspaces';
COMMENT ON COLUMN projects.id IS 'Unique project identifier (UUID v4)';
COMMENT ON COLUMN projects.owner_id IS 'Project owner (references users.id)';
COMMENT ON COLUMN projects.name IS 'Project name (3-100 characters, unique per owner)';
COMMENT ON COLUMN projects.description IS 'Project description (optional)';
COMMENT ON COLUMN projects.status IS 'Project status: active, archived, or deleted';
COMMENT ON COLUMN projects.created_at IS 'Project creation timestamp';
COMMENT ON COLUMN projects.updated_at IS 'Last project update timestamp';
