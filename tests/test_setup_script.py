import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def setup_environment(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("setup 스크립트의 실제 버전 검사에는 Node.js가 필요하다")
    commands = tmp_path / "bin"
    commands.mkdir()
    stub = commands / "stub"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "name = Path(sys.argv[0]).name\n"
        "if name == 'uname':\n"
        "    print(os.environ['TEST_OS'] if sys.argv[1] == '-s' else os.environ['TEST_ARCH'])\n"
        "    sys.exit(0)\n"
        "if name == 'node':\n"
        "    prefix = \"Object.defineProperty(process.versions, 'node', {value: process.env.TEST_NODE_VERSION});\\n\"\n"
        f"    os.execv({node!r}, [{node!r}, '-e', prefix + sys.argv[2]])\n"
        "with open(os.environ['TEST_COMMAND_LOG'], 'a') as log:\n"
        "    log.write(json.dumps({'command': [name, *sys.argv[1:]], 'cwd': os.getcwd()}) + '\\n')\n"
        "if name == os.environ.get('TEST_FAIL_COMMAND'):\n"
        "    sys.exit(17)\n"
    )
    stub.chmod(0o755)
    for command in ["uname", "uv", "node", "npm", "ffmpeg", "ffprobe"]:
        (commands / command).symlink_to(stub)
    (commands / "dirname").symlink_to("/usr/bin/dirname")
    environment = {
        **os.environ,
        "PATH": str(commands),
        "TEST_OS": "Darwin",
        "TEST_ARCH": "arm64",
        "TEST_NODE_VERSION": "26.0.0",
        "TEST_FAIL_COMMAND": "",
        "TEST_COMMAND_LOG": str(tmp_path / "commands.jsonl"),
    }
    return environment, commands


def run_setup(environment, tmp_path):
    return subprocess.run(
        ["/bin/bash", str(ROOT / "scripts/setup.sh")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("version", ["22.22.2", "22.23.0", "24.15.0", "26.0.0"])
def test_setup_installs_locked_dependencies_models_and_checks_from_project_root(
    setup_environment, tmp_path, version
):
    environment, _ = setup_environment
    result = run_setup({**environment, "TEST_NODE_VERSION": version}, tmp_path)
    assert result.returncode == 0, result.stderr
    commands = [
        json.loads(line) for line in Path(environment["TEST_COMMAND_LOG"]).read_text().splitlines()
    ]
    assert [item["command"] for item in commands] == [
        ["uv", "sync", "--frozen", "--extra", "speech"],
        ["npm", "--prefix", "web", "ci"],
        ["uv", "run", "--no-sync", "meetinglog", "prepare-models"],
        ["uv", "run", "--no-sync", "meetinglog", "doctor"],
    ]
    assert all(item["cwd"] == str(ROOT) for item in commands)


@pytest.mark.parametrize("platform,architecture", [("Linux", "arm64"), ("Darwin", "x86_64")])
def test_setup_refuses_unsupported_platform_before_installing(
    setup_environment, tmp_path, platform, architecture
):
    environment, _ = setup_environment
    result = run_setup({**environment, "TEST_OS": platform, "TEST_ARCH": architecture}, tmp_path)
    assert result.returncode != 0
    assert "Apple Silicon" in result.stderr
    assert not Path(environment["TEST_COMMAND_LOG"]).exists()


def test_setup_reports_missing_tools_before_installing(setup_environment, tmp_path):
    environment, commands = setup_environment
    (commands / "ffmpeg").unlink()
    result = run_setup(environment, tmp_path)
    assert result.returncode != 0
    assert "ffmpeg" in result.stderr
    assert not Path(environment["TEST_COMMAND_LOG"]).exists()


@pytest.mark.parametrize("version", ["22.12.0", "22.22.1", "23.4.0", "24.14.9", "25.0.0"])
def test_setup_rejects_unsupported_node_before_installing(setup_environment, tmp_path, version):
    environment, _ = setup_environment
    result = run_setup({**environment, "TEST_NODE_VERSION": version}, tmp_path)
    assert result.returncode != 0
    assert "Node.js" in result.stderr
    assert not Path(environment["TEST_COMMAND_LOG"]).exists()


def test_setup_stops_after_dependency_install_failure(setup_environment, tmp_path):
    environment, _ = setup_environment
    result = run_setup({**environment, "TEST_FAIL_COMMAND": "npm"}, tmp_path)
    assert result.returncode == 17
    commands = [
        json.loads(line)["command"][0]
        for line in Path(environment["TEST_COMMAND_LOG"]).read_text().splitlines()
    ]
    assert commands == ["uv", "npm"]
