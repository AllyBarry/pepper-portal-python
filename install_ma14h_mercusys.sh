#!/usr/bin/env bash

set -e

# ============================================================
# Mercusys MA14H AX300 Linux Driver Installer
#
# Driver:
#   MA14H(EU)_V1_251010_Linux_Beta
#
# Temporary build location:
#   /tmp/mercusys-ma14h
#
# Important:
# - The Mercusys download contains nested ZIP archives.
# - The vendor Makefile does not reliably handle spaces or
#   parentheses in build paths.
# - Compilation is done as the normal user.
# - Installation/module loading uses sudo.
# ============================================================


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

DRIVER_URL='https://static.mercusys.com/software/MA14H(EU)_V1_251010_Linux_Beta20251013080432.zip'

WORK_DIR="/tmp/mercusys-ma14h"
ZIP_FILE="$WORK_DIR/ma14h-driver.zip"

KERNEL_VERSION="$(uname -r)"
ARCH="$(uname -m)"
KERNEL_BUILD="/lib/modules/$KERNEL_VERSION/build"


echo "============================================================"
echo " Mercusys MA14H AX300 Linux Driver Installer"
echo "============================================================"
echo
echo "[INFO] Kernel:       $KERNEL_VERSION"
echo "[INFO] Architecture: $ARCH"
echo "[INFO] Working dir:  $WORK_DIR"
echo


# ============================================================
# 1. Install dependencies
# ============================================================

echo "[INFO] Installing dependencies..."

sudo apt update

sudo apt install -y \
    build-essential \
    "linux-headers-$KERNEL_VERSION" \
    wget \
    unzip \
    usb-modeswitch \
    iw \
    wireless-tools

echo
echo "[OK] Dependencies installed."
echo


# ============================================================
# 2. Verify kernel headers
# ============================================================

echo "[INFO] Checking kernel build directory..."

if [ ! -e "$KERNEL_BUILD" ]; then
    echo "[ERROR] Kernel build directory not found:"
    echo "        $KERNEL_BUILD"
    exit 1
fi

echo "[OK] Kernel build directory:"
echo "     $KERNEL_BUILD"
echo


# ============================================================
# 3. Prepare /tmp directory
# ============================================================

echo "[INFO] Preparing build directory..."

sudo rm -rf "$WORK_DIR"

mkdir -p "$WORK_DIR"

echo "[OK] Build directory:"
echo "     $WORK_DIR"
echo


# ============================================================
# 4. Download driver
# ============================================================

echo "[INFO] Downloading MA14H Beta driver..."

wget \
    -O "$ZIP_FILE" \
    "$DRIVER_URL"

echo
echo "[OK] Downloaded:"
echo "     $ZIP_FILE"
echo


# ============================================================
# 5. Extract outer ZIP
# ============================================================

echo "[INFO] Extracting outer archive..."

unzip -q "$ZIP_FILE" -d "$WORK_DIR"

echo "[OK] Outer archive extracted."
echo


# ============================================================
# 6. Recursively extract nested ZIP files
#
# The MA14H Beta package contains another archive:
#
#   ma14h-driver.zip
#       |
#       +-- aic8800_linux_drvier.zip
#
# Do not depend on that exact filename. Extract any nested
# ZIPs that appear.
# ============================================================

echo "[INFO] Searching for nested ZIP archives..."

while true; do

    NESTED_ZIP="$(find "$WORK_DIR" \
        -type f \
        -iname '*.zip' \
        ! -path "$ZIP_FILE" \
        | head -n 1)"

    if [ -z "$NESTED_ZIP" ]; then
        break
    fi

    echo
    echo "[INFO] Found nested archive:"
    echo "       $NESTED_ZIP"

    # Put contents into a directory named after the ZIP.
    NESTED_DIR="${NESTED_ZIP%.*}"

    echo "[INFO] Extracting into:"
    echo "       $NESTED_DIR"

    mkdir -p "$NESTED_DIR"

    unzip -q "$NESTED_ZIP" -d "$NESTED_DIR"

    # Delete the nested archive after extraction so this loop
    # does not discover the same ZIP again.
    rm -f "$NESTED_ZIP"

done

echo
echo "[OK] All nested ZIP archives extracted."
echo


# ============================================================
# 7. Show extracted structure
# ============================================================

