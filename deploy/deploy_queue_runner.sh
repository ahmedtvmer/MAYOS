#!/usr/bin/env bash
set -euo pipefail
umask 0027

queue_root="${MAYOS_DEPLOY_QUEUE_ROOT:-/opt/mayos/deploy-queue}"
requests_dir="${MAYOS_DEPLOY_REQUESTS_DIR:-$queue_root/requests}"
results_dir="${MAYOS_DEPLOY_RESULTS_DIR:-$queue_root/results}"
deploy_script="${MAYOS_DEPLOY_SCRIPT:-/opt/mayos/src/deploy/deploy_server.sh}"
work_dir="${MAYOS_DEPLOY_QUEUE_WORK_DIR:-${TMPDIR:-/tmp}}"

mkdir -p -- "$work_dir"
exec 9>"$work_dir/mayos-deploy-queue.lock"
flock 9

request=""
while IFS= read -r -d '' candidate; do
  request="$candidate"
  break
done < <(find "$requests_dir" -maxdepth 1 -type f -name '*.request' -print0 | sort -z)
[[ -n "$request" ]] || exit 0

base="${request##*/}"
filename_id="${base%.request}"
id=''
commit=''
reason=''
mapfile -t fields < "$request" || true
if [[ "$filename_id" =~ ^[A-Za-z0-9_-]{1,64}$ ]] && (( ${#fields[@]} == 2 )) && [[ "${fields[0]}" =~ ^[A-Za-z0-9_-]{1,64}$ ]] && [[ "${fields[0]}" == "$filename_id" ]]; then
  id="${fields[0]}"
  commit="${fields[1]}"
  if [[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]; then
    commit='unknown'
    reason='commit must be exactly 40 lowercase hexadecimal characters'
  fi
else
  id="$filename_id"
  [[ "$id" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || id='invalid'
  reason='request must contain exactly two lines: matching safe request id and lowercase 40-character commit SHA'
fi

result="$results_dir/$id.result"
tmp_result="$results_dir/.$id.result.$$"
tmp_output="$work_dir/mayos-deploy-output.$$"
finish_result() {
  local outcome="$1"
  {
    printf 'request_id: %s\n' "$id"
    printf 'commit: %s\n' "${commit:-unknown}"
    printf 'outcome: %s\n' "$outcome"
    printf 'output_tail:\n'
    if [[ -s "$tmp_output" ]]; then
      tail -n 20 -- "$tmp_output" | sed -E 's/((TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY)=)[^[:space:]]+/\1[redacted]/Ig; s/gh[pousr]_[A-Za-z0-9_]{20,}/[redacted]/g'
    else
      printf '(no deploy output)\n'
    fi
  } > "$tmp_result"
  chmod 0640 "$tmp_result"
  mv -f -- "$tmp_result" "$result"
  rm -f -- "$tmp_output" "$request" || true
  exit 0
}

: > "$tmp_output"
if [[ -n "$reason" ]]; then
  printf 'Request refused: %s\n' "$reason" > "$tmp_output"
  finish_result "refused: $reason"
fi

if [[ ! -f "$deploy_script" ]]; then
  reason="deploy script not found at $deploy_script"
  printf 'Request refused: %s\n' "$reason" > "$tmp_output"
  finish_result "refused: $reason"
fi

set +e
bash "$deploy_script" pull "$commit" > "$tmp_output" 2>&1
status=$?
set -e
if (( status == 0 )); then
  finish_result ready
fi
if grep -Fq 'Deployment result: rolled back' "$tmp_output"; then
  finish_result 'rolled back'
fi
why="$(sed -n 's/^Deployment refused: //p' "$tmp_output" | tail -n 1)"
[[ -n "$why" ]] || why="deploy command exited with status $status"
finish_result "refused: $why"
