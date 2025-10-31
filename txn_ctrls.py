from ldap.controls import RequestControl
from ldap.extop import ExtendedRequest, ExtendedResponse
from pyasn1.codec.ber import decoder as ber_decoder, encoder as ber_encoder
from pyasn_rfc5805 import TxnEndReq, TxnEndRes

# OIDs from RFC 5805
OID_TXN_START = '1.3.6.1.1.21.1'
OID_TXN_SPEC_CTRL = '1.3.6.1.1.21.2'
OID_TXN_END = '1.3.6.1.1.21.3'


class TxnRequestControl(RequestControl):
    controlType = OID_TXN_SPEC_CTRL

    def __init__(
        self,
        txn_id: str,
        commit: bool = True,  # False here stands for abort
    ):
        super().__init__(controlType=self.controlType, criticality=True)
        self.commit = commit
        self.txn_id = txn_id

    def encodeControlValue(self):
        p = TxnEndReq()
        p.setComponentByName('commit', self.commit)
        p.setComponentByName('identifier', self.txn_id)
        return ber_encoder.encode(p)


class TxnStartRequest(ExtendedRequest):
    requestName = OID_TXN_START
    requestValue = None

    def __init__(self):
        super().__init__(requestName=OID_TXN_START, requestValue=None)


class TxnStartResponse(ExtendedResponse):
    responseName = None
    responseValue = None


class TxnEndRequest(ExtendedRequest):
    def __init__(self, commit: bool = True):
        super().__init__(requestName=OID_TXN_END, requestValue=None)
        self.commit = commit

    def asn1(self):
        p = TxnEndReq()
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
