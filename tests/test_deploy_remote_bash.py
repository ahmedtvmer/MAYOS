import os
import json
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "deploy" / "deploy_server.sh"


def test_remote_bash_preserves_empty_and_spaced_arguments(tmp_path):
    stub = tmp_path / "ssh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "shift\n"
        "command=\"$*\"\n"
        "exec bash -c \"$command\"\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; ssh_target=selftest; remote_bash "" "two words"', "test", str(SCRIPT)],
        input='printf "%s\\n" "$#" "$1" "$2"\n',
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["2", "", "two words"]
    # The old `bash -s -- "${remote_args[@]}"` expansion loses the empty value
    # when ssh joins its arguments into the remote command string.


def _run_deploy_release(tmp_path, readiness_result):
    log = tmp_path / "calls.log"
    harness = r'''
source "$1"
log="$2"
current_tag=""
record() { printf '%s\n' "$1" >> "$log"; }
upload_build_input() { record upload_build_input; }
set_image_tag() { record set_image_tag; }
build_and_start() { record build_and_start; }
check_readiness() { record check_readiness; return "$READINESS_RESULT"; }
start_companion_services() { record start_companion_services; }
remember_image() { record remember_image; }
prune_images() { record prune_images; }
prune_build_cache_and_report_disk() { record prune_build_cache_and_report_disk; }
restore_previous_after_failure() { record restore_previous_after_failure; }
deploy_release fakecommit faketag
'''
    env = os.environ.copy()
    env["READINESS_RESULT"] = str(readiness_result)
    return subprocess.run(
        ["bash", "-c", harness, "test", str(SCRIPT), str(log)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    ), log


def test_companion_services_start_after_successful_readiness(tmp_path):
    result, log = _run_deploy_release(tmp_path, 0)
    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert calls.index("check_readiness") < calls.index("start_companion_services")
    assert calls.index("start_companion_services") < calls.index("remember_image")


def test_companion_services_do_not_start_when_readiness_fails(tmp_path):
    result, log = _run_deploy_release(tmp_path, 1)
    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert "restore_previous_after_failure" in calls
    assert "start_companion_services" not in calls


def _verify_checks(tmp_path, payload, required="First|Second", curl_fails=False):
    curl = tmp_path / "curl"
    curl.write_text("#!/usr/bin/env bash\n" + ("exit 22\n" if curl_fails else f"printf '%s' '{payload}'\n"), encoding="utf-8")
    curl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
    env["MAYOS_REQUIRED_CHECKS"] = required
    return subprocess.run(
        ["bash", "-c", 'source "$1"; verify_required_checks abc123', "test", str(SCRIPT)],
        text=True, capture_output=True, env=env, check=False,
    )


def test_server_pull_requires_each_named_successful_check(tmp_path):
    payload = '{"check_runs":[{"name":"First","status":"completed","conclusion":"success"},{"name":"Second","status":"completed","conclusion":"success"}]}'
    result = _verify_checks(tmp_path, payload)
    assert result.returncode == 0, result.stderr


def test_server_pull_refuses_missing_pending_and_failed_checks(tmp_path):
    for run in (
        '{"check_runs":[{"name":"First","status":"completed","conclusion":"success"}]}',
        '{"check_runs":[{"name":"First","status":"completed","conclusion":"success"},{"name":"Second","status":"in_progress","conclusion":null}]}',
        '{"check_runs":[{"name":"First","status":"completed","conclusion":"success"},{"name":"Second","status":"completed","conclusion":"failure"}]}',
    ):
        result = _verify_checks(tmp_path, run)
        assert result.returncode != 0
        assert "Second" in result.stdout


def test_server_pull_refuses_github_api_errors(tmp_path):
    result = _verify_checks(tmp_path, "", curl_fails=True)
    assert result.returncode != 0
    assert "GitHub check-runs API failed" in result.stdout


def test_server_pull_refuses_malformed_commit_before_fetch(tmp_path):
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; server_checkout=/unused; verify_pull_commit not-a-sha', "test", str(SCRIPT)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode != 0
    assert "commit must be a lowercase hexadecimal SHA" in result.stdout


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _bash_path(path):
    value = str(path)
    if len(value) > 2 and value[1:3] == ":\\":
        return "/" + value[0].lower() + value[2:].replace("\\", "/")
    return value


def _pull_fixture(tmp_path, *, inputs=True, checks=None):
    origin = tmp_path / "origin"
    work = tmp_path / "work"
    root = tmp_path / "server"
    (work / "data").mkdir(parents=True)
    (work / "data" / ".gitkeep").write_text("\n", encoding="utf-8")
    (work / "deploy").mkdir()
    (work / "deploy" / "compose.server.yaml").write_text("services: {}\n", encoding="utf-8")
    (work / "deploy" / "deploy_server.sh").write_bytes(SCRIPT.read_bytes())
    guard = SCRIPT.parent / "rollback_guard.py"
    (work / "deploy" / "rollback_guard.py").write_bytes(guard.read_bytes())
    subprocess.run(["git", "init", "--bare", "--initial-branch=master", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "init", "--initial-branch=master", str(work)], check=True, capture_output=True)
    _git(work, "config", "user.email", "test@example.invalid")
    _git(work, "config", "user.name", "Test")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "master commit")
    master_sha = _git(work, "rev-parse", "HEAD")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-u", "origin", "master")
    _git(work, "checkout", "-b", "side")
    (work / "side.txt").write_text("side\n", encoding="utf-8")
    _git(work, "add", "side.txt")
    _git(work, "commit", "-m", "side commit")
    side_sha = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "origin", "side")
    _git(work, "checkout", "master")
    _git(work, "clone", str(origin), str(root / "src"))

    inputs_dir = root / "inputs"
    if inputs:
        inputs_dir.mkdir(parents=True)
        for name in ("processed_exercises.csv", "food_library.csv", "food_portions.csv"):
            (inputs_dir / name).write_text("fixture\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text(
        "#!/usr/bin/env bash\n"
        f"if [[ \"$*\" == *'?per_page=100'* ]]; then printf '%s' '{json.dumps({'check_runs': checks if checks is not None else [{'id': 1, 'name': 'Unit, Concurrency & Telemetry Tests', 'status': 'completed', 'conclusion': 'success'}, {'id': 2, 'name': 'Production Image Smoke Test', 'status': 'completed', 'conclusion': 'success'}]})}'; else printf 'ready'; fi\n",
        encoding="utf-8",
    )
    (bin_dir / "sudo").write_text("#!/usr/bin/env bash\nexec \"$@\"\n", encoding="utf-8")
    (bin_dir / "docker").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == compose ]]; then printf '%s\\n' \"$*\" >> \"$MAYOS_SERVER_ROOT/docker.log\"; exit 0; fi\n"
        "if [[ \"$1\" == ps ]]; then if [[ -s \"$MAYOS_SERVER_ROOT/app/deploy/.image.env\" ]]; then printf 'container\\n'; fi; exit 0; fi\n"
        "if [[ \"$1\" == inspect && \"$2\" == --format ]]; then tag=$(sed -n 's/^MAYOS_IMAGE_TAG=//p' \"$MAYOS_SERVER_ROOT/app/deploy/.image.env\"); printf 'mayos-api:%s\\n' \"$tag\"; exit 0; fi\n"
        "if [[ \"$1\" == image && \"$2\" == inspect ]]; then exit 1; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "df").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == -B1 ]]; then printf 'Avail\\n9000000000\\n'; else printf 'Filesystem Size Used Avail Use%% Mounted on\\ntest 10G 1G 9G 10%% /\\n'; fi\n",
        encoding="utf-8",
    )
    for executable in bin_dir.iterdir():
        executable.chmod(0o755)
    return root, master_sha, side_sha, origin, bin_dir


