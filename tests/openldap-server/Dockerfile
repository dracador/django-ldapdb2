FROM ubuntu:24.04

RUN apt update && apt install -y slapd slapd-contrib ldap-utils

COPY ./slapd.conf /etc/ldap/slapd.conf
COPY ./ldifs /ldifs
COPY ./schema /schema
COPY ./init-ldap.sh /init-ldap.sh
RUN chmod +x /init-ldap.sh

EXPOSE 389 636
