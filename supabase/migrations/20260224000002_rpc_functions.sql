-- Rigovo Teams — RPC Functions for Memory Search and Utilities

-- Semantic memory search using cosine similarity
create or replace function search_memories(
  query_embedding vector(384),
  workspace_id uuid,
  match_count integer default 10
)
returns table (
  id uuid,
  workspace_id uuid,
  source_project_id uuid,
  source_task_id uuid,
  content text,
  type text,
  embedding vector(384),
  times_used integer,
  times_used_outside_source integer,
  tags text[],
  created_at timestamptz,
  last_used_at timestamptz,
  similarity float
)
language plpgsql
as $$
begin
  return query
  select
    m.id,
    m.workspace_id,
    m.source_project_id,
    m.source_task_id,
    m.content,
    m.type,
    m.embedding,
    m.times_used,
    m.times_used_outside_source,
    m.tags,
    m.created_at,
    m.last_used_at,
    1 - (m.embedding <=> query_embedding) as similarity
  from memories m
  where m.workspace_id = search_memories.workspace_id
    and m.embedding is not null
  order by m.embedding <=> query_embedding
  limit match_count;
end;
$$;

-- Increment memory usage counters atomically
create or replace function increment_memory_usage(
  memory_id uuid,
  outside_source boolean default false
)
returns void
language plpgsql
as $$
begin
  update memories
  set
    times_used = times_used + 1,
    times_used_outside_source = case
      when outside_source then times_used_outside_source + 1
      else times_used_outside_source
    end,
    last_used_at = now()
  where id = memory_id;
end;
$$;
