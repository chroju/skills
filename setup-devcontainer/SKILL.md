---
name: setup-devcontainer
description: Generate a devcontainer.json with personal dotfiles integration (SSH, AWS, Claude Code settings sharing via bind mounts, Podman SSH agent forwarding)
---

# Setup Devcontainer

Generate a `.devcontainer/devcontainer.json` for the current project.

## Steps

1. Check if `.devcontainer/devcontainer.json` already exists. If so, ask the user whether to overwrite or skip.

2. Create `.devcontainer/devcontainer.json` using the template below. Set `name` to the current repository or directory name.

3. Ask the user which additional devcontainer features are needed for the project (e.g., Node.js, Python, Go, Terraform, AWS CLI). Add them to the `features` section.

4. Create `.devcontainer/.gitignore` with the following content if it doesn't exist:
   ```
   .env.devcontainer
   .env.devcontainer.local
   ```

## Template

```json
{
  "name": "<project-name>",
  "image": "ubuntu:24.04",
  "features": {
    "ghcr.io/devcontainers/features/common-utils:2.5.9": {
      "configureZshAsDefaultShell": true,
      "username": "chroju"
    },
    "ghcr.io/devcontainers/features/git:1.3.4": {},
    "ghcr.io/devcontainers/features/github-cli:1.1.0": {},
    "ghcr.io/anthropics/devcontainer-features/claude-code:1.0.5": {}
  },
  "dotfiles.repository": "chroju/dotfiles",
  "mounts": [
    "source=${localEnv:HOME}/.ssh,target=/home/chroju/.ssh,type=bind,readonly",
    "source=/tmp/ssh-agent.sock,target=/home/chroju/.ssh-agent.sock,type=bind,relabel=shared",
    "source=${localEnv:HOME}/.aws,target=/home/chroju/.aws,type=bind",
    "source=${localEnv:HOME}/.claude/projects,target=/home/chroju/.claude/projects,type=bind",
    "source=${localEnv:HOME}/.claude/sessions,target=/home/chroju/.claude/sessions,type=bind",
    "source=${localEnv:HOME}/.claude/.credentials-devcontainer.json,target=/home/chroju/.claude/.credentials.json,type=bind",
    "source=${localEnv:HOME}/.claude/settings.json,target=/home/chroju/.claude/settings.json,type=bind,readonly",
    "source=${localEnv:HOME}/.claude/history.jsonl,target=/home/chroju/.claude/history.jsonl,type=bind",
    "source=${localEnv:HOME}/.claude.devcontainer.json,target=/home/chroju/.claude.json,type=bind"
  ],
  "remoteEnv": {
    "TERM": "xterm-256color",
    "COLORTERM": "truecolor",
    "TZ": "Asia/Tokyo"
  },
  "initializeCommand": "devcontainer-init",
  "runArgs": ["--env-file", ".devcontainer/.env.devcontainer", "--security-opt", "label=disable"],
  "remoteUser": "chroju"
}
```

## Notes

- `devcontainer-init` must be available on the host at `/usr/local/bin/devcontainer-init` (installed via `chroju/dotfiles` `setup_symlinks.sh`).
- `dotfiles.repository` automatically clones `chroju/dotfiles` and runs `install.sh` inside the container, which creates symlinks and installs tools (Claude Code, mise).
- The AWS CLI feature is not included by default. Add `"ghcr.io/devcontainers/features/aws-cli:1.1.4": {}` if the project needs AWS access.
- If the project does not use Claude Code, remove the `claude-code` feature and all `~/.claude*` mounts.
