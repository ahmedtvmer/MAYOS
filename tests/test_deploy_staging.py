import os
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "deploy" / "deploy_server.sh"
STAGING = ROOT / "deploy" / "staging_server.bash"


def _run_bash(body, *arguments, env=None):
    return subprocess.run(
        ["bash", "-c", body, "test", *map(str, arguments)],
        text=True, capture_output=True, check=False, env=env,
    )


def _executable(path, body):
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def staging_server(tmp_path):
    """Use real files and shell code; replace Docker and wall time."""
    root = tmp_path / "mayos"
    state = root / "state" / "staging"
    state.mkdir(parents=True)
    data = tmp_path / "data" / "staging"
    data.mkdir(parents=True)
    (root / "staging.env").write_text("JWT_SECRET=staging-only\n", encoding="utf-8")
    worker = tmp_path / "staging_server.bash"
    # Map the remote filesystem boundary into the test's private directory.
    worker.write_text(
        STAGING.read_text(encoding="utf-8")
        .replace("/opt/mayos", root.as_posix())
        .replace("/mnt/mayos-data/staging", data.as_posix()),
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    _executable(bin_dir / "sudo", 'exec "$@"\n')
    _executable(bin_dir / "docker", r'''
printf '%s\n' "$*" >> "$DOCKER_LOG"
case "$1" in
  ps) if [[ "${HAS_CONTAINER:-0}" == 1 ]]; then printf 'staging-api\n'; fi ;;
  inspect)
    case "$3" in
      *State.Running*) printf '%s\n' "${RUNNING:-true}" ;;
      *State.StartedAt*) printf '2026-11-08T00:00:00Z\n' ;;
      *ttl-hours*) printf '%s\n' "${TTL_HOURS:-4}" ;;
      *staging.commit*) printf '%s\n' "${COMMIT:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}" ;;
      *) exit 2 ;;
    esac ;;
  compose)
    case " $* " in
      *' config --format json '*) printf '{"services":{"api":{"labels":{"online.mayos.staging.ttl-hours":"%s"}}}}\n' "${TTL_HOURS:-4}" ;;
      *' exec -T api '*) printf '{"ready":true}\n' ;;
    esac ;;
  image)
    if [[ "$2" == ls ]]; then printf '%s' "${IMAGE_LIST:-}"; fi ;;
  buildx|stop|rm) ;;
  *) exit 2 ;;
esac
''')
    _executable(bin_dir / "date", r'''
if [[ "$*" == '+%s' ]]; then printf '%s\n' "${NOW_EPOCH:-1794096000}"; exit; fi
exec /usr/bin/date "$@"
''')
    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}", "DOCKER_LOG": str(log)})
    return root, state, data, worker, log, env


