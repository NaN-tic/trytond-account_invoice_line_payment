# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from .invoice import *
from .payment import *


def register():
    Pool.register(
        Move,
        Group,
        Payment,
        Invoice,
        InvoiceLine,
        ImportPaymentsStart,
        CreateWriteOffMoveStart,
        module='account_invoice_line_payment', type_='model')
    Pool.register(
        ImportPayments,
        CreateWriteOffMove,
        module='account_invoice_line_payment', type_='wizard')
