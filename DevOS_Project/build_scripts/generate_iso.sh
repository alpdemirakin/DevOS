#!/bin/bash
set -e

# DevOS ISO Generator (GUI Mode) - REPOFIX 2
# Simplification to fix package resolution errors

BUILD_DIR="/build/work"
ISO_OUTPUT="/build/output/devos.iso"
ROOTFS="$BUILD_DIR/rootfs"
ISO_ROOT="$BUILD_DIR/iso"

echo "Starting DevOS Build (GUI + RepoFix 2)..."

# 0. Clean
if [ -d "$BUILD_DIR" ]; then rm -rf "$BUILD_DIR"; fi
mkdir -p "$BUILD_DIR"
mkdir -p "$ROOTFS"
mkdir -p "$ISO_ROOT/boot/grub"
mkdir -p "$(dirname "$ISO_OUTPUT")"

# 1. Install Alpine Base + GUI + Tools
echo "Installing OS components..."

# Use latest stable repos
REPO_MAIN="https://dl-cdn.alpinelinux.org/alpine/latest-stable/main"
REPO_COMM="https://dl-cdn.alpinelinux.org/alpine/latest-stable/community"

mkdir -p "$ROOTFS/etc/apk"
if [ -d /etc/apk/keys ]; then cp -r /etc/apk/keys "$ROOTFS/etc/apk/"; fi

echo "$REPO_MAIN" > "$ROOTFS/etc/apk/repositories"
echo "$REPO_COMM" >> "$ROOTFS/etc/apk/repositories"

# Install packages
# Removed: py3-tkinter (not strictly needed for basic bot)
# Added: xf86-input-libinput AND evdev
apk --root "$ROOTFS" --initdb --update-cache --allow-untrusted add \
    alpine-base \
    linux-virt \
    python3 \
    py3-pip \
    py3-pillow \
    git \
    bash \
    openrc \
    util-linux \
    xorg-server \
    xf86-video-vesa \
    xf86-input-libinput \
    xf86-input-evdev \
    virtualbox-guest-additions \
    udev \
    xinit \
    fluxbox \
    firefox \
    xdotool \
    scrot \
    ttf-dejavu \
    nodejs \
    npm \
    rxvt-unicode

# 2. Inject DevOS AI Core & Configs
echo "Injecting AI Brain..."
mkdir -p /build/ai /build/projects /build/system
cp -r /build/ai "$ROOTFS/"
cp -r /build/projects "$ROOTFS/"
cp -r /build/system "$ROOTFS/"
mkdir -p "$ROOTFS/logs" "$ROOTFS/tmp" "$ROOTFS/root"

# 2b. Fix Windows CRLF line endings on all scripts
echo "Fixing line endings..."
find "$ROOTFS/ai" -type f -name "*.py" -exec sed -i 's/\r$//' {} +
find "$ROOTFS/ai" -type f -name "*.txt" -exec sed -i 's/\r$//' {} +
sed -i 's/\r$//' "$ROOTFS/system/init"

# 3. Configure Setup
echo "Configuring Init..."
cp "$ROOTFS/system/init" "$ROOTFS/init"
chmod +x "$ROOTFS/init"

# 4. Configure X11 (For root user)
echo "Configuring GUI..."
cat > "$ROOTFS/root/.xinitrc" <<EOF
#!/bin/sh
# Start Guest Additions (Try-catch style)
VBoxClient --clipboard || true
VBoxClient --draganddrop || true
VBoxClient --checkhostversion || true
VBoxClient --seamless || true

xsetroot -solid "#1a1a1a"
fluxbox &
urxvt -fn "xft:DejaVu Sans Mono:pixelsize=14" -geometry 100x30 -bg black -fg green -e python3 -u /ai/core/main.py
EOF
chmod +x "$ROOTFS/root/.xinitrc"
mkdir -p "$ROOTFS/root/.fluxbox"
touch "$ROOTFS/root/.fluxbox/init"

# 5. Extract Kernel & Modules
echo "Extracting Kernel..."
KERNEL_SRC=$(find "$ROOTFS/boot" -name "vmlinuz-virt" | head -n 1)
MOD_DIR=$(find "$ROOTFS/lib/modules" -maxdepth 1 -name "6.*" | head -n 1)

if [ -z "$KERNEL_SRC" ]; then echo "Kernel not found!"; exit 1; fi
cp "$KERNEL_SRC" "$ISO_ROOT/boot/vmlinuz"

# Update modules map
if [ -n "$MOD_DIR" ]; then
    depmod -b "$ROOTFS" $(basename "$MOD_DIR")
fi

# 6. Pack RootFS into RAM Disk
echo "Packing RootFS..."
# Helper to create static dev nodes if possible (Docker limitation workaround)
mkdir -p "$ROOTFS/dev"
# Try mknod, ignore failure if unprivileged
mknod -m 600 "$ROOTFS/dev/console" c 5 1 2>/dev/null || true
mknod -m 666 "$ROOTFS/dev/null" c 1 3 2>/dev/null || true
mknod -m 666 "$ROOTFS/dev/zero" c 1 5 2>/dev/null || true

cd "$ROOTFS"
find . -path ./boot -prune -o -print | cpio -o -H newc | gzip > "$ISO_ROOT/boot/initramfs.gz"
cd "$BUILD_DIR"

# 7. Configure GRUB
echo "Configuring Bootloader..."
cat > "$ISO_ROOT/boot/grub/grub.cfg" <<EOF
set default=0
set timeout=5

menuentry "DevOS GUI" {
    linux /boot/vmlinuz console=tty0 quiet init=/init
    initrd /boot/initramfs.gz
}
EOF

# 8. Generate ISO
echo "Burning ISO..."
if [ -x "$(command -v grub-mkrescue)" ]; then
    grub-mkrescue -o "$ISO_OUTPUT" "$ISO_ROOT"
else
    xorriso -as mkisofs \
        -r -J --joliet-long \
        -l -iso-level 3 \
        -o "$ISO_OUTPUT" \
        -b boot/grub/i386-pc/eltorito.img \
        -no-emul-boot -boot-load-size 4 -boot-info-table \
        "$ISO_ROOT"
fi

echo "Build Complete: $ISO_OUTPUT"
ls -lh "$ISO_OUTPUT"
