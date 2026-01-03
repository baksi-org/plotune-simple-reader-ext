#!/usr/bin/env bash
set -euo pipefail

# ============================
# CONFIG
# ============================
APP_NAME="plotune_simple_reader"
TARGET="x86_64-unknown-linux-gnu"
DIST_DIR="dist/linux"
DATA_DIR="data"

# ============================
# CLEAN
# ============================
echo "Cleaning previous build..."
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

# ============================
# BUILD
# ============================
echo "Building release for Linux..."
cargo build --release --target "$TARGET"

BIN_SRC="target/$TARGET/release/$APP_NAME"
if [[ ! -f "$BIN_SRC" ]]; then
    echo "Executable not found: $BIN_SRC"
    exit 1
fi

# ============================
# STAGE FILES
# ============================
cp "$BIN_SRC" "$DIST_DIR/$APP_NAME"
chmod +x "$DIST_DIR/$APP_NAME"

cp plugin.json "$DIST_DIR/"
cp -r "$DATA_DIR" "$DIST_DIR/data"

# ============================
# ARCHIVE
# ============================
TAR_NAME="$APP_NAME-linux-x64.tar.gz"
TAR_PATH="dist/$TAR_NAME"

echo "Creating TAR.GZ: $TAR_NAME"
tar -C "$DIST_DIR" -czf "$TAR_PATH" .

# ============================
# SHA256
# ============================
echo "Generating SHA256..."
sha256sum "$TAR_PATH" | awk '{print $1}' > "$TAR_PATH.sha256"

echo "Linux build completed successfully."
