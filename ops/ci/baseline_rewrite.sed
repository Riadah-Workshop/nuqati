# Part of ops/ci/schema_dump.sh. PostgreSQL prints "col IN ('a', 'b')" on a varchar column as
#   ((col)::text = ANY ((ARRAY['a'::character varying, 'b'::character varying])::text[]))
# but parsing that text again builds a different (equivalent) expression, so a database built from the dump would not
# have exactly the same partial-index predicate as the original (found by the CI schema comparison). Writing the
# original form back makes the baseline rebuild the same expression.
/ANY \(\(ARRAY\[/{
  s/\(\(([a-z_]+)\)::text = ANY \(\(ARRAY\[([^]]*)\]\)::text\[\]\)\)/(\1 IN (\2))/
  s/::character varying//g
}