def _run_pull(tmp_path, root, bin_dir, commit):
    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
        "MAYOS_SERVER_ROOT": _bash_path(root),
        "MAYOS_PUBLIC_REPO_URL": _bash_path(tmp_path / "origin"),
        "MAYOS_REQUIRED_CHECKS": "Unit, Concurrency & Telemetry Tests|Production Image Smoke Test",
    })
    return subprocess.run(["bash", str(SCRIPT), "pull", commit], text=True, capture_output=True, env=env, check=False)


def test_pull_deploy_refuses_unknown_commit_end_to_end(tmp_path):
    root, _, _, _, bin_dir = _pull_fixture(tmp_path)
    result = _run_pull(tmp_path, root, bin_dir, "0" * 40)
    assert result.returncode != 0
    assert "Deployment refused: unknown commit" in result.stdout


def test_pull_deploy_refuses_commit_outside_master_end_to_end(tmp_path):
    root, _, side_sha, _, bin_dir = _pull_fixture(tmp_path)
    result = _run_pull(tmp_path, root, bin_dir, side_sha)
    assert result.returncode != 0
    assert "not reachable from origin/master" in result.stdout


def test_pull_deploy_refuses_latest_failed_check_end_to_end(tmp_path):
    checks = [
        {"id": 10, "name": "Unit, Concurrency & Telemetry Tests", "status": "completed", "conclusion": "success"},
        {"id": 11, "name": "Unit, Concurrency & Telemetry Tests", "status": "completed", "conclusion": "failure"},
        {"id": 12, "name": "Production Image Smoke Test", "status": "completed", "conclusion": "success"},
    ]
    root, master_sha, _, _, bin_dir = _pull_fixture(tmp_path, checks=checks)
    result = _run_pull(tmp_path, root, bin_dir, master_sha)
    assert result.returncode != 0
    assert "required check 'Unit, Concurrency & Telemetry Tests'" in result.stdout


