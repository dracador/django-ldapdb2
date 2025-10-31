#!/usr/bin/env python3
"""
Proof-of-concept for LDAP RFC 5805 transactions using python-ldap.

Requirements:
  pip install python-ldap

Usage examples:
  python poc_ldap_txn.py --uri ldap://localhost:389 \
      --bind-dn "cn=admin,dc=example,dc=org" --bind-pw secret \
      --base-dn "ou=People,dc=example,dc=org"

  # Force abort to verify rollback:
  python poc_ldap_txn.py --abort

Notes:
- The script uses only python-ldap and tiny BER helpers (no pyasn1).
- It starts a txn, adds an entry, modifies it, then commits/aborts.
- After finishing, it searches to show whether the entry exists.
"""


import ldap
from ldap.controls import SimplePagedResultsControl
from ldap.extop import ExtendedRequest
from txn_ctrls import TxnStartRequest

# OIDs from RFC 5805
OID_TXN_START = '1.3.6.1.1.21.1'
OID_TXN_SPEC_CTRL = '1.3.6.1.1.21.2'
OID_TXN_END = '1.3.6.1.1.21.3'

connection = ldap.initialize(
    uri='ldap://localhost:389/',
)
connection.set_option(ldap.OPT_PROTOCOL_VERSION, 3)

# connection.simple_bind_s('uid=admin,ou=Users,dc=example,dc=org', 'adminpassword')
connection.simple_bind_s('uid=root,dc=example,dc=org', 'thisisapassword')

# root = connection.search_s("", ldap.SCOPE_BASE, "(objectClass=*)", ["supportedControl", "supportedExtension"])
# print("RootDSE:", root)


def search():
    result = connection.search_s('ou=Users,dc=example,dc=org', filterstr='(uid=*)', scope=ldap.SCOPE_ONELEVEL)
    return result


def start_txn():
    msg_id = connection.extop(TxnStartRequest())
    rtype, rdata, rmsgid, serverctrls, respoid, respvalue = connection.result4(msg_id, all=1, add_extop=1)
    print(f'{rtype=}, {rdata=}, {rmsgid=}, {serverctrls=}, {respoid=}, {respvalue=}')
    return respvalue


def start_txn2():
    msgid = connection.extop(ExtendedRequest(OID_TXN_START, None))
    # Get the LDAPResult dict with result code / msg
    resp_type, resp_data, resp_msgid, decoded_resp_ctrls, resp_name, resp_value = connection.result4(
        msgid, all=1, add_extop=1
    )
    print(f'{resp_type=}, {resp_data=}, {resp_msgid=}, {decoded_resp_ctrls=}, {resp_name=}, {resp_value=}')
    return


def start_txn3():
    msgid = connection.extop(ExtendedRequest(OID_TXN_START, None))

    # Get the result code/desc for this message id
    # NOTE: for extended ops, rdata is usually a dict from result3(); for some builds it can be empty.
    rtype3, rdata3, rmsgid3, sctrls3 = connection.result3(msgid, all=1)
    # If rdata3 is a dict, you'll have 'result' and 'desc'. If it's empty, ask OPT_RESULT_CODE.
    rc = None
    desc = None
    if isinstance(rdata3, dict) and 'result' in rdata3:
        rc = rdata3.get('result')
        desc = rdata3.get('desc')
    else:
        try:
            rc, matched, msg, refs = connection.get_option(ldap.OPT_RESULT_CODE)
            desc = msg
        except Exception:
            pass
    print(f'Start-TXN result: rc={rc} desc={desc!r}')

    # Now fetch the extop response value (the transaction id) via result4(add_extop=1)
    rtype4, rdata4, rmsgid4, sctrls4, respoid, respvalue = connection.result4(msgid, all=1, add_extop=1)
    print(f'result4 add_extop -> respoid={respoid}, respvalue={respvalue!r}')


def search_txn():
    result = connection.search_ext_s(
        'ou=Users,dc=example,dc=org',
        filterstr='(uid=*)',
        scope=ldap.SCOPE_ONELEVEL,
        serverctrls=[
            SimplePagedResultsControl(True, size=10, cookie=''),
        ],
    )
    return result


r = start_txn2()
print(r, dir(r))
