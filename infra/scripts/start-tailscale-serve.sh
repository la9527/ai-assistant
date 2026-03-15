#!/usr/bin/env zsh

set -euo pipefail

TARGET="${1:-80}"

tailscale serve --bg "$TARGET"
tailscale serve status