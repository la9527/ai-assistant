#!/usr/bin/env zsh

set -euo pipefail

tailscale serve reset
tailscale serve status