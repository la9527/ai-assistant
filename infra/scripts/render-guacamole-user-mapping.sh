#!/bin/sh

set -eu

output_dir="${1:-/config}"
mkdir -p "$output_dir"

xml_escape() {
  printf '%s' "$1" | sed \
    -e 's/&/\&amp;/g' \
    -e 's/"/\&quot;/g' \
    -e "s/'/\&apos;/g" \
    -e 's/</\&lt;/g' \
    -e 's/>/\&gt;/g'
}

username="$(xml_escape "${GUACAMOLE_USERNAME:-operator}")"
raw_password="${GUACAMOLE_PASSWORD:-}"
if [ -z "$raw_password" ]; then
  echo "GUACAMOLE_PASSWORD must be set. The default Guacamole XML authentication cannot accept an arbitrary password entered at login and pass it through without first authenticating that same password." >&2
  exit 1
fi
password="$(xml_escape "$raw_password")"
connection_name="$(xml_escape "${GUACAMOLE_CONNECTION_NAME:-Mac Mini Desktop}")"
vnc_host="$(xml_escape "${GUACAMOLE_VNC_HOST:-host.docker.internal}")"
vnc_port="$(xml_escape "${GUACAMOLE_VNC_PORT:-5900}")"
vnc_username="${GUACAMOLE_VNC_USERNAME:-}"
vnc_use_login_password="${GUACAMOLE_VNC_USE_LOGIN_PASSWORD:-false}"
vnc_password="${GUACAMOLE_VNC_PASSWORD:-}"

cat > "$output_dir/user-mapping.xml" <<EOF
<user-mapping>
  <authorize username="$username" password="$password">
    <connection name="$connection_name">
      <protocol>vnc</protocol>
      <param name="hostname">$vnc_host</param>
      <param name="port">$vnc_port</param>
EOF

if [ -n "$vnc_username" ]; then
  escaped_vnc_username="$(xml_escape "$vnc_username")"
  cat >> "$output_dir/user-mapping.xml" <<EOF
      <param name="username">$escaped_vnc_username</param>
EOF
fi

if [ "$vnc_use_login_password" = "true" ] || [ "$vnc_use_login_password" = "1" ]; then
  cat >> "$output_dir/user-mapping.xml" <<'EOF'
      <param name="password">${GUAC_PASSWORD}</param>
EOF
elif [ -n "$vnc_password" ]; then
  escaped_vnc_password="$(xml_escape "$vnc_password")"
  cat >> "$output_dir/user-mapping.xml" <<EOF
      <param name="password">$escaped_vnc_password</param>
EOF
fi

cat >> "$output_dir/user-mapping.xml" <<'EOF'
      <param name="cursor">remote</param>
      <param name="color-depth">16</param>
    </connection>
  </authorize>
</user-mapping>
EOF