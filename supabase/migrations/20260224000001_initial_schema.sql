-- Rigovo Teams — Initial Database Schema
-- Enables pgvector for semantic memory search

create extension if not exists vector with schema extensions;

-- Workspaces
create table workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  owner_id uuid not null,
  plan text not null default 'free' check (plan in ('free', 'pro', 'enterprise')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index idx_workspaces_owner on workspaces(owner_id);
create index idx_workspaces_slug on workspaces(slug);

-- Projects
create table projects (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  name text not null,
  slug text not null,
  tech_stack jsonb,
  config jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(workspace_id, slug)
);

create index idx_projects_workspace on projects(workspace_id);

-- Tasks
create table tasks (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  project_id uuid references projects(id) on delete set null,
  description text not null,
  type text check (type in ('feature', 'bug', 'refactor', 'incident', 'test', 'infra', 'review')),
  status text not null default 'pending'
    check (status in ('pending', 'classifying', 'assembling', 'running', 'awaiting_approval', 'completed', 'failed')),
  team_assembled boolean default false,
  outcome jsonb,
  lessons_learned text[],
  token_cost_estimate integer,
  duration_ms integer,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now()
);

create index idx_tasks_workspace on tasks(workspace_id);
create index idx_tasks_project on tasks(project_id);
create index idx_tasks_status on tasks(status);

-- Memories (semantic search with pgvector)
create table memories (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  source_project_id uuid references projects(id) on delete set null,
  source_task_id uuid references tasks(id) on delete set null,
  content text not null,
  type text not null check (type in ('lesson', 'pattern', 'preference', 'codebase_context')),
  embedding vector(384),
  times_used integer not null default 0,
  times_used_outside_source integer not null default 0,
  tags text[],
  created_at timestamptz not null default now(),
  last_used_at timestamptz
);

create index idx_memories_workspace on memories(workspace_id);
create index idx_memories_type on memories(type);
create index idx_memories_embedding on memories using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- Audit Logs
create table audit_logs (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references tasks(id) on delete cascade,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  agent_role text not null,
  action_type text not null
    check (action_type in (
      'classify', 'assign', 'generate', 'review', 'fix', 'test',
      'approve', 'reject', 'retry', 'complete', 'fail',
      'memory_store', 'memory_retrieve'
    )),
  input_summary text,
  output_summary text,
  gate_results jsonb,
  fix_packet_id uuid,
  duration_ms integer,
  token_count integer,
  created_at timestamptz not null default now()
);

create index idx_audit_task on audit_logs(task_id);
create index idx_audit_workspace on audit_logs(workspace_id);
create index idx_audit_created on audit_logs(created_at desc);

-- Team Templates
create table team_templates (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references workspaces(id) on delete cascade,
  name text not null,
  description text,
  agents text[] not null,
  config jsonb,
  is_system boolean not null default false,
  created_at timestamptz not null default now()
);

create index idx_templates_workspace on team_templates(workspace_id);