def test_pull_deploy_refuses_missing_server_input_end_to_end(tmp_path):
    root, master_sha, _, _, bin_dir = _pull_fixture(tmp_path, inputs=False)
    result = _run_pull(tmp_path, root, bin_dir, master_sha)
    assert result.returncode != 0
    assert "required server input missing" in result.stdout


def test_pull_deploy_refuses_unexpected_untracked_checkout_file(tmp_path):
    root, master_sha, _, _, bin_dir = _pull_fixture(tmp_path)
    (root / "src" / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    result = _run_pull(tmp_path, root, bin_dir, master_sha)
    assert result.returncode != 0
    assert "checkout is dirty or does not match verified commit" in result.stdout


def test_pull_deploy_refuses_when_deploy_lock_is_held(tmp_path):
    root, master_sha, _, _, bin_dir = _pull_fixture(tmp_path)
    state = root / "state"
    state.mkdir()
    lock_file = state / "deploy.lock"
    holder = subprocess.Popen(["bash", "-c", 'flock "$1" sleep 30', "test", _bash_path(lock_file)])
    try:
        result = _run_pull(tmp_path, root, bin_dir, master_sha)
    finally:
        holder.terminate()
        holder.wait(timeout=5)
    assert result.returncode != 0
    assert "another deployment is running" in result.stdout


def test_pull_deploy_uses_shared_image_env_and_status_reads_deployed_tag(tmp_path):
    root, master_sha, _, _, bin_dir = _pull_fixture(tmp_path)
    result = _run_pull(tmp_path, root, bin_dir, master_sha)
    assert result.returncode == 0, result.stdout + result.stderr
    image_env = root / "app" / "deploy" / ".image.env"
    tag_line = image_env.read_text(encoding="utf-8").strip()
    assert tag_line.startswith("MAYOS_IMAGE_TAG=")
    compose_calls = (root / "docker.log").read_text(encoding="utf-8")
    assert f"--env-file {_bash_path(image_env)}" in compose_calls
    assert "/src/deploy/compose.server.yaml" in compose_calls

    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}", "MAYOS_SERVER_ROOT": _bash_path(root)})
    status = subprocess.run(
        ["bash", "-c", 'source "$1"; server_pull_mode=1; ssh_target=; current_tag="$(running_tag)"; printf "Current API image: %s\\n" "$current_tag"', "test", str(SCRIPT)],
        text=True, capture_output=True, env=env, check=False,
    )
    assert status.returncode == 0, status.stderr
    assert f"Current API image: {tag_line.split('=', 1)[1]}" in status.stdout
