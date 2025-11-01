#!/bin/bash

# Clean up the data directory
# rm -rf /var/lib/ldap/*

mkdir -p /var/run/slapd

# Apply the base LDIF file using slapadd
/opt/symas/sbin/slapadd -f /etc/ldap/slapd-symas.conf -l /ldifs/base.ldif

# Start the LDAP server
exec /opt/symas/lib/slapd -d 256 -f /etc/ldap/slapd-symas.conf