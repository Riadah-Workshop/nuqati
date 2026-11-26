# Daily PostgreSQL backup and restore-drill tooling. Same PostgreSQL major version as the `db` service,
# so pg_dump and pg_restore always match the server. rclone encrypts and copies the dumps off the server (offsite.sh);
# it is only used when NUQATI_OFFSITE is set.
FROM postgres:16-alpine

RUN apk add --no-cache rclone

COPY backup.sh offsite.sh restore_drill.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/backup.sh /usr/local/bin/offsite.sh /usr/local/bin/restore_drill.sh \
    && mkdir -p /backups \
    && chown postgres:postgres /backups

USER postgres
ENTRYPOINT ["/usr/local/bin/backup.sh"]
CMD ["loop"]