@pytest.mark.parametrize("action", ["up", "down", "status"])
def test_staging_routes_without_accessing_production_state(tmp_path, action):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "ssh.log"
    upload = "/opt/mayos/state/staging/upload.abcdefgh"
    _executable(bin_dir / "git", r'''
case "$*" in
  *--show-toplevel*) printf '%s\n' "$CHECKOUT" ;;
  *status*) printf ' M dirty.txt\n' ;;
  *--short=12*) printf 'aaaaaaaaaaaa\n' ;;
  *'rev-parse HEAD'*) printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' ;;
  *) echo "unexpected git: $*" >&2; exit 2 ;;
esac
''')
    _executable(bin_dir / "ssh", r'''
payload="$(cat)"
printf '%s\n' "$*" "$payload" >> "$SSH_LOG"
[[ "$payload" != *compose.server.yaml* && "$payload" != *deploy-history.tsv* ]] || exit 2
case "$*" in
  *'-- prepare') printf '%s\n' "$UPLOAD" ;;
  *'-- status') printf 'Staging is off.\n' ;;
esac
''')
    _executable(bin_dir / "rsync", 'printf "rsync %s\\n" "$*" >> "$SSH_LOG"\n')
    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
        "CHECKOUT": str(tmp_path), "SSH_LOG": str(log), "UPLOAD": upload,
        "MAYOS_DEPLOY_HOST": "server.example",
    })
    result = subprocess.run(
        ["bash", str(SCRIPT), "staging", action],
        text=True, capture_output=True, check=False, env=env,
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8")
    assert f"-- {action}" in calls
    assert "/opt/mayos/.env" not in calls
    assert "/opt/mayos/app/" not in calls
    assert "deploy-history.tsv" not in calls
    if action == "up":
        assert "Warning: checkout has uncommitted changes" in result.stderr
        assert f"deploy@server.example:{upload}/" in calls
        assert "-- cleanup" in calls


@pytest.mark.parametrize("arguments", [[], ["restart"], ["up", "extra"]])
def test_staging_rejects_invalid_subcommands(arguments):
    result = subprocess.run(
        ["bash", str(SCRIPT), "staging", *arguments],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 2
    assert "staging up|down|status" in result.stderr


def test_staging_remote_executes_streamed_worker_without_production_preamble(staging_server):
    root, _, data, worker, log, env = staging_server
    _executable(worker.parent / "bin" / "ssh", r'''
shift
sed "s|/opt/mayos|$STAGING_ROOT|g; s|/mnt/mayos-data/staging|$STAGING_DATA|g" | bash -c "$*"
''')
    env.update({"STAGING_ROOT": str(root), "STAGING_DATA": str(data), "HAS_CONTAINER": "1"})
    result = _run_bash(
        'source "$1"; staging_mode=1; ssh_target=selftest; staging_remote status', SCRIPT, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("Staging running: true") == 1
    assert "Auto-stops: 2026-11-08T04:00:00Z" in result.stdout
    assert "compose.server.yaml" not in log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("head", "fetch_result", "allowed", "message"),
    [("b" * 40, 0, False, "HEAD must equal current origin/master"),
     ("a" * 40, 1, False, "could not fetch origin/master"),
     ("a" * 40, 0, True, "")],
)
def test_local_production_deploy_requires_fetched_master(tmp_path, head, fetch_result, allowed, message):
    _executable(tmp_path / "git", r'''
printf '%s\n' "$*" >> "$GIT_LOG"
case "$*" in
  *--show-toplevel*) printf '%s\n' "$CHECKOUT" ;;
  *--git-dir|*--git-common-dir) printf '%s/.git\n' "$CHECKOUT" ;;
  *fetch*) exit "$FETCH_RESULT" ;;
  *'--verify origin/master') printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' ;;
  *'rev-parse HEAD') printf '%s\n' "$HEAD_SHA" ;;
  *) exit 2 ;;
esac
''')
    env = os.environ.copy()
    env.update({
        "PATH": f"{tmp_path}{os.pathsep}{env.get('PATH', '')}",
        "HEAD_SHA": head, "FETCH_RESULT": str(fetch_result), "GIT_LOG": str(tmp_path / "git.log"),
        "CHECKOUT": str(tmp_path),
    })
    if allowed:
        result = _run_bash('source "$1"; repo_root=checkout; verify_local_deploy_commit', SCRIPT, env=env)
    else:
        # No deploy host is configured: refusal must happen before any SSH access.
        env.pop("MAYOS_DEPLOY_HOST", None)
        result = subprocess.run(["bash", str(SCRIPT), "deploy"], env=env, text=True, capture_output=True)
    assert (result.returncode == 0) is allowed
    assert message in result.stderr
    calls = (tmp_path / "git.log").read_text(encoding="utf-8").splitlines()
    fetch_index = next(index for index, call in enumerate(calls) if " fetch " in call)
    assert "fetch --force --no-tags origin +refs/heads/master:refs/remotes/origin/master" in calls[fetch_index]
    assert not any("rev-parse HEAD" in call for call in calls[:fetch_index])


@pytest.mark.parametrize("missing", ["settings", "data"])
def test_staging_up_refuses_missing_server_setup(staging_server, missing):
    root, _, data, worker, log, env = staging_server
    if missing == "settings":
        (root / "staging.env").unlink()
        expected = "staging.env is missing"
    else:
        data.rmdir()
        expected = "create the staging data folder first"
    result = subprocess.run(["bash", str(worker), "prepare"], env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert expected in result.stderr
    assert not log.exists()


@pytest.mark.parametrize(
    ("age_seconds", "ttl", "running", "has_container", "stopped"),
    [(14399, "4", "true", "1", False),
     (14400, "4", "true", "1", True),
     (14401, "4", "true", "1", True),
     (7200, "2", "true", "1", True),
     (14401, "4", "false", "1", False),
     (14401, "4", "true", "0", False)],
)
def test_autostop_obeys_container_age_and_configured_ttl(
    staging_server, age_seconds, ttl, running, has_container, stopped,
):
    _, _, _, worker, log, env = staging_server
    env.update({
        "NOW_EPOCH": str(1794096000 + age_seconds), "TTL_HOURS": ttl,
        "RUNNING": running, "HAS_CONTAINER": has_container,
    })
    result = subprocess.run(["bash", str(worker), "autostop"], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8")
    assert ("stop --time 60 staging-api" in calls) is stopped
    assert ("rm staging-api" in calls) is stopped
    assert "com.docker.compose.project=mayos-staging" in calls
    assert "com.docker.compose.project=mayos " not in calls


@pytest.mark.parametrize("ttl", ["0", "-1", "abc", "1.5"])
def test_autostop_rejects_invalid_ttl_without_stopping(staging_server, ttl):
    _, _, _, worker, log, env = staging_server
    env.update({"TTL_HOURS": ttl, "HAS_CONTAINER": "1"})
    result = subprocess.run(["bash", str(worker), "autostop"], env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert "positive whole number" in result.stderr
    assert "stop --time" not in log.read_text(encoding="utf-8")


def test_staging_status_reports_commit_start_and_expiry(staging_server):
    _, _, _, worker, _, env = staging_server
    env["HAS_CONTAINER"] = "1"
    result = subprocess.run(["bash", str(worker), "status"], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert "Staging running: true" in result.stdout
    assert f"Commit: {'a' * 40}" in result.stdout
    assert "Started: 2026-11-08T00:00:00Z" in result.stdout
    assert "Auto-stops: 2026-11-08T04:00:00Z" in result.stdout


def test_staging_down_removes_only_its_container(staging_server):
    root, state, _, worker, log, env = staging_server
    production_history = root / "state" / "deploy-history.tsv"
    production_history.write_text("production rollback state\n", encoding="utf-8")
    production_env = root / "app" / "deploy" / ".image.env"
    production_env.parent.mkdir(parents=True)
    production_env.write_text("MAYOS_IMAGE_TAG=production\n", encoding="utf-8")
    env["HAS_CONTAINER"] = "1"
    result = subprocess.run(["bash", str(worker), "down"], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert log.read_text(encoding="utf-8").splitlines() == [
        "ps -aq --filter label=com.docker.compose.project=mayos-staging --filter label=com.docker.compose.service=api",
        "stop --time 60 staging-api", "rm staging-api",
    ]
    assert production_history.read_text(encoding="utf-8") == "production rollback state\n"
    assert production_env.read_text(encoding="utf-8") == "MAYOS_IMAGE_TAG=production\n"
    assert (state / "deploy.lock").exists()
    assert not (root / "state" / "deploy.lock").exists()


def test_staging_refuses_concurrent_operation_without_touching_docker(staging_server):
    _, state, _, worker, log, env = staging_server
    result = _run_bash(
        # fd 8 and a non-final command keep this shell holding the lock while the worker runs.
        'exec 8>"$2/deploy.lock"; flock -n 8; bash "$1" down; status=$?; exit "$status"',
        worker, state, env=env,
    )
    assert result.returncode != 0
    assert "another staging operation is running" in result.stderr
    assert not log.exists()


def test_staging_up_bounds_build_checks_ready_and_keeps_two_images(staging_server):
    root, state, _, worker, log, env = staging_server
    production_files = [root / "state" / "deploy-history.tsv", root / "app" / "deploy" / ".image.env"]
    for path in production_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("production state\n", encoding="utf-8")
    upload = state / "upload.abcdefgh"
    (upload / "deploy").mkdir(parents=True)
    (upload / "deploy" / "compose.staging.yaml").write_text("services: {}\n", encoding="utf-8")
    (upload / "Dockerfile.fly").write_text("FROM scratch\n", encoding="utf-8")
    (upload / "data").mkdir()
    for name in ("processed_exercises.csv", "food_library.csv", "food_portions.csv"):
        (upload / "data" / name).write_bytes(b"synthetic checkout fixture\n")
    previous_tag = "bbbbbbbbbbbb-20261107120000-1"
    old_tag = "cccccccccccc-20261106120000-1"
    tag = "aaaaaaaaaaaa-20261108120000-1"
    (state / "history.tsv").write_text(f"{'b' * 40}\t{previous_tag}\n{'c' * 40}\t{old_tag}\n", encoding="utf-8")
    env["HAS_CONTAINER"] = "1"
    env["IMAGE_LIST"] = "\n".join(f"mayos-api-staging:{image}" for image in (tag, previous_tag, old_tag)) + "\nmayos-api:production\n"
    result = subprocess.run(
        ["bash", str(worker), "up", str(upload), tag, "a" * 40], env=env, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8")
    assert "--driver-opt memory=1536m,memory-swap=1536m" in calls
    assert "buildx rm mayos-staging-builder" in calls
    assert "--force-recreate api" in calls
    assert "http://localhost:8000/readyz" in calls
    assert f"image rm mayos-api-staging:{old_tag}" in calls
    assert f"image rm mayos-api-staging:{previous_tag}" not in calls
    assert "image rm mayos-api:production" not in calls
    assert (state / "history.tsv").read_text(encoding="utf-8").splitlines() == [
        f"{'a' * 40}\t{tag}", f"{'b' * 40}\t{previous_tag}",
    ]
    assert "/opt/mayos/.env" not in calls
    assert "compose.server.yaml" not in calls
    assert "builder prune" not in calls
    assert all(path.read_text(encoding="utf-8") == "production state\n" for path in production_files)
    assert not (root / "state" / "deploy.lock").exists()


@pytest.mark.parametrize("name", ["processed_exercises.csv", "food_library.csv", "food_portions.csv"])
@pytest.mark.parametrize("availability", ["server-only", "checkout", "missing"])
def test_staging_up_fills_missing_protected_inputs_and_refuses_unavailable_input(staging_server, name, availability):
    root, state, _, worker, log, env = staging_server
    upload = state / "upload.abcdefgh"
    (upload / "data").mkdir(parents=True)
    (upload / "deploy").mkdir()
    (upload / "deploy" / "compose.staging.yaml").write_text("services: {}\n", encoding="utf-8")
    (upload / "Dockerfile.fly").write_text("FROM scratch\n", encoding="utf-8")
    for filename in ("processed_exercises.csv", "food_library.csv", "food_portions.csv"):
        if filename != name or availability == "checkout":
            (upload / "data" / filename).write_bytes(b"synthetic checkout fixture\n")
    inputs = root / "inputs"
    inputs.mkdir()
    if availability != "missing":
        (inputs / name).write_bytes(b"synthetic server fixture\n")
        (inputs / name).chmod(0o600)
    result = subprocess.run(
        ["bash", str(worker), "up", str(upload), "aaaaaaaaaaaa-20261108120000-1", "a" * 40],
        env=env, text=True, capture_output=True, check=False,
    )
    if availability == "missing":
        assert result.returncode != 0
        assert f"required build input {name} is missing" in result.stderr
        assert str(inputs / name) in result.stderr
        assert not log.exists()
    else:
        assert result.returncode == 0, result.stderr
        expected = b"synthetic server fixture\n" if availability == "server-only" else b"synthetic checkout fixture\n"
        destination = state / "app" / "data" / name
        assert destination.read_bytes() == expected
        if availability == "server-only":
            assert destination.stat().st_mode & 0o777 == 0o644
        assert (inputs / name).read_bytes() == b"synthetic server fixture\n"
        assert "buildx build" in log.read_text(encoding="utf-8")
    assert "synthetic checkout fixture" not in result.stdout + result.stderr
    assert "synthetic server fixture" not in result.stdout + result.stderr


def test_staging_compose_isolates_data_secrets_and_runtime_settings():
    staging_path = ROOT / "deploy" / "compose.staging.yaml"
    staging = yaml.safe_load(staging_path.read_text(encoding="utf-8"))
    production = yaml.safe_load((ROOT / "deploy" / "compose.server.yaml").read_text(encoding="utf-8"))
    assert staging["name"] == "mayos-staging"
    assert set(staging["services"]) == {"api"}
    api = staging["services"]["api"]
    assert api["env_file"] == ["/opt/mayos/staging.env"]
    assert "/opt/mayos/.env" not in staging_path.read_text(encoding="utf-8")
    assert api["environment"] == {
        "JWT_SECRET": "${JWT_SECRET:?set JWT_SECRET in /opt/mayos/staging.env}",
        "ANONYMOUS_ID_SECRET": "${ANONYMOUS_ID_SECRET:?set ANONYMOUS_ID_SECRET in /opt/mayos/staging.env}",
        "MAYOS_ENV": "staging", "SENTRY_ENVIRONMENT": "staging", "MAYOS_LITESTREAM": "false",
        "DISCORD_ALERT_WEBHOOK_URL": "", "SMTP_HOST": "", "MAYOS_DATA_DIR": "/data",
        "MAYOS_REQUIRE_PERSISTENT_DATA": "true", "MAYOS_CLIENT_IP_HEADER": "cf-connecting-ip",
        "RESET_LINK_BASE_URL": "https://${MAYOS_STAGING_HOSTNAME:?set MAYOS_STAGING_HOSTNAME in /opt/mayos/staging.env}",
    }
    assert api["volumes"] == [{
        "type": "bind", "source": "/mnt/mayos-data/staging", "target": "/data",
        "bind": {"create_host_path": False},
    }]
    production_mounts = {
        mount["source"] for service in production["services"].values()
        for mount in service.get("volumes", []) if isinstance(mount, dict)
    }
    assert not production_mounts.intersection(mount["source"] for mount in api["volumes"])
    assert api["networks"]["production"]["aliases"] == ["api-staging"]
    assert staging["networks"]["production"] == {"external": True, "name": "mayos_default"}
    assert api["mem_limit"] == "1536m"
    assert api["restart"] == "no"
    assert api["healthcheck"] == production["services"]["api"]["healthcheck"]
    assert api["command"] == production["services"]["api"]["command"]
    assert api["build"]["dockerfile"] == "Dockerfile.fly"
    assert api["image"].startswith("mayos-api-staging:")


def test_staging_autostop_units_are_installed_alongside_queue_units():
    unit_root = ROOT / "deploy" / "systemd"
    timer = (unit_root / "mayos-staging-autostop.timer").read_text(encoding="utf-8")
    service = (unit_root / "mayos-staging-autostop.service").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "OnUnitActiveSec=15min" in timer
    assert "User=deploy" in service
    assert "ExecStart=/bin/bash /usr/local/libexec/mayos/staging_server.bash autostop" in service
    for name in ("mayos-staging-autostop.timer", "mayos-staging-autostop.service"):
        assert f"deploy/systemd/{name} /etc/systemd/system/" in docs
    assert "deploy/staging_server.bash /usr/local/libexec/mayos/staging_server.bash" in docs
    assert "systemctl enable --now mayos-staging-autostop.timer" in docs
