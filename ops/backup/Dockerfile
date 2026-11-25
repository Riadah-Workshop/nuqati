# Daily PostgreSQL backup and restore-drill tooling. Same PostgreSQL major version as the `db` service,
# so pg_dump and pg_restore always match the server.
FROM postgres:16-alpine

COPY backup.sh restore_drill.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/backup.sh /usr/local/bin/restore_drill.sh \
    && mkdir -p /backups \
    && chown postgres:postgres /backups

USER postgres
ENTRYPOINT ["/usr/local/bin/backup.sh"]
CMD ["loop"]
