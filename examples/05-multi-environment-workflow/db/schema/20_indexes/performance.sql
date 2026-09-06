-- Performance Indexes
-- Optimize common query patterns

-- Users indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_display_name_trgm ON users USING GIN (display_name gin_trgm_ops);

COMMENT ON INDEX idx_users_email IS 'Fast email lookups for authentication';
COMMENT ON INDEX idx_users_created_at IS 'User registration analytics (descending for recent-first)';
COMMENT ON INDEX idx_users_display_name_trgm IS 'Fuzzy search on display names using trigram similarity';

-- Projects indexes
CREATE INDEX IF NOT EXISTS idx_projects_owner_id ON projects(owner_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status) WHERE status != 'deleted';
CREATE INDEX IF NOT EXISTS idx_projects_owner_status ON projects(owner_id, status);
CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at DESC);

COMMENT ON INDEX idx_projects_owner_id IS 'Fast project lookups by owner';
COMMENT ON INDEX idx_projects_status IS 'Filter projects by status (partial index excludes deleted)';
COMMENT ON INDEX idx_projects_owner_status IS 'Composite index for owner-specific status filtering';
COMMENT ON INDEX idx_projects_created_at IS 'Recent projects first';

-- Tasks indexes
CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks(assigned_to) WHERE assigned_to IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date) WHERE due_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee_status ON tasks(assigned_to, status) WHERE assigned_to IS NOT NULL;

COMMENT ON INDEX idx_tasks_project_id IS 'Fast task lookups by project';
COMMENT ON INDEX idx_tasks_assigned_to IS 'Tasks assigned to specific user (partial index excludes unassigned)';
COMMENT ON INDEX idx_tasks_status IS 'Filter tasks by status';
COMMENT ON INDEX idx_tasks_priority IS 'Filter tasks by priority';
COMMENT ON INDEX idx_tasks_due_date IS 'Upcoming deadlines (partial index excludes tasks without due dates)';
COMMENT ON INDEX idx_tasks_project_status IS 'Composite index for project-specific status filtering';
COMMENT ON INDEX idx_tasks_assignee_status IS 'My tasks by status (partial index excludes unassigned)';
