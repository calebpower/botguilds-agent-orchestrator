"""Cheap guard that the shell scripts parse under a POSIX shell (dash).

`sh -n` is a syntax check only, but under dash it also rejects the common
bashisms ([[, arrays, ...) — which matters because the reaper guest and many
targets use dash as /bin/sh. Not a substitute for shellcheck, but it runs
everywhere with no extra dependency.
"""

import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = ["run-live.sh", "redeploy.sh", "analyze-iteration.sh",
           "apply-iteration.sh", "svc.sh", ".githooks/pre-commit"]


@pytest.mark.parametrize("script", SCRIPTS)
def test_shell_script_parses_under_sh(script):
    sh = shutil.which("sh")
    if sh is None:                       # extraordinarily unlikely; name it if so
        pytest.skip("no POSIX sh on PATH")
    path = os.path.join(ROOT, script)
    assert os.path.exists(path), f"missing script: {script}"
    r = subprocess.run([sh, "-n", path], capture_output=True, text=True)
    assert r.returncode == 0, f"{script} failed sh -n:\n{r.stderr}"


@pytest.mark.parametrize("script", SCRIPTS)
def test_shell_script_is_executable_or_hook(script):
    path = os.path.join(ROOT, script)
    # the two entrypoints must be executable; the hook is invoked by git either way
    if script.endswith(".sh"):
        assert os.access(path, os.X_OK), f"{script} is not executable (chmod +x)"
