from contextlib import contextmanager
from enum import Enum
from random import randint

import ldap
from django.db import connections
from ldap import modlist
from ldap.controls import RequestControl
from ldap.extop import ExtendedRequest, ExtendedResponse
from ldap.ldapobject import ReconnectLDAPObject, SimpleLDAPObject
from pyasn1.codec.ber import decoder as ber_decoder, encoder as ber_encoder

from .pyasn_rfc5805 import TxnEndReq, TxnEndRes

# From RFC 5805, section 3.1:
# Start and end transaction OIDs are found in supportedExtension.
# Specification Control is found in supportedControl.
# Please also see note about Transaction Specification Control in `features.py: supports_transactions`.
LDAP_OID_TRANSACTION_START = '1.3.6.1.1.21.1'
LDAP_OID_TRANSACTION_SPECIFICATION_CONTROL = '1.3.6.1.1.21.2'
LDAP_OID_TRANSACTION_END = '1.3.6.1.1.21.3'
LDAP_OID_TRANSACTION_ABORT = '1.3.6.1.1.21.4'


class TxnRFC5805Error(NotImplementedError):
    def __str__(self):
        return (
            'Your server uses the proper RFC 5805 transaction control, but it is not yet fully supported yet. '
            'Please open an issue in which you describe the LDAP server you are using.'
        )


# ----- Transaction Start -----
class TxnStartRequest(ExtendedRequest):
    def __init__(self):
        super().__init__(requestName=LDAP_OID_TRANSACTION_START, requestValue=None)


class TxnStartResponse(ExtendedResponse):
    responseName = None
    responseValue = None


# ----- Transaction Control -----
class TxnRequestControl(RequestControl):
    def __init__(self, txn_id: bytes):
        super().__init__(
            controlType=LDAP_OID_TRANSACTION_SPECIFICATION_CONTROL,
            criticality=True,
            encodedControlValue=txn_id,
        )

    def __str__(self):
        return self.encodedControlValue

    def __repr__(self):
        return f'<TxnRequestControl: {self.encodedControlValue}>'


# ----- Transaction End -----
class TxnEndRequest(ExtendedRequest):
    def __init__(self, txn_id: bytes, commit: bool = True):
        # note: on some implemenations txn_id is just an empty string
        super().__init__(requestName=LDAP_OID_TRANSACTION_END, requestValue=None)
        self.commit = commit
        self.txn_id = txn_id

    def asn1(self):
        p = TxnEndReq()
        p.setComponentByName('identifier', self.txn_id)
        p.setComponentByName('commit', self.commit)
        return p

    def encodedRequestValue(self):
        return ber_encoder.encode(self.asn1())


class TxnEndResponse(ExtendedResponse):
    responseName = None

    def __init__(self, *args, **kwargs):
        self.message_id = None
        self.updatesControls = []
        super().__init__(self, *args, **kwargs)

    def decodeResponseValue(self, value):
        response_value, _ = ber_decoder.decode(value, asn1Spec=TxnEndRes())
        msgid = response_value.getComponentByName('messageID')
        if msgid is not None and msgid.hasValue():
            self.message_id = int(msgid)

        ucs = response_value.getComponentByName('updatesControls')
        if ucs is not None and ucs.hasValue():
            for uc in ucs:
                mid = int(uc.getComponentByName('messageID'))
                ctrls = uc.getComponentByName('controls')
                self.updatesControls.append((mid, ctrls))


# ----- Transaction helpers for DatabaseWrapper -----
def start_ldap_txn(connection) -> bytes:
    """
    Perform a Start Transaction extop.
    Returns txn_id, which can be an empty string in some server implementations.
    """
    msgid = connection.extop(TxnStartRequest())
    rtype, rdata, rmsgid, sctrls, respoid, respvalue = connection.result4(msgid, all=1, add_extop=1)
    return respvalue


def end_ldap_txn(connection, txn_id: bytes, commit: bool):
    """
    Perform an End Transaction extop.
    """
    connection.extop_s(TxnEndRequest(txn_id, commit))


@contextmanager
def as_ldap_transaction(connection: ReconnectLDAPObject | SimpleLDAPObject):
    txn_id = start_ldap_txn(connection)
    ctrl = TxnRequestControl(txn_id)

    try:
        yield ctrl

    except Exception:
        end_ldap_txn(connection, txn_id, commit=False)
        raise

    end_ldap_txn(connection, txn_id, commit=True)
