#!/usr/bin/env bash
# install_infra_runner.sh — install N repo-scoped GitHub Actions runners (label jta-infra) on the TRAINER VM.
#
# Row GH-CAPACITY-INFRA-RUNNER (operator popup 2026-11-03 ~10:07Z: "Self-hosted runner (Recommended)").
# Run as root on ict-trainer-vm ONLY (refuses on any host whose hostname does not contain "trainer").
# Called by .github/workflows/infra-runner-install.yml; the registration token arrives on STDIN (never argv/env/log).
#
# Security (public repo):
#   * one dedicated unprivileged user per instance (ghr1..ghrN): no sudo, no docker group, not in group ubuntu;
#     /home/ubuntu is chmod 750 so runner users cannot read the trainer's repo, DBs or keys.
#   * a job-completed hook wipes the user's ~/.ssh ~/.config/gh ~/.kaggle ~/.netrc and the job workspace, so a
#     key a workflow writes (VM_SSH_KEY, KAGGLE token) does not outlive its job.
#   * which workflows may target the label is enforced in CI by tests/test_self_hosted_runner_guard.py
#     (no pull_request / pull_request_target workflow may reference it).
#
# Idempotent: an instance already configured is left alone (its service is (re)enabled and started).
set -euo pipefail

COUNT="${1:-4}"
REPO_URL="${2:?usage: install_infra_runner.sh <count> <https://github.com/owner/repo>}"
LABELS="${3:-jta-infra}"
BASE=/opt/actions-runner

case "$(hostname)" in *trainer*) ;; *) echo "REFUSED: hostname $(hostname) is not the trainer VM"; exit 3;; esac
[ "$(id -u)" = 0 ] || { echo "REFUSED: must run as root"; exit 3; }
IFS= read -r REG_TOKEN || true
[ -n "${REG_TOKEN:-}" ] || { echo "REFUSED: no registration token on stdin"; exit 3; }

case "$(uname -m)" in aarch64|arm64) ARCH=arm64;; x86_64) ARCH=x64;; *) echo "unsupported arch $(uname -m)"; exit 3;; esac

export DEBIAN_FRONTEND=noninteractive
need=()
for p in git curl jq unzip openssh-client python3 python3-venv python3-pip python3-yaml python3-requests ca-certificates openssl sqlite3 zstd rsync; do
  dpkg -s "$p" >/dev/null 2>&1 || need+=("$p")
done
if ! command -v gh >/dev/null; then
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli-archive-keyring.gpg
  chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list
  need+=(gh)
fi
if [ "${#need[@]}" -gt 0 ]; then apt-get update -qq && apt-get install -y -qq "${need[@]}" >/dev/null; fi
echo "deps_ok gh=$(gh --version | head -1)"

# Runner users must not read the trainer's own tree.
chmod 750 /home/ubuntu

VER="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name | sed 's/^v//')"
[ -n "$VER" ] && [ "$VER" != null ] || { echo "could not resolve runner version"; exit 4; }
TARBALL="/var/cache/actions-runner-${VER}-${ARCH}.tar.gz"
[ -s "$TARBALL" ] || curl -fsSL -o "$TARBALL" \
  "https://github.com/actions/runner/releases/download/v${VER}/actions-runner-linux-${ARCH}-${VER}.tar.gz"
echo "runner_version=$VER arch=$ARCH"

# Job-completed hook: wipe credentials a job may have written.
cat > /usr/local/bin/jta-runner-job-cleanup <<'HOOK'
#!/usr/bin/env bash
# ACTIONS_RUNNER_HOOK_JOB_COMPLETED for the jta-infra runners (install_infra_runner.sh).
rm -rf "$HOME/.ssh" "$HOME/.config/gh" "$HOME/.kaggle" "$HOME/.netrc" "$HOME/.git-credentials" 2>/dev/null || true
[ -n "${GITHUB_WORKSPACE:-}" ] && find "$GITHUB_WORKSPACE" -mindepth 1 -delete 2>/dev/null || true
find /tmp -maxdepth 1 -user "$(id -u)" -mmin +0 -exec rm -rf {} + 2>/dev/null || true
exit 0
HOOK
chmod 755 /usr/local/bin/jta-runner-job-cleanup

for i in $(seq 1 "$COUNT"); do
  U="ghr$i"; D="$BASE/$U"; NAME="trainer-jta-infra-$i"
  id "$U" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$U"
  gpasswd -d "$U" sudo >/dev/null 2>&1 || true
  gpasswd -d "$U" docker >/dev/null 2>&1 || true
  install -d -o "$U" -g "$U" -m 0750 "$D"
  if [ ! -f "$D/.runner" ]; then
    sudo -u "$U" tar -xzf "$TARBALL" -C "$D"
    sudo -u "$U" bash -c "cd '$D' && ./config.sh --unattended --replace --url '$REPO_URL' --token \"\$(cat)\" \
        --name '$NAME' --labels '$LABELS' --work _work --disableupdate=false" <<<"$REG_TOKEN" >/dev/null
    echo "configured $NAME"
  else
    echo "already_configured $NAME"
  fi
  grep -q ACTIONS_RUNNER_HOOK_JOB_COMPLETED "$D/.env" 2>/dev/null || \
    echo "ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/usr/local/bin/jta-runner-job-cleanup" >> "$D/.env"
  chown "$U:$U" "$D/.env"
  systemctl list-unit-files --no-legend 'actions.runner.*' | grep -qF "${NAME}.service" || ( cd "$D" && ./svc.sh install "$U" >/dev/null )
  # Per-service private /tmp: the moved workflows write fixed /tmp/<name> paths, so two concurrent jobs on two
  # instances would collide on a shared /tmp. NoNewPrivileges: a job can never escalate (sudo/setuid).
  UNIT="$(systemctl list-unit-files --no-legend 'actions.runner.*' | awk '{print $1}' | grep -F "${NAME}.service" | head -1)"
  if [ -n "$UNIT" ]; then
    install -d "/etc/systemd/system/${UNIT}.d"
    printf '[Service]\nPrivateTmp=true\nNoNewPrivileges=true\n' > "/etc/systemd/system/${UNIT}.d/jta-hardening.conf"
    systemctl daemon-reload
    systemctl restart "$UNIT" || true
  else
    echo "WARN: no systemd unit found for $NAME"
  fi
done
unset REG_TOKEN
systemctl list-units --all 'actions.runner*' --no-legend | awk '{print "unit", $1, $3, $4}'
echo "INSTALL_DONE count=$COUNT labels=$LABELS"