echo "============================================================"
echo " EXTRACTED DIRECTORY STRUCTURE"
echo "============================================================"
echo

find "$WORK_DIR" -maxdepth 6 -type d

echo


# ============================================================
# 8. Locate install_setup.sh
#
# Do not hard-code Mercusys directory names.
# ============================================================

echo "[INFO] Searching for install_setup.sh..."

INSTALL_SCRIPT="$(find "$WORK_DIR" \
    -type f \
    -name 'install_setup.sh' \
    | head -n 1)"

if [ -z "$INSTALL_SCRIPT" ]; then

    echo
    echo "[ERROR] install_setup.sh not found."
    echo
    echo "[INFO] Extracted files:"
    find "$WORK_DIR" -maxdepth 8 -type f

    exit 1

fi

echo "[OK] Found installer:"
echo "     $INSTALL_SCRIPT"
echo

DRIVER_ROOT="$(dirname "$INSTALL_SCRIPT")"

echo "[INFO] Driver root:"
echo "       $DRIVER_ROOT"
echo


# ============================================================
# 9. Fix ownership
#
# We encountered a previous failure where make could not create:
#
#   aic_load_fw.mod: Permission denied
#
# Make sure the source tree belongs to the current user.
# ============================================================

echo "[INFO] Ensuring build tree is writable..."

sudo chown -R "$USER":"$(id -gn)" "$WORK_DIR"

echo "[OK] Build tree ownership corrected."
echo


# ============================================================
# 10. Run Mercusys setup script
# ============================================================

echo "============================================================"
echo " MERCUSYS SETUP"
echo "============================================================"
echo

cd "$DRIVER_ROOT"

chmod +x install_setup.sh

sudo ./install_setup.sh

echo
echo "[OK] Mercusys setup completed."
echo


# ============================================================
# 11. Restore ownership after Mercusys setup
#
# install_setup.sh runs as root and may create root-owned files.
# Fix ownership again before make.
# ============================================================

echo "[INFO] Restoring build-tree ownership..."

sudo chown -R "$USER":"$(id -gn)" "$WORK_DIR"

echo "[OK] Build tree is writable."
echo


# ============================================================
# 12. Locate AIC8800 source
#
# With the current Beta package this resolves to something like:
#
# /tmp/mercusys-ma14h/
#   aic8800_linux_drvier/
#     drivers/
#       aic8800/
#
# But we discover it instead of hard-coding it.
# ============================================================

echo "[INFO] Searching for AIC8800 source..."

AIC_DIR="$(find "$DRIVER_ROOT" \
    -type d \
    -name 'aic8800' \
    | head -n 1)"

if [ -z "$AIC_DIR" ]; then

    # Fallback: search entire extracted tree.
    AIC_DIR="$(find "$WORK_DIR" \
        -type d \
        -name 'aic8800' \
        | head -n 1)"

fi


if [ -z "$AIC_DIR" ]; then

    echo
    echo "[ERROR] Could not locate aic8800 source directory."
    echo
    echo "[INFO] Available directories:"

    find "$WORK_DIR" -maxdepth 8 -type d

    exit 1

fi


echo "[OK] AIC8800 source:"
echo "     $AIC_DIR"
echo


# ============================================================
# 13. Clean
# ============================================================

cd "$AIC_DIR"

echo "[INFO] Cleaning previous build..."

make clean || true

echo


# ============================================================
# 14. Build
#
# IMPORTANT:
# Do NOT use sudo here.
# ============================================================

echo "============================================================"
echo " BUILDING AIC8800 DRIVER"
echo "============================================================"
echo

echo "[INFO] Kernel:"
echo "       $KERNEL_VERSION"
echo

echo "[INFO] Source:"
echo "       $AIC_DIR"
echo

make -j"$(nproc)"

echo
echo "[OK] Driver compiled successfully."
echo


# ============================================================
# 15. Find resulting kernel modules
# ============================================================

echo "============================================================"
echo " COMPILED MODULES"
echo "============================================================"
echo

find "$AIC_DIR" -type f -name '*.ko' -print

echo


LOAD_FW="$(find "$AIC_DIR" \
    -type f \
    -name 'aic_load_fw.ko' \
    | head -n 1)"

FDRV="$(find "$AIC_DIR" \
    -type f \
    -name 'aic8800_fdrv.ko' \
    | head -n 1)"


