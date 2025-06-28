#!/bin/bash

# Clean up the data directory
# rm -rf /var/lib/ldap/*

# Apply the base LDIF file using slapadd
slapadd -f /etc/ldap/slapd.conf -l /ldifs/base.ldif

if [ ! -f /var/lib/ldap/DB_CONFIG ]; then
    echo "Initializing LDAP data"

    # Load base LDIF
    slapadd -f /etc/ldap/slapd.conf -l /ldifs/base.ldif

    # Apply generated data
    if [[ -f /ldifs/generated_data.ldif ]]; then
        echo "Applying generated_data.ldif..."
        slapadd -f /etc/ldap/slapd.conf -l /ldifs/generated_data.ldif
    fi

    # Fix permissions
    chown -R openldap:openldap /var/lib/ldap
else
    echo "LDAP data directory already initialized, skipping import"
fi

# Fix permissions
chown -R openldap:openldap /var/lib/ldap

# Start the LDAP server
slapd -d 256 -f /etc/ldap/slapd.conf -u openldap -g openldap