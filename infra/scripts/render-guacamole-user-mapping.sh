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
vnc_color_depth="${GUACAMOLE_VNC_COLOR_DEPTH:-16}"
vnc_compress_level="${GUACAMOLE_VNC_COMPRESS_LEVEL:-6}"
vnc_quality_level="${GUACAMOLE_VNC_QUALITY_LEVEL:-5}"
vnc_disable_display_resize="${GUACAMOLE_VNC_DISABLE_DISPLAY_RESIZE:-false}"
vnc_enable_audio="${GUACAMOLE_VNC_ENABLE_AUDIO:-false}"
vnc_encodings="${GUACAMOLE_VNC_ENCODINGS:-}"

escaped_vnc_color_depth="$(xml_escape "$vnc_color_depth")"
escaped_vnc_compress_level="$(xml_escape "$vnc_compress_level")"
escaped_vnc_quality_level="$(xml_escape "$vnc_quality_level")"
escaped_vnc_disable_display_resize="$(xml_escape "$vnc_disable_display_resize")"
escaped_vnc_enable_audio="$(xml_escape "$vnc_enable_audio")"

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

cat >> "$output_dir/user-mapping.xml" <<EOF
      <param name="cursor">remote</param>
      <param name="color-depth">$escaped_vnc_color_depth</param>
      <param name="compress-level">$escaped_vnc_compress_level</param>
      <param name="quality-level">$escaped_vnc_quality_level</param>
      <param name="disable-display-resize">$escaped_vnc_disable_display_resize</param>
      <param name="enable-audio">$escaped_vnc_enable_audio</param>
EOF

if [ -n "$vnc_encodings" ]; then
  escaped_vnc_encodings="$(xml_escape "$vnc_encodings")"
  cat >> "$output_dir/user-mapping.xml" <<EOF
      <param name="encodings">$escaped_vnc_encodings</param>
EOF
fi

cat >> "$output_dir/user-mapping.xml" <<'EOF'
    </connection>
  </authorize>
</user-mapping>
EOF