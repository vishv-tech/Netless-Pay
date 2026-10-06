"""Authentication and device enrollment; no seeded accounts or credentials."""
from alembic import op
import sqlalchemy as sa

revision = "0003_authentication"
down_revision = "0002_accounting"
branch_labels = None
depends_on = None

# Frozen DDL generated from the reviewed Sprint 2 model snapshot.
DDL = [
    r"""CREATE TABLE accounts (
	role VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	login_name VARCHAR(128) NOT NULL, 
	participant_id UUID, 
	phone VARCHAR(13), 
	phone_confirmation VARCHAR(32), 
	phone_confirmed_by UUID, 
	phone_confirmed_at TIMESTAMP WITH TIME ZONE, 
	password_hash VARCHAR(512), 
	password_changed_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT account_role CHECK (role IN ('PARTICIPANT', 'ADMIN', 'GATEWAY')), 
	CONSTRAINT account_status CHECK (status IN ('pending', 'active', 'suspended')), 
	CONSTRAINT active_password CHECK (status <> 'active' OR role = 'GATEWAY' OR password_hash IS NOT NULL), 
	CONSTRAINT indian_phone CHECK (phone IS NULL OR phone ~ '^\+91[6-9][0-9]{9}$'), 
	CONSTRAINT account_identity CHECK ((role = 'PARTICIPANT' AND participant_id IS NOT NULL AND phone IS NOT NULL AND phone_confirmation = 'admin-confirmed phone' AND phone_confirmed_by IS NOT NULL AND phone_confirmed_at IS NOT NULL) OR (role <> 'PARTICIPANT' AND participant_id IS NULL AND phone IS NULL)), 
	UNIQUE (login_name), 
	UNIQUE (participant_id), 
	FOREIGN KEY(participant_id) REFERENCES participants (id), 
	UNIQUE (phone), 
	FOREIGN KEY(phone_confirmed_by) REFERENCES accounts (id)
)""",
    r"""CREATE INDEX ix_accounts_phone_confirmed_by ON accounts (phone_confirmed_by)""",
    r"""CREATE TABLE devices (
	participant_id UUID NOT NULL, 
	label VARCHAR(80) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	secret_version INTEGER NOT NULL, 
	encrypted_secret BYTEA NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	last_seen_at TIMESTAMP WITH TIME ZONE, 
	approved_by UUID, 
	approved_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT device_status CHECK (status IN ('pending', 'active', 'revoked')), 
	CONSTRAINT device_secret_version CHECK (secret_version > 0), 
	CONSTRAINT device_revocation CHECK ((status = 'revoked') = (revoked_at IS NOT NULL)), 
	CONSTRAINT device_approval CHECK (status <> 'active' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)), 
	FOREIGN KEY(participant_id) REFERENCES participants (id), 
	FOREIGN KEY(approved_by) REFERENCES accounts (id)
)""",
    r"""CREATE INDEX ix_devices_approved_by ON devices (approved_by)""",
    r"""CREATE INDEX ix_devices_participant_id ON devices (participant_id)""",
    r"""CREATE UNIQUE INDEX one_active_device ON devices (participant_id) WHERE status = 'active'""",
    r"""CREATE TABLE enrollment_tokens (
	account_id UUID NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	redeemed_at TIMESTAMP WITH TIME ZONE, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id), 
	UNIQUE (token_hash)
)""",
    r"""CREATE INDEX ix_enrollment_tokens_account_id ON enrollment_tokens (account_id)""",
    r"""CREATE TABLE auth_sessions (
	account_id UUID NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	device_id UUID, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES accounts (id), 
	UNIQUE (token_hash), 
	FOREIGN KEY(device_id) REFERENCES devices (id)
)""",
    r"""CREATE INDEX ix_auth_sessions_account_id ON auth_sessions (account_id)""",
    r"""CREATE INDEX ix_auth_sessions_device_id ON auth_sessions (device_id)""",
    r"""CREATE TABLE auth_rate_buckets (
	key_hash VARCHAR(64) NOT NULL, 
	window_started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	attempts INTEGER NOT NULL, 
	PRIMARY KEY (key_hash)
)""",
]


def upgrade():
    for statement in DDL:
        op.execute(statement)
    op.execute("""CREATE FUNCTION guard_account_role() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF current_user = 'wallet_runtime' AND NEW.role <> 'PARTICIPANT' THEN
            RAISE EXCEPTION 'Runtime may enroll participants only' USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER account_role_guard BEFORE INSERT ON accounts FOR EACH ROW EXECUTE FUNCTION guard_account_role()")
    op.execute("""CREATE FUNCTION guard_device_history() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.status = 'revoked' OR
           ROW(OLD.id, OLD.participant_id, OLD.secret_version, OLD.encrypted_secret, OLD.created_at)
           IS DISTINCT FROM ROW(NEW.id, NEW.participant_id, NEW.secret_version, NEW.encrypted_secret, NEW.created_at)
           OR (OLD.status = 'active' AND NEW.status = 'pending') THEN
            RAISE EXCEPTION 'Device credential history cannot be changed' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER device_history_guard BEFORE UPDATE ON devices FOR EACH ROW EXECUTE FUNCTION guard_device_history()")


def downgrade():
    tables = ('auth_rate_buckets', 'auth_sessions', 'enrollment_tokens', 'devices', 'accounts')
    op.execute('LOCK TABLE ' + ', '.join(tables) + ' IN ACCESS EXCLUSIVE MODE')
    for table in tables:
        if op.get_bind().scalar(sa.text(f'SELECT EXISTS (SELECT 1 FROM {table})')):
            raise RuntimeError('Cannot remove existing authentication records; use a forward migration')
    for table in tables:
        op.drop_table(table)
    op.execute('DROP FUNCTION guard_device_history()')
    op.execute('DROP FUNCTION guard_account_role()')
