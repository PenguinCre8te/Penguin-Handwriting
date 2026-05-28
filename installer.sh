#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

# Ensure the installer script itself is run as root to handle system paths
if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run this installer with sudo." >&2
  exit 1
fi

# Identify the actual user who invoked sudo
if [ -n "$SUDO_USER" ]; then
  REAL_USER="$SUDO_USER"
else
  echo "Error: Could not detect the non-root user. Please run with 'sudo ./install.sh'" >&2
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
  echo "Warning: apt-get not found. Verifying Python dependencies via pip/modules..."
  
  # Check and try to install evdev
  if ! python3 -c "import evdev" &> /dev/null; then
    if command -v pip3 &> /dev/null; then
      echo "  -> evdev not found. Trying to install via pip..."
      pip3 install evdev --break-system-packages || true
    else
      echo "Error: evdev is missing and pip3 is not installed." >&2
      exit 1
    fi
  fi

  # Check Tkinter availability
  if ! python3 -c "import tkinter" &> /dev/null; then
    echo "Error: Tkinter is not installed or available to Python. Please install your distribution's python3-tk package." >&2
    exit 1
  fi
fi

# Configure input group permissions for the user
echo "Configuring input group permissions..."
# Ensure the 'input' group exists (standard on most modern Linux distros)
if ! getent group input > /dev/null; then
  groupadd input
fi

# Add the real user to the input group so they can access the touchpad device
echo "  -> Adding user '$REAL_USER' to the 'input' group..."
usermod -aG input "$REAL_USER"

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

# 3. Create execution wrapper (No longer requires xauth/root tricks!)
TARGET_BIN="$BIN_DIR/$BINARY_NAME"
cat << 'EOF' > "$TARGET_BIN"
#!/usr/bin/env bash

# Run the raw Python script as the current user
exec python3 "/usr/local/bin/.penguinhandwriting-raw.py" "$@"
EOF

# Standardize binary targeting inside the execution wrapper
sed -i "s|\.penguinhandwriting-raw\.py|.$BINARY_NAME-raw.py|g" "$TARGET_BIN"
chmod 755 "$TARGET_BIN"
echo "  -> Executable wrapper installed to: $TARGET_BIN"

# 4. Generate Desktop Entry (Removed pkexec so it runs as the logged-in user)
DESKTOP_FILE="$APP_DIR/$BINARY_NAME.desktop"

cat << EOF > "$DESKTOP_FILE"
[Desktop Entry]
Type=Application
Version=1.0
Name=$APP_NAME
Comment=$COMMENT
Exec=$TARGET_BIN
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

echo "--------------------------------------------------------"
echo "Installation complete!"
echo "IMPORTANT: User '$REAL_USER' was added to the 'input' group."
echo "You MUST log out and log back in (or restart) for the group changes to take effect."
echo "--------------------------------------------------------"