if [ -z "$LOAD_FW" ]; then
    echo "[ERROR] aic_load_fw.ko was not produced."
    exit 1
fi


if [ -z "$FDRV" ]; then
    echo "[ERROR] aic8800_fdrv.ko was not produced."
    exit 1
fi


echo "[OK] Required modules:"
echo
echo "     $LOAD_FW"
echo "     $FDRV"
echo


# ============================================================
# 16. Install kernel modules
#
# Root is required because this writes to /lib/modules.
# ============================================================

echo "============================================================"
echo " INSTALLING MODULES"
echo "============================================================"
echo

sudo make install

sudo depmod -a

echo
echo "[OK] Modules installed."
echo


# ============================================================
# 17. Verify module installation
# ============================================================

echo "============================================================"
echo " MODULE INFORMATION"
echo "============================================================"
echo

echo "[INFO] aic_load_fw:"
modinfo aic_load_fw | head -20 || true

echo
echo "[INFO] aic8800_fdrv:"
modinfo aic8800_fdrv | head -20 || true

echo


# ============================================================
# 18. Remove previously loaded AIC modules
# ============================================================

echo "[INFO] Removing old loaded copies if necessary..."

if lsmod | grep -q '^aic8800_fdrv'; then
    sudo modprobe -r aic8800_fdrv || true
fi

if lsmod | grep -q '^aic_load_fw'; then
    sudo modprobe -r aic_load_fw || true
fi

echo


# ============================================================
# 19. Check for MA14H mass-storage mode
#
# Previously observed:
#
#   a69c:5721
#   Product: Aic MSC
#
# If present, eject it so it re-enumerates as AIC8800DC.
# ============================================================

echo "============================================================"
echo " USB MODE"
echo "============================================================"
echo

lsusb

echo


if lsusb | grep -qi 'a69c:5721'; then

    echo "[INFO] MA14H is in mass-storage mode."
    echo "[INFO] Switching it to Wi-Fi mode..."

    sudo usb_modeswitch \
        -v 0xa69c \
        -p 0x5721 \
        -K

    echo "[INFO] Waiting for USB re-enumeration..."

    sleep 5

    echo
    echo "[INFO] USB devices after mode switch:"
    lsusb

else

    echo "[INFO] a69c:5721 mass-storage mode not detected."
    echo "[INFO] No manual USB mode switch required."

fi

echo


# ============================================================
# 20. Load wireless infrastructure
# ============================================================

echo "[INFO] Loading cfg80211..."

sudo modprobe cfg80211

echo "[OK] cfg80211 loaded."
echo


# ============================================================
# 21. Load AIC firmware loader
# ============================================================

echo "[INFO] Loading aic_load_fw..."

sudo modprobe aic_load_fw

echo "[OK] aic_load_fw loaded."
echo


# ============================================================
# 22. Load AIC Wi-Fi driver
# ============================================================

echo "[INFO] Loading aic8800_fdrv..."

sudo modprobe aic8800_fdrv

echo "[OK] aic8800_fdrv loaded."
echo


# ============================================================
# 23. Wait for interface creation
# ============================================================

echo "[INFO] Waiting for network interface creation..."

sleep 3

echo


# ============================================================
# 24. Diagnostics
# ============================================================

echo "============================================================"
echo " USB DEVICES"
echo "============================================================"
echo

lsusb


echo
echo "============================================================"
echo " LOADED AIC MODULES"
echo "============================================================"
echo

lsmod | grep -i aic || \
    echo "No AIC modules shown."


echo
echo "============================================================"
echo " WIRELESS DEVICES"
echo "============================================================"
echo

iw dev || true


echo
echo "============================================================"
echo " NETWORK INTERFACES"
echo "============================================================"
echo

ip link


echo
echo "============================================================"
echo " NETWORKMANAGER"
echo "============================================================"
echo

nmcli device status || true


echo
echo "============================================================"
echo " AIC KERNEL MESSAGES"
echo "============================================================"
echo

sudo dmesg | \
    grep -i -E 'aic|8800|firmware' | \
    tail -150 || true


echo
echo "============================================================"
echo " DONE"
echo "============================================================"
echo

echo "Check WIRELESS DEVICES above for the MA14H."
echo
echo "Your built-in Intel Wi-Fi is likely wlo1."
echo "The MA14H should appear as another wireless interface."
