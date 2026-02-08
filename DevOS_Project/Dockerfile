
FROM alpine:latest

# Setup repositories
RUN echo "https://dl-cdn.alpinelinux.org/alpine/latest-stable/main" > /etc/apk/repositories && \
    echo "https://dl-cdn.alpinelinux.org/alpine/latest-stable/community" >> /etc/apk/repositories

# Install build tools only (these are for the builder container, not the ISO)
RUN apk update && apk add --no-cache \
    xorriso \
    grub-bios \
    libisoburn \
    mtools \
    python3 \
    squashfs-tools \
    build-base \
    bash \
    tree \
    openrc \
    alpine-conf \
    cpio \
    findutils

WORKDIR /build

COPY . /build

RUN chmod +x /build/build_scripts/generate_iso.sh

CMD ["/build/build_scripts/generate_iso.sh"]
