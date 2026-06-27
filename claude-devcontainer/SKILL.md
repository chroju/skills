---
name: claude-devcontainer
description: Generate a devcontainer.json optimized for Claude Code development (dotfiles, credential sharing via bind mounts, SSH agent forwarding)
---

# Claude Devcontainer

Generate a `.devcontainer/devcontainer.json` optimized for Claude Code development.

## Steps

1. Check if `.devcontainer/devcontainer.json` already exists. If so, ask the user whether to overwrite or skip.

2. Gather the following parameters from the user:
   - **Username**: OS username inside the container (used for home directory path and common-utils)
   - **Dotfiles repository**: GitHub repository for dotfiles (e.g., `user/dotfiles`). Optional — skip dotfiles setup if not provided.
   - **Dotfiles install command**: Script to run after cloning the dotfiles repository (default: `install.sh`). Ask only if dotfiles repository is provided. Optional — omit if using the default.
   - **SSH agent forwarding**: Whether to forward the host's SSH agent into the container (default: yes). If yes, also ask:
     - **SSH agent socket path**: Path to the SSH agent socket on the host (suggest the host's `$SSH_AUTH_SOCK` if set, otherwise `/tmp/ssh-agent.sock`)
   - **Include AWS mount**: Whether to bind-mount `~/.aws` into the container (default: no)
   - **initializeCommand**: A host-side command to run before container creation (e.g., a script that ensures credential files exist). Optional — omit if not needed.
   - **Timezone**: Container timezone (suggest the host's `$TZ` if set, otherwise `UTC`)
   - **postCreateCommand**: A command to run inside the container after creation (e.g., `gh auth setup-git` for git credential helper). Optional — omit if not needed.
   - **Include GPG mount**: Whether to bind-mount `~/.gnupg` into the container for GPG commit signing (default: no)
   - **Forward ports**: Ports to forward from the container to the host (e.g., `3000, 8080`). Optional — omit if not needed.

3. Resolve the latest patch version of each devcontainer feature before generating the file. For each feature in `ghcr.io/devcontainers/features/` and `ghcr.io/anthropics/devcontainer-features/`, query the GitHub Packages API to get the latest tag pinned to the patch level (e.g., `2.5.9` not `2` or `2.5`):
   ```
   gh api /orgs/<org>/packages/container/features%2F<feature-name>/versions --jq '.[0].metadata.container.tags | map(select(test("^[0-9]+\\.[0-9]+\\.[0-9]+$"))) | .[0]'
   ```
   Use the resolved versions in the generated JSON. Never use versions from this template without verifying they still exist.

4. Create `.devcontainer/devcontainer.json` using the template below, substituting parameters and resolved versions. Set `name` to the current repository or directory name.

5. Ask the user which additional devcontainer features are needed for the project (e.g., Node.js, Python, Go, Terraform, AWS CLI). Look up the latest version for each and add them to the `features` section.

6. Create `.devcontainer/.env.devcontainer` as an empty file if it doesn't exist (required by `--env-file` in runArgs).

7. Create `.devcontainer/.gitignore` with the following content if it doesn't exist:
   ```
   .env.devcontainer
   .env.devcontainer.local
   ```

8. Verify the generated configuration by running `devcontainer up --workspace-folder . [--dotfiles-repository <dotfiles-repo>] [--dotfiles-install-command <command>]` (include these flags only if the user provided them) and confirm the container starts successfully. If it fails, diagnose the error (missing files for bind mounts, invalid feature versions, etc.), fix the generated `devcontainer.json`, and retry. Once verified, stop and remove the container.

## Template

```json
{
  "name": "<project-name>",
  "image": "ubuntu:24.04",
  "features": {
    "ghcr.io/devcontainers/features/common-utils:<latest>": {
      "configureZshAsDefaultShell": true,
      "username": "<username>"
    },
    "ghcr.io/devcontainers/features/git:<latest>": {},
    "ghcr.io/devcontainers/features/github-cli:<latest>": {},
    "ghcr.io/anthropics/devcontainer-features/claude-code:<latest>": {}
  },
  "mounts": [
    "source=${localEnv:HOME}/.ssh,target=/home/<username>/.ssh,type=bind,readonly",
    "source=${localEnv:HOME}/.claude/projects,target=/home/<username>/.claude/projects,type=bind",
    "source=${localEnv:HOME}/.claude/sessions,target=/home/<username>/.claude/sessions,type=bind",
    "source=${localEnv:HOME}/.claude/.credentials-devcontainer.json,target=/home/<username>/.claude/.credentials.json,type=bind",
    "source=${localEnv:HOME}/.claude/settings.json,target=/home/<username>/.claude/settings.json,type=bind,readonly",
    "source=${localEnv:HOME}/.claude/history.jsonl,target=/home/<username>/.claude/history.jsonl,type=bind",
    "source=${localEnv:HOME}/.claude.devcontainer.json,target=/home/<username>/.claude.json,type=bind"
  ],
  "containerEnv": {
    "TZ": "<timezone>"
  },
  "remoteEnv": {
    "TERM": "xterm-256color",
    "COLORTERM": "truecolor"
  },
  "runArgs": ["--env-file", ".devcontainer/.env.devcontainer", "--security-opt", "label=disable"],
  "init": true,
  "remoteUser": "<username>"
}
```

### Conditional sections

**If initializeCommand is provided**, add:
```json
{
  "initializeCommand": "<command>"
}
```

**If postCreateCommand is provided**, add:
```json
{
  "postCreateCommand": "<command>"
}
```

**If SSH agent forwarding is enabled**, add to `mounts`:
```json
"source=<ssh-agent-socket>,target=/home/<username>/.ssh-agent.sock,type=bind,relabel=shared"
```

**If AWS mount is included**, add to `mounts`:
```json
"source=${localEnv:HOME}/.aws,target=/home/<username>/.aws,type=bind"
```

**If GPG mount is included**, add to `mounts`:
```json
"source=${localEnv:HOME}/.gnupg,target=/home/<username>/.gnupg,type=bind"
```

**If forward ports are provided**, add:
```json
{
  "forwardPorts": [3000, 8080]
}
```

## Prerequisites

- Dev Containers CLI (`devcontainer` command) or a compatible runtime (VS Code Dev Containers extension, GitHub Codespaces, etc.) must be installed on the host.
- Claude Code must be installed on the host (`~/.claude/` directory exists).

## Notes

- When a dotfiles repository is provided, pass it as `--dotfiles-repository <repo>` to `devcontainer up`. The devcontainer runtime clones the repository and runs `install.sh` by default. To use a different script, also pass `--dotfiles-install-command <command>`.
- `initializeCommand` runs on the host before container creation. Typical uses: ensuring bind-mount target files exist, refreshing credentials, or pulling secrets.
- The Claude Code credentials mount expects `~/.claude/.credentials-devcontainer.json` on the host. This is a separate credential file to avoid conflicts with the host's active session.
- The `--security-opt label=disable` run arg is required for Podman and SELinux environments to allow bind mounts. It is harmless on Docker Desktop, so it is included unconditionally.
