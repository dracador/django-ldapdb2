from pyasn1.type import namedtype, univ
from pyasn1_modules.rfc2251 import Controls, MessageID


class UpdateControls(univ.Sequence):
    componentType = namedtype.NamedTypes(
        namedtype.NamedType('messageID', MessageID()),
        namedtype.NamedType('controls', Controls()),
    )


class UpdatesControls(univ.SequenceOf):
    componentType = UpdateControls()


class TxnEndReq(univ.Sequence):
    #    txnEndReq ::= SEQUENCE {
    #         commit         BOOLEAN DEFAULT TRUE,
    #         identifier     OCTET STRING }
    componentType = namedtype.NamedTypes(
        namedtype.NamedType('identifier', univ.OctetString()),
        namedtype.NamedType('commit', univ.Boolean(True)),
    )


class TxnEndRes(univ.Sequence):
    #    txnEndRes ::= SEQUENCE {
    #         messageID MessageID OPTIONAL,
    #              -- msgid associated with non-success resultCode
    #         updatesControls SEQUENCE OF updateControls SEQUENCE {
    #              messageID MessageID,
    #                   -- msgid associated with controls
    #              controls  Controls
    #         } OPTIONAL
    #    }
    componentType = namedtype.NamedTypes(
        namedtype.OptionalNamedType('messageID', MessageID()),
        namedtype.OptionalNamedType('updatesControls', UpdatesControls()),
    )
