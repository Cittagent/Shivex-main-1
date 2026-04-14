from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "simulatorctl.sh"


def test_simulatorctl_purge_removes_standalone_simulators(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "docker.log"
    docker_path = bin_dir / "docker"
    docker_path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f'printf \"%s\\n\" \"$*\" >> \"{log_path}\"',
                'if [[ \"$1 $2\" == \"ps -aq\" ]]; then',
                '  printf \"container-1\\ncontainer-2\\n\"',
                "  exit 0",
                "fi",
                'if [[ \"$1\" == \"rm\" && \"$2\" == \"-f\" ]]; then',
                "  exit 0",
                "fi",
                "exit 0",
            ]
        ),
        encoding="utf-8",
    )
    docker_path.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    completed = subprocess.run(
        [str(SCRIPT_PATH), "purge"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0
    assert "Purged all simulator containers" in completed.stdout
    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert log_lines == [
        "ps -aq --filter name=^/telemetry-simulator-",
        "rm -f container-1 container-2",
    ]
