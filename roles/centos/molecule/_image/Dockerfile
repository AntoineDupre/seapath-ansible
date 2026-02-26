FROM quay.io/centos/centos:stream9

ENV container=docker
STOPSIGNAL SIGRTMIN+3

# Paquets nécessaires pour Ansible + systemd + ton rôle
RUN dnf -y update && \
    dnf -y install \
      systemd systemd-udev \
      sudo \
      python3 python3-libselinux \
      iproute procps-ng \
      vim-minimal \
      dnf-plugins-core \
      ca-certificates openssl \
    && dnf clean all

# Optionnel: EPEL + syslog-ng (utile pour ton scénario logging)
# Si tu ne veux pas syslog-ng dans l'image, commente ce bloc et installe-le en prepare scenario.
RUN dnf -y install epel-release || true && \
    dnf -y makecache && \
    dnf -y install syslog-ng || true && \
    dnf clean all || true

# Assure un init présent, quelle que soit l'image
RUN ln -sf /usr/lib/systemd/systemd /sbin/init && \
    ln -sf /usr/lib/systemd/systemd /usr/sbin/init

# "Allège" systemd pour container (évite des erreurs/bruit), tout en gardant journald
RUN (cd /lib/systemd/system/sysinit.target.wants/; \
      for i in *; do \
        [ "$i" = "systemd-tmpfiles-setup.service" ] || rm -f "$i"; \
      done) && \
    rm -f /lib/systemd/system/multi-user.target.wants/* && \
    rm -f /etc/systemd/system/*.wants/* && \
    rm -f /lib/systemd/system/local-fs.target.wants/* && \
    rm -f /lib/systemd/system/sockets.target.wants/*udev* && \
    rm -f /lib/systemd/system/sockets.target.wants/*initctl* || true

VOLUME ["/sys/fs/cgroup"]
CMD ["/sbin/init"]
