#!/bin/bash

# Clean up the data directory
# rm -rf /var/lib/ldap/*

# Apply the base LDIF file using slapadd
slapadd -f /etc/ldap/slapd.conf -l /ldifs/base.ldif

# Fix permissions
chown -R openldap:openldap /var/lib/ldap

# Start the LDAP server (LDAP on 389 + LDAPS on 636).
exec slapd -d 256 -f /etc/ldap/slapd.conf -u openldap -g openldap -h "ldap:/// ldaps:///"