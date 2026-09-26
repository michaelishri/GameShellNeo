#!/bin/bash
# Loaded by the locked Armbian framework. /project is the wrapper's fixed mount.

function extension_prepare_config__gameshellneo() {
    DEBIAN_MIRROR="snapshot.debian.org/archive/debian/${NEO_DEBIAN_SNAPSHOT}"
    DEBIAN_SECURITY="snapshot.debian.org/archive/debian-security/${NEO_SECURITY_SNAPSHOT}"
    add_packages_to_image systemd-resolved systemd-timesyncd openssh-server wpasupplicant \
        sudo python3 usbutils iproute2 iw evtest stress-ng
    remove_packages armbian-config armbian-zsh network-manager netplan.io fake-hwclock
    PACKAGE_LIST_RM="${PACKAGE_LIST_RM} armbian-zsh"
}

function custom_apt_repo__gameshellneo() {
    python3 /project/tools/image.py apt-sources "${SDCARD}"
}

function post_create_partitions__gameshellneo() {
    mkopts[fat]='-F 16'
    sfdisk --part-type "${SDCARD}.raw" 1 0e
    sfdisk --activate "${SDCARD}.raw" 1
}

function prepare_root_device__gameshellneo() {
    # Kernel partition nodes appear in sysfs; Docker has a separate /dev mount.
    local number node major minor
    for number in 1 2; do
        node="${LOOP##*/}p${number}"
        if [[ ! -b /dev/$node ]]; then
            IFS=: read -r major minor < "/sys/class/block/${node}/dev"
            mknod -m 0600 "/dev/${node}" b "$major" "$minor"
        fi
    done
}

function pre_umount_final_image__gameshellneo() {
    deploy_qemu_binary_to_chroot "${MOUNT}" gameshellneo-finalize
    python3 /project/tools/image.py finalize "${MOUNT}" --loop "${LOOP}"
    undeploy_qemu_binary_from_chroot "${MOUNT}" gameshellneo-finalize
}

function post_build_image__gameshellneo() {
    python3 /project/tools/image.py inject "${FINAL_IMAGE_FILE}"
}
