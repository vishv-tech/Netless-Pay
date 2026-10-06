"""Windows-only initializer check using synthetic files, never backend/.env."""
import base64
from pathlib import Path
import secrets
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[2]
    scratch = root / "build" / "local-config-checks"
    scratch.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="synthetic-", dir=scratch)
    target = Path(temporary.name).resolve()
    # Cleanup is constrained to a generated child of this workspace's ignored build tree.
    assert target.is_relative_to(scratch.resolve())
    try:
        backend = target / "backend"
        scripts = backend / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "init-local.ps1").write_bytes((root / "backend/scripts/init-local.ps1").read_bytes())
        (backend / ".env.example").write_bytes((root / "backend/.env.example").read_bytes())

        def run():
            result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(scripts / "init-local.ps1")], capture_output=True, text=True)
            assert result.returncode == 0, "Initializer failed (output withheld to protect credentials)"
            data = dict(line.split("=", 1) for line in (backend / ".env").read_text(encoding="utf-8-sig").splitlines()
                        if "=" in line and not line.startswith("#"))
            assert all(data[key] not in result.stdout + result.stderr for key in
                       ("DB_PASSWORD", "DB_ADMIN_PASSWORD", "MIGRATION_DB_PASSWORD", "DEVICE_MASTER_KEY"))
            assert len(base64.urlsafe_b64decode(data["DEVICE_MASTER_KEY"])) == 32
            return data

        fresh = run()
        assert fresh == run(), "Initializer changed existing credentials"
        legacy_password = secrets.token_hex(32)
        (backend / ".env").write_text("DB_USER=legacy_owner\nDB_PASSWORD=" + legacy_password + "\nDB_NAME=legacy_db\n")
        upgraded = run()
        assert upgraded["DB_ADMIN_USER"] == "legacy_owner" and upgraded["DB_ADMIN_PASSWORD"] == legacy_password
        assert upgraded["DB_USER"] == "wallet_runtime" and upgraded["DB_PASSWORD"] != legacy_password
        assert upgraded["DB_NAME"] == "legacy_db" and upgraded == run()
        print("PASS isolated initializer: fresh generation, redaction, legacy preservation and stable repeat runs")
    finally:
        temporary.cleanup()


if __name__ == "__main__":
    main()
