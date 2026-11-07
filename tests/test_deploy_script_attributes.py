import subprocess


def test_deploy_shell_scripts_are_executable_and_have_lf_attributes(git_checkout):
    repo_root = git_checkout
    result = subprocess.run(
        ["git", "ls-files", "-s", "--", "deploy/*.sh"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    scripts = []
    mode_failures = []
    for line in result.stdout.splitlines():
        mode, _, _, path = line.split(maxsplit=3)
        scripts.append(path)
        if mode != "100755":
            mode_failures.append(f"{path}: mode {mode}")

    assert scripts, "No tracked deploy shell scripts found"
    assert not mode_failures, "Deploy scripts must be executable:\n" + "\n".join(mode_failures)

    attribute_failures = []
    for path in scripts:
        result = subprocess.run(
            ["git", "check-attr", "eol", "--", path],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() != f"{path}: eol: lf":
            attribute_failures.append(result.stdout.strip())

    assert not attribute_failures, "Deploy scripts must have eol=lf:\n" + "\n".join(attribute_failures)
