# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import invoice
from . import payment
from . import party


def register():
    Pool.register(
        payment.Move,
        payment.Group,
        payment.Payment,
        invoice.Invoice,
        invoice.InvoiceLine,
        payment.ImportPaymentsStart,
        payment.CreateWriteOffMoveStart,
        module='account_invoice_line_payment', type_='model')
    Pool.register(
        payment.ImportPayments,
        payment.CreateWriteOffMove,
        party.PartyReplace,
        module='account_invoice_line_payment', type_='wizard')
