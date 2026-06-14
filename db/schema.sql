-- Setup for db.py's pgvector similarity search.
-- Run this in the Supabase SQL editor (Dashboard -> SQL Editor -> New query).
-- The `documents` table already exists; this (re)creates the search function.
--
-- NOTE: the previously-deployed match_documents only returned near-identical
-- vectors and capped output at 1 row, so normal semantic queries returned 0
-- results. This version respects both match_count and match_threshold.

-- pgvector extension (no-op if already enabled).
create extension if not exists vector;

-- Drop ANY existing match_documents overload (regardless of arg order/types),
-- so the create below isn't blocked by a conflicting signature.
do $$
declare
    r record;
begin
    for r in
        select oid::regprocedure as sig
        from pg_proc
        where proname = 'match_documents'
          and pronamespace = 'public'::regnamespace
    loop
        execute 'drop function ' || r.sig;
    end loop;
end $$;

-- Cosine-similarity search over documents.embedding (vector(1024)).
-- Returns the closest `match_count` rows with similarity > match_threshold,
-- highest similarity first.
create function match_documents(
    query_embedding vector(1024),
    match_count int default 5,
    match_threshold float default 0.0
)
returns table (
    id bigint,
    content text,
    source text,
    chunk_index int,
    similarity float
)
language sql
stable
as $$
    select
        d.id,
        d.content,
        d.source,
        d.chunk_index,
        -- <=> is pgvector's cosine distance; 1 - distance = cosine similarity.
        1 - (d.embedding <=> query_embedding) as similarity
    from documents d
    where 1 - (d.embedding <=> query_embedding) > match_threshold
    order by d.embedding <=> query_embedding
    limit match_count;
$$;

-- Make PostgREST pick up the new function immediately.
notify pgrst, 'reload schema';
