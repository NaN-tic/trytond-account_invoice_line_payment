# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal
from sql import Cast, Literal
from sql.aggregate import Sum
from sql.conditionals import Coalesce
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval
from trytond.tools import grouped_slice, reduce_ids
from trytond.transaction import Transaction
from trytond.modules.currency.fields import Monetary

__all__ = ['Invoice', 'InvoiceLine']


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'

    line_payments = fields.Function(fields.Many2Many(
            'account.invoice.line.payment', None,None, 'Line Payments',
            states={
                'invisible': ~Bool(Eval('line_payments')),
                }),
        'get_line_payments')

    @classmethod
    def write(cls, *args):
        Line = Pool().get('account.invoice.line')

        to_write = []
        actions = iter(args)
        for invoices, values in zip(actions, actions):
            if 'party' in values:
                for invoice in invoices:
                    to_write.extend((list(invoice.lines), {
                        'party': values['party']}))
        if to_write:
            Line.write(*to_write)
        super(Invoice, cls).write(*args)

    @classmethod
    def get_amount_to_pay(cls, invoices, name):
        result = super(Invoice, cls).get_amount_to_pay(invoices, name)
        for invoice in invoices:
            # Only loop for invoices that have amount to pay
            if result[invoice.id]:
                for line in invoice.lines:
                    for payment in line.payments:
                        if payment.state != 'done':
                            continue
                        result[invoice.id] -= payment.amount
        return result

    def get_reconciled(self, name):
        lines_to_pay = [l for l in self.lines if l.type == 'line' and
            l.amount != Decimal(0)]
        if (lines_to_pay and all(l.paid for l in lines_to_pay)):
            return max(p.date for l in lines_to_pay for p in l.payments)
        return super(Invoice, self).get_reconciled(name)

    def get_line_payments(self, name):
        return list(set(p.id for l in self.lines for p in l.payments))


class InvoiceLine(metaclass=PoolMeta):
    __name__ = 'account.invoice.line'

    payment_amount = fields.Function(Monetary('Payment Amount',
        currency='currency', digits='currency'), 'get_payment_amount',
        searcher='search_payment_amount')
    payments = fields.One2Many('account.invoice.line.payment', 'line',
        'Payments', readonly=True)

    @classmethod
    def create(cls, vlist):
        Invoice = Pool().get('account.invoice')

        vlist = [x.copy() for x in vlist]
        invoices = dict((x.id, x) for x in Invoice.browse(list(
            set([vals['invoice'] for vals in vlist if vals.get('invoice')]))))
        for vals in vlist:
            if vals.get('invoice'):
                vals['party'] = invoices.get(vals['invoice']).party.id
        return super(InvoiceLine, cls).create(vlist)

    @property
    def paid(self):
        difference = False
        done = True
        if not self.payments:
            return False
        for payment in self.payments:
            if payment.state != 'done':
                done = False
            if payment.difference_move:
                difference = True
        return (difference or self.payment_amount == Decimal(0)) and done

    @property
    def tax_amount(self):
        tax_amount = Decimal(0)
        if self.type != 'line':
            return tax_amount
        return sum((v.amount for v in self._get_taxes().values()), Decimal(0))

    @classmethod
    def _compute_payment_amount_query(cls):
        pool = Pool()
        Payment = pool.get('account.invoice.line.payment')
        InvoiceLineTax = pool.get('account.invoice.line-account.tax')
        Tax = pool.get('account.tax')
        Invoice = pool.get('account.invoice')
        table = cls.__table__()
        payment = Payment.__table__()
        line_tax = InvoiceLineTax.__table__()
        tax = Tax.__table__()
        invoice = Invoice.__table__()

        # TODO: Sum amount taxes
        amount = Cast(Coalesce(table.quantity, 0.0) *
            Coalesce(table.unit_price, 0.0), cls.unit_price.sql_type().base)
        taxes_subquery = line_tax.select(line_tax.tax,
            where=(line_tax.line == table.id))
        tax_rate = tax.select(Literal(1) + Sum(tax.rate),
            where=(tax.id.in_(taxes_subquery) | tax.parent.in_(taxes_subquery))
                & (tax.type == 'percentage'))
        payment_amount = Sum(Coalesce(payment.amount, 0))
        line_amount = amount * tax_rate
        main_amount = line_amount - payment_amount
        return {
            'invoice_line': table,
            'payment': payment,
            'invoice': invoice,
            'line_tax': line_tax,
            'tax': tax,
            }, main_amount

    @classmethod
    def get_payment_amount(cls, lines, name):
        amounts = {}
#        for line in lines:
#            amount = line.amount + line.tax_amount
#            for payment in line.payments:
#                amount -= payment.amount
#            currency = line.currency
#            if line.invoice:
#                currency = line.invoice.currency
#            amounts[line.id] = currency.round(amount)
        cursor = Transaction().connection.cursor()
        tables, main_amount = cls._compute_payment_amount_query()
        table = tables['invoice_line']
        invoice = tables['invoice']
        payment = tables['payment']
        for sub_lines in grouped_slice(lines):
            ids2line = dict((l.id, l) for l in sub_lines)
            query = table.join(invoice, type_='LEFT',
                condition=(invoice.id == table.invoice)
                ).join(payment, type_='LEFT',
                condition=((table.id == payment.line) &
                        (payment.state == 'done'))
                ).select(table.id, main_amount,
                    where=reduce_ids(table.id, ids2line.keys()),
                    group_by=(table.id, invoice.type))
            cursor.execute(*query)
            for line_id, amount in cursor.fetchall():
                line = ids2line[line_id]
                currency = line.currency
                if line.invoice:
                    currency = line.invoice.currency

                # SQLite uses float for SUM
                if not isinstance(amount, Decimal):
                    amount = Decimal(amount or 0)
                amounts[line_id] = currency.round(amount)
        return amounts

    @classmethod
    def search_payment_amount(cls, name, clause):
        _, operator, value = clause
        Operator = fields.SQL_OPERATORS[operator]
        tables, main_amount = cls._compute_payment_amount_query()
        table = tables['invoice_line']
        invoice = tables['invoice']
        payment = tables['payment']
        value = cls.payment_amount.sql_format(value)
        query = table.join(invoice, type_='LEFT',
            condition=(invoice.id == table.invoice)
            ).join(payment, type_='LEFT',
            condition=((table.id == payment.line) & (payment.state == 'done'))
            ).select(table.id,
                group_by=(table.id,),
                having=Operator(main_amount, value)
                )
        return [('id', 'in', query)]

    @classmethod
    def copy(cls, lines, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('payments', None)
        return super(InvoiceLine, cls).copy(lines, default=default)
