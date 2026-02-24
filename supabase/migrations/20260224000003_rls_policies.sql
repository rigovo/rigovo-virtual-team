-- Rigovo Teams — Row Level Security Policies
-- Every table is protected. Users can only access data in their workspaces.

alter table workspaces enable row level security;
alter table projects enable row level security;
alter table tasks enable row level security;
alter table memories enable row level security;
alter table audit_logs enable row level security;
alter table team_templates enable row level security;

-- Workspaces: owners can read/write their own
create policy "workspace_owner_select"
  on workspaces for select
  using (owner_id = auth.uid());

create policy "workspace_owner_insert"
  on workspaces for insert
  with check (owner_id = auth.uid());

create policy "workspace_owner_update"
  on workspaces for update
  using (owner_id = auth.uid());

-- Projects: workspace members can access
create policy "project_workspace_select"
  on projects for select
  using (
    workspace_id in (select id from workspaces where owner_id = auth.uid())
  );

create policy "project_workspace_insert"
  on projects for insert
  with check (
    workspace_id in (select id from workspaces where owner_id = auth.uid())
  );

create policy "project_workspace_update"
  on projects for update
  using (
    workspace_id in (select id from workspaces where owner_id = auth.uid())
  );

-- Tasks: workspace scoped
create policy "task_workspace_select"
  on tasks for select
  using (
    workspace_id in (select id from workspaces where owner_id = auth.uid())
  );

create policy "task_workspace_insert"
  on tasks for insert
  with check (
    workspace_id in (select id from workspaces where owner_id = auth.uid())
  );

create policy "task_workspace_update"
  on tasks for update
  using (
    workspace_id in (select id from workspaces where owner_id = auth.uid())
  );

-- Memories: workspace scoped (flat — no project scoping)
create policy "memory_workspace_select"
  on memories for select
  using (
    workspace_id in (select id from workspaces where owner_id = auth.uid())
  );

create policy "memory_workspace_insert"
  on memories for insert
  with check (
    workspace_id in (select id from workspaces where owner_id = auth.uid())
  );

create policy "memory_workspace_delete"
  on memories for delete
  using (
    workspace_id in (select id from workspaces where owner_id = auth.uid())
  );

-- Audit Logs: read-only for workspace owners
create policy "audit_workspace_select"
  on audit_logs for select
  using (
    workspace_id in (select id from workspaces where owner_id = auth.uid())
  );

create policy "audit_workspace_insert"
  on audit_logs for insert
  with check (
    workspace_id in (select id from workspaces where owner_id = auth.uid())
  );

-- Team Templates: workspace scoped + system templates visible to all
create policy "template_select"
  on team_templates for select
  using (
    is_system = true
    or workspace_id in (select id from workspaces where owner_id = auth.uid())
  );

create policy "template_workspace_insert"
  on team_templates for insert
  with check (
    workspace_id in (select id from workspaces where owner_id = auth.uid())
  );
