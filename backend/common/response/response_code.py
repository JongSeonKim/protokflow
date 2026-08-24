import dataclasses

from enum import Enum

from backend.common.i18n import t


class CustomCodeBase(Enum):
    """Custom status code base class"""

    @property
    def code(self) -> int:
        """Get status code"""
        return self.value[0]

    @property
    def msg(self) -> str:
        """Get status code information"""
        message = self.value[1]
        return t(message)


class CustomResponseCode(CustomCodeBase):
    """Custom response status code"""

    HTTP_200 = (200, "response.success")
    HTTP_400 = (400, "response.error")
    HTTP_500 = (500, "Internal server error")


class CustomErrorCode(CustomCodeBase):
    """Custom error status codes"""

    pass


@dataclasses.dataclass
class CustomResponse:
    """
    Provide open-ended response status codes, rather than enumerations,
    which may be useful if you want to customize response information
    """

    code: int
    msg: str


class StandardResponseCode:
    """Standard response status code"""

    """
    HTTP codes
    See HTTP Status Code Registry:
    https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml

    And RFC 2324 - https://tools.ietf.org/html/rfc2324
    """
    HTTP_100 = 100  # CONTINUE
    HTTP_101 = 101  # SWITCHING_PROTOCOLS
    HTTP_102 = 102  # PROCESSING
    HTTP_103 = 103  # EARLY_HINTS
    HTTP_200 = 200  # OK
    HTTP_201 = 201  # CREATED
    HTTP_202 = 202  # ACCEPTED
    HTTP_203 = 203  # NON_AUTHORITATIVE_INFORMATION
    HTTP_204 = 204  # NO_CONTENT
    HTTP_205 = 205  # RESET_CONTENTSWAP
    HTTP_206 = 206  # PARTIAL_CONTENTSWAP
    HTTP_207 = 207  # MULTI_STATUSSWAP
    HTTP_208 = 208  # ALREADY_REPORTEDSWAP
    HTTP_226 = 226  # IM_USEDSWAP
    HTTP_300 = 300  # MULTIPLE_CHOICESSWAP
    HTTP_301 = 301  # MOVED_PERMANENTLYSWAP
    HTTP_302 = 302  # FOUNDSWAP
    HTTP_303 = 303  # SEE_OTHERSWAP
    HTTP_304 = 304  # NOT_MODIFIEDSWAP
    HTTP_305 = 305  # USE_PROXYSWAP
    HTTP_307 = 307  # TEMPORARY_REDIRECTSWAP
    HTTP_308 = 308  # PERMANENT_REDIRECTSWAP
    HTTP_400 = 400  # BAD_REQUESTSWAP
    HTTP_401 = 401  # UNAUTHORIZEDSWAP
    HTTP_402 = 402  # PAYMENT_REQUIREDSWAP
    HTTP_403 = 403  # FORBIDDENSWAP
    HTTP_404 = 404  # NOT_FOUNDSWAP
    HTTP_405 = 405  # METHOD_NOT_ALLOWEDSWAP
    HTTP_406 = 406  # NOT_ACCEPTABLESWAP
    HTTP_407 = 407  # PROXY_AUTHENTICATION_REQUIREDSWAP
    HTTP_408 = 408  # REQUEST_TIMEOUTSWAP
    HTTP_409 = 409  # CONFLICTSWAP
    HTTP_410 = 410  # GONESWAP
    HTTP_411 = 411  # LENGTH_REQUIREDSWAP
    HTTP_412 = 412  # PRECONDITION_FAILEDSWAP
    HTTP_413 = 413  # REQUEST_ENTITY_TOO_LARGESWAP
    HTTP_414 = 414  # REQUEST_URI_TOO_LONGSWAP
    HTTP_415 = 415  # UNSUPPORTED_MEDIA_TYPESWAP
    HTTP_416 = 416  # REQUESTED_RANGE_NOT_SATISFIABLESWAP
    HTTP_417 = 417  # EXPECTATION_FAILEDSWAP
    HTTP_418 = 418  # UNUSEDSWAP
    HTTP_421 = 421  # MISDIRECTED_REQUESTSWAP
    HTTP_422 = 422  # UNPROCESSABLE_CONTENTSWAP
    HTTP_423 = 423  # LOCKEDSWAP
    HTTP_424 = 424  # FAILED_DEPENDENCYSWAP
    HTTP_425 = 425  # TOO_EARLYSWAP
    HTTP_426 = 426  # UPGRADE_REQUIREDSWAP
    HTTP_427 = 427  # UNASSIGNEDSWAP
    HTTP_428 = 428  # PRECONDITION_REQUIREDSWAP
    HTTP_429 = 429  # TOO_MANY_REQUESTSSWAP
    HTTP_430 = 430  # UnassignedSWAP
    HTTP_431 = 431  # REQUEST_HEADER_FIELDS_TOO_LARGESWAP
    HTTP_451 = 451  # UNAVAILABLE_FOR_LEGAL_REASONSSWAP
    HTTP_500 = 500  # INTERNAL_SERVER_ERRORSWAP
    HTTP_501 = 501  # NOT_IMPLEMENTEDSWAP
    HTTP_502 = 502  # BAD_GATEWAYSWAP
    HTTP_503 = 503  # SERVICE_UNAVAILABLESWAP
    HTTP_504 = 504  # GATEWAY_TIMEOUTSWAP
    HTTP_505 = 505  # HTTP_VERSION_NOT_SUPPORTEDSWAP
    HTTP_506 = 506  # VARIANT_ALSO_NEGOTIATESSWAP
    HTTP_507 = 507  # INSUFFICIENT_STORAGESWAP
    HTTP_508 = 508  # LOOP_DETECTEDSWAP
    HTTP_509 = 509  # UNASSIGNEDSWAP
    HTTP_510 = 510  # NOT_EXTENDEDSWAP
    HTTP_511 = 511  # NETWORK_AUTHENTICATION_REQUIREDSWAP

    """
    WebSocket codes
    https://www.iana.org/assignments/websocket/websocket.xml#close-code-number
    https://developer.mozilla.org/en-US/docs/Web/API/CloseEvent
    """
    WS_1000 = 1000  # NORMAL_CLOSURESWAP
    WS_1001 = 1001  # GOING_AWAYSWAP
    WS_1002 = 1002  # PROTOCOL_ERRORSWAP
    WS_1003 = 1003  # UNSUPPORTED_DATASWAP
    WS_1005 = 1005  # NO_STATUS_RCVDSWAP
    WS_1006 = 1006  # ABNORMAL_CLOSURESWAP
    WS_1007 = 1007  # INVALID_FRAME_PAYLOAD_DATASWAP
    WS_1008 = 1008  # POLICY_VIOLATIONSWAP
    WS_1009 = 1009  # MESSAGE_TOO_BIGSWAP
    WS_1010 = 1010  # MANDATORY_EXTSWAP
    WS_1011 = 1011  # INTERNAL_ERRORSWAP
    WS_1012 = 1012  # SERVICE_RESTARTSWAP
    WS_1013 = 1013  # TRY_AGAIN_LATERSWAP
    WS_1014 = 1014  # BAD_GATEWAYSWAP
    WS_1015 = 1015  # TLS_HANDSHAKESWAP
    WS_3000 = 3000  # UNAUTHORIZEDSWAP
    WS_3003 = 3003  # FORBIDDENSWAP
