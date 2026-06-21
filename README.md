# setup-devcontainer

Claude Code skill to generate a devcontainer.json with personal dotfiles integration.

## Install

```bash
# GitHub CLI
gh skill install chroju/claude-devcontainer-skill setup-devcontainer

# npx
npx skills add chroju/claude-devcontainer-skill -a claude-code
```

## Usage

In a Claude Code session:

```
/setup-devcontainer
```

## What it does

Generates a `.devcontainer/devcontainer.json` with:

- Host credentials shared via bind mounts (SSH, AWS, Claude Code sessions/settings)
- Automatic dotfiles setup via `chroju/dotfiles` (symlinks, Claude Code, mise)
- Podman SSH agent forwarding for git commit signing
- Project-specific devcontainer features (Node.js, Python, Go, etc.)

## Prerequisites

`devcontainer-init` must be installed on the host at `/usr/local/bin/devcontainer-init`. Run `setup_symlinks.sh` from [chroju/dotfiles](https://github.com/chroju/dotfiles).
