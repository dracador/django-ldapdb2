FROM ubuntu:24.04

RUN apt update && apt install -y slapd slapd-contrib ldap-utils openssl

# Self-signed cert for StartTLS / LDAPS — test-only, regenerated per build.
RUN mkdir -p /etc/ldap/tls \
    && openssl req -new -x509 -nodes -days 3650 \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
        -keyout /etc/ldap/tls/server.key \
        -out /etc/ldap/tls/server.crt \
    && chmod 600 /etc/ldap/tls/server.key \
    && chown -R openldap:openldap /etc/ldap/tls

COPY ./slapd.conf /etc/ldap/slapd.conf
COPY ./init-ldap.sh /init-ldap.sh
RUN chmod +x /init-ldap.sh

EXPOSE 389 636
