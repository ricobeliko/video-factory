"""Run targeted regression in a disposable source copy, without local secrets.

Uses the current interpreter/dependencies. Config is an empty synthetic TOML;
all application storage lives in the temporary copy. Socket connections are
blocked before pytest imports application modules. No production paths are used.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="closed-loop-regression-") as directory:
        target = Path(directory)
        for folder in ("app", "test", "scripts", "webui", "docs"):
            for source in (root / folder).rglob("*"):
                if source.is_file() and source.suffix in (".py", ".ps1", ".md"):
                    dest = target / source.relative_to(root)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, dest)
        (target / "config.toml").write_text('[app]\n[ui]\n', encoding="utf-8")
        bootstrap = target / "offline_pytest.py"
        bootstrap.write_text(
            "import sys\n"
            "def guard(event, args):\n"
            "    if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.sendto'):\n"
            "        raise RuntimeError('Network disabled during isolated regression')\n"
            "sys.addaudithook(guard)\n"
            "import pytest\n"
            "raise SystemExit(pytest.main(sys.argv[1:]))\n", encoding="utf-8")
        # Copy only OS execution paths, never application/provider environment.
        allowed_env = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
                       "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
                       "PROGRAMDATA", "HOMEDRIVE", "HOMEPATH", "NUMBER_OF_PROCESSORS"}
        env = {key: os.environ[key] for key in os.environ if key.upper() in allowed_env}
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        return subprocess.call([sys.executable, str(bootstrap), "-p", "no:cacheprovider",
                                "--basetemp", str(target / "pytest-tmp"), *sys.argv[1:]], cwd=target, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
