$ErrorActionPreference = "Stop"

# ============================
# CONFIG
# ============================
$APP_NAME = "plotune_simple_reader"
$TARGET   = "x86_64-pc-windows-msvc"
$DIST_DIR = "dist/windows"
$DATA_DIR = "data"

# ============================
# CLEAN
# ============================
Write-Host "Cleaning previous build..."
Remove-Item -Recurse -Force $DIST_DIR -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $DIST_DIR | Out-Null

# ============================
# BUILD
# ============================
Write-Host "Building release for Windows..."
cargo build --release --target $TARGET

$BIN_SRC = "target/$TARGET/release/$APP_NAME.exe"
if (!(Test-Path $BIN_SRC)) {
    throw "Executable not found: $BIN_SRC"
}

# ============================
# STAGE FILES
# ============================
Copy-Item $BIN_SRC "$DIST_DIR/$APP_NAME.exe"
Copy-Item "plugin.json" $DIST_DIR
Copy-Item $DATA_DIR "$DIST_DIR/data" -Recurse

# ============================
# ARCHIVE
# ============================
$ZIP_NAME = "$APP_NAME-windows-x64.zip"
$ZIP_PATH = "dist/$ZIP_NAME"

Write-Host "Creating ZIP: $ZIP_NAME"
Compress-Archive -Path "$DIST_DIR/*" -DestinationPath $ZIP_PATH -Force

# ============================
# SHA256
# ============================
Write-Host "Generating SHA256..."
$HASH = Get-FileHash $ZIP_PATH -Algorithm SHA256
$HASH.Hash | Out-File "$ZIP_PATH.sha256"

Write-Host "Windows build completed successfully."
