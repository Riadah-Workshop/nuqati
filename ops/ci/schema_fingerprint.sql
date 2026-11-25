-- One line per schema object of schema "public", sorted. Two databases with identical output have the same
-- tables, columns (type, null, default, position), constraints, indexes, sequences, views, triggers, functions,
-- enum types and extensions. The alembic_version table is left out. Used by CI job "Migrations":
--   psql -At -f - < ops/ci/schema_fingerprint.sql
SELECT line FROM (
    SELECT 'column ' || c.relname || '.' || a.attname || ' ' || format_type(a.atttypid, a.atttypmod)
           || CASE WHEN a.attnotnull THEN ' NOT NULL' ELSE ' NULL' END
           || ' default ' || coalesce(pg_get_expr(d.adbin, d.adrelid), '-')
           || ' generated ' || a.attgenerated::text || ' identity ' || a.attidentity::text
           || ' position ' || row_number() OVER (PARTITION BY c.oid ORDER BY a.attnum) AS line
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
      LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
     WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f') AND c.relname <> 'alembic_version'
    UNION ALL
    SELECT 'relation ' || c.relname || ' kind ' || c.relkind::text
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relname NOT LIKE 'alembic\_version%'
    UNION ALL
    SELECT 'constraint ' || c.relname || ' ' || k.conname || ' ' || pg_get_constraintdef(k.oid)
      FROM pg_constraint k
      JOIN pg_class c ON c.oid = k.conrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relname <> 'alembic_version'
    UNION ALL
    SELECT 'index ' || indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename <> 'alembic_version'
    UNION ALL
    SELECT 'sequence ' || sequencename || ' ' || data_type::text || ' start ' || coalesce(start_value::text, '-')
           || ' min ' || coalesce(min_value::text, '-') || ' max ' || coalesce(max_value::text, '-')
           || ' inc ' || coalesce(increment_by::text, '-') || ' cycle ' || cycle::text || ' cache ' || coalesce(cache_size::text, '-')
      FROM pg_sequences WHERE schemaname = 'public'
    UNION ALL
    SELECT 'owned-by ' || s.relname || ' -> ' || t.relname || '.' || a.attname
      FROM pg_depend d
      JOIN pg_class s ON s.oid = d.objid AND d.classid = 'pg_class'::regclass AND s.relkind = 'S'
      JOIN pg_class t ON t.oid = d.refobjid AND d.refclassid = 'pg_class'::regclass
      JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
      JOIN pg_namespace n ON n.oid = s.relnamespace
     WHERE n.nspname = 'public' AND d.deptype IN ('a', 'i') AND t.relname <> 'alembic_version'
    UNION ALL
    SELECT 'view ' || viewname || ' ' || definition FROM pg_views WHERE schemaname = 'public'
    UNION ALL
    SELECT 'trigger ' || pg_get_triggerdef(t.oid)
      FROM pg_trigger t
      JOIN pg_class c ON c.oid = t.tgrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE NOT t.tgisinternal AND n.nspname = 'public'
    UNION ALL
    SELECT 'function ' || p.proname || '(' || pg_get_function_arguments(p.oid) || ')'
      FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public'
    UNION ALL
    SELECT 'type ' || t.typname || ' ' || t.typtype::text
      FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE n.nspname = 'public' AND t.typtype IN ('e', 'd', 'c') AND t.typrelid = 0
    UNION ALL
    SELECT 'extension ' || extname FROM pg_extension WHERE extname <> 'plpgsql'
) fingerprint ORDER BY line COLLATE "C";
