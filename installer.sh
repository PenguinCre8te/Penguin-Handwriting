#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

# Ensure the script is run as root
if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run this installer with sudo." >&2
  exit 1
fi

# --- CONFIGURATION ---
GIT_REPO_URL="https://github.com/PenguinCre8te/Penguin-Handwriting.git"
SCRIPT_NAME="main.py"
BINARY_NAME="penguinhandwriting"
REPO_ICON_PATH="images/icon.jpg"

APP_NAME="Penguin Handwriting"
COMMENT="A handwriting input designed to utilise the touchpad."
CATEGORIES="Utility;"

# System-wide installation paths
BIN_DIR="/usr/local/bin"
APP_DIR="/usr/share/applications"
ICON_DIR="/usr/share/icons/hicolor/scalable/apps"
# ---------------------

# Create a secure temporary directory for cloning
WORK_DIR=$(mktemp -d -t git-install-XXXXXX)

echo "Checking and installing system dependencies..."
if command -v apt-get &> /dev/null; then
  echo "  -> Installing python3-evdev and python3-tk via apt..."
  apt-get update -yq
  apt-get install -yq python3-evdev python3-tk
else
  echo "Warning: apt-get not found. Trying to install evdev with pip."
  if command -v pip3 &> /dev/null; then
    pip3 install evdev --break-system-packages || true
  fi
fi

# Set up cleanup trap for temporary directory
cleanup() {
  echo "Cleaning up temporary workspace..."
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

echo "Cloning repository into temporary workspace..."
git clone --depth 1 "$GIT_REPO_URL" "$WORK_DIR/repo"

cd "$WORK_DIR/repo"

# Verify script exists before deployment
if [ ! -f "$SCRIPT_NAME" ]; then
  echo "Error: Script '$SCRIPT_NAME' not found in the root of the repository." >&2
  exit 1
fi

# Evaluate icon availability
if [ ! -f "$REPO_ICON_PATH" ]; then
  echo "Warning: Icon not found at '$REPO_ICON_PATH'. Falling back to default system icon."
  SYSTEM_ICON_TARGET="utilities-terminal"
else
  SYSTEM_ICON_TARGET="$BINARY_NAME"
fi

echo "Installing $APP_NAME system-wide..."

# 1. Install custom icon if available
if [ "$SYSTEM_ICON_TARGET" = "$BINARY_NAME" ]; then
  mkdir -p "$ICON_DIR"
  cp "$REPO_ICON_PATH" "$ICON_DIR/$BINARY_NAME.jpg"
  echo "  -> Icon installed to: $ICON_DIR/$BINARY_NAME.jpg"
fi

# 2. Install the raw python source file securely
INTERNAL_BIN="$BIN_DIR/.$BINARY_NAME-raw.py"
cp "$SCRIPT_NAME" "$INTERNAL_BIN"
chmod 755 "$INTERNAL_BIN"

# 3. Create execution wrapper to pass X11/Wayland authorization tokens to root
TARGET_BIN="$BIN_DIR/$BINARY_NAME"
cat << 'EOF' > "$TARGET_BIN"
#!/usr/bin/env bash
# Merge the user's .Xauthority details so root can render the Tkinter GUI
if [ -n "$XAUTHORITY" ]; then
    xauth merge "$XAUTHORITY"
elif [ -f "$HOME/.Xauthority" ]; then
    xauth merge "$HOME/.Xauthority"
fi

# Fallback environment variables for display access
export DISPLAY="${DISPLAY:-:0}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"

# Run the raw Python script
exec python3 "/usr/local/bin/.penguinhandwriting-raw.py" "$@"
EOF

# Standardize binary targeting inside the execution wrapper
sed -i "s|\.penguinhandwriting-raw\.py|.$BINARY_NAME-raw.py|g" "$TARGET_BIN"
chmod 755 "$TARGET_BIN"
echo "  -> Executable wrapper installed to: $TARGET_BIN"

# 4. Generate Desktop Entry with functional X11 tunnel variables
DESKTOP_FILE="$APP_DIR/$BINARY_NAME.desktop"

cat << EOF > "$DESKTOP_FILE"
[Desktop Entry]
Type=Application
Version=1.0
Name=$APP_NAME
Comment=$COMMENT
Exec=pkexec env DISPLAY=$DISPLAY XAUTHORITY=$XAUTHORITY $TARGET_BIN
Icon=$SYSTEM_ICON_TARGET
Terminal=false
Categories=$CATEGORIES
EOF

chmod 644 "$DESKTOP_FILE"
echo "  -> Desktop entry created at: $DESKTOP_FILE"

echo "Updating system desktop and icon databases..."
if command -v gtk-update-icon-cache &> /dev/null; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
fi
if command -v update-desktop-database &> /dev/null; then
  update-desktop-database /usr/share/applications || true
fi

echo "Installation complete!"