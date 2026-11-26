"""Two-step sign-in for dashboard accounts (TOTP): the secret, the guessing lock and the recovery codes.

Two new tables, nothing else is touched. Without NUQATI_MFA_KEY they stay empty and unused.

    user_mfa                  one row per account that started or finished enrolment. `secret_enc` is the active
                              authenticator secret (AES-256-GCM, see app/mfa.py), `pending_secret_enc` the one being
                              confirmed during enrolment or a device change. `last_step` is the newest accepted
                              30-second step (a code works once). `failed_count`/`locked_until` slow down guessing.
    user_mfa_recovery_codes   one row per recovery code: a salted PBKDF2 hash, never the code itself.

Both are removed together with the account (ON DELETE CASCADE).
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE user_mfa (
            user_id integer NOT NULL,
            secret_enc text,
            pending_secret_enc text,
            confirmed_at timestamp with time zone,
            last_step bigint,
            failed_count integer DEFAULT 0 NOT NULL,
            locked_until timestamp with time zone,
            created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
            CONSTRAINT user_mfa_pkey PRIMARY KEY (user_id),
            CONSTRAINT user_mfa_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )""")
    op.execute("""
        CREATE TABLE user_mfa_recovery_codes (
            id serial NOT NULL,
            user_id integer NOT NULL,
            salt character varying(64) NOT NULL,
            code_hash character varying(128) NOT NULL,
            used_at timestamp with time zone,
            created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
            CONSTRAINT user_mfa_recovery_codes_pkey PRIMARY KEY (id),
            CONSTRAINT user_mfa_recovery_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )""")
    op.execute("CREATE INDEX idx_user_mfa_recovery_codes_user ON user_mfa_recovery_codes (user_id)")


def downgrade():
    # Only enrolments and recovery codes are lost (people enrol again); nothing else depends on these tables.
    op.execute("DROP TABLE user_mfa_recovery_codes")
    op.execute("DROP TABLE user_mfa")
