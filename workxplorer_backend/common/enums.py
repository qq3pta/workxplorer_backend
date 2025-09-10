from enum import StrEnum

class Role(StrEnum):
    LOGISTIC = "LOGISTIC"
    CUSTOMER = "CUSTOMER"
    CARRIER  = "CARRIER"

class TransportType(StrEnum):
    TENT = "TENT"
    CONT = "CONTAINER"
    REEF = "REEFER"
    DUMP = "DUMP"
    CARCAR = "CAR_CARRIER"
    GRAIN = "GRAIN"
    CRANE = "CRANE"
    TIMBER = "TIMBER"
    PICKUP = "PICKUP"
    CEM = "CEMENT"
    TANK = "TANKER"
    MEGA = "MEGA"

class Currency(StrEnum):
    UZS = "UZS"
    KZT = "KZT"
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"

class DocumentCategory(StrEnum):
    LICENSE = "LICENSE"
    DRIVER = "DRIVER"
    CONTRACT = "CONTRACT"
    LOAD = "LOAD"
    UNLOAD = "UNLOAD"
    EXTRA = "EXTRA"