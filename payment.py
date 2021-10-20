# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from io import StringIO
import csv
import datetime
from decimal import Decimal
from itertools import chain
from sql.functions import Abs

from trytond.model import Workflow, ModelView, ModelSQL, fields, Unique
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, If, Bool
from trytond.transaction import Transaction
from trytond.wizard import Wizard, StateView, StateTransition, Button
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.modules.currency.fields import Monetary

__all__ = ['Move', 'Group', 'Payment', 'ImportPaymentsStart', 'ImportPayments',
    'CreateWriteOffMoveStart', 'CreateWriteOffMove']

KINDS = [
    ('customer', 'Customer'),
    ('supplier', 'Supplier'),
    ]
_STATES = {
    'readonly': Eval('state') != 'draft',
    }
_DEPENDS = ['state']
_ZERO = Decimal('0.0')


class Move(metaclass=PoolMeta):
    __name__ = 'account.move'

    @classmethod
    def _get_origin(cls):
        return super(Move, cls)._get_origin() + [
            'account.invoice.line.payment']


class Group(Workflow, ModelSQL, ModelView):
    'Invoice Line Payment Group'
    __name__ = 'account.invoice.line.payment.group'
    _rec_name = 'reference'
    reference = fields.Char('Reference', required=True, states=_STATES,
        depends=_DEPENDS)
    party = fields.Many2One('party.party', 'Party', required=True,
        states=_STATES, depends=_DEPENDS)
    company = fields.Many2One('company.company', 'Company', required=True,
        select=True, states=_STATES, depends=_DEPENDS,
        domain=[
            ('id', If(Eval('context', {}).contains('company'), '=', '!='),
                Eval('context', {}).get('company', -1)),
            ])
    currency = fields.Function(fields.Many2One('currency.currency',
            'Currency'),
        'on_change_with_currency')
    kind = fields.Selection(KINDS, 'Kind', required=True, states=_STATES,
        depends=_DEPENDS)
    payments = fields.One2Many('account.invoice.line.payment', 'group',
        'Payments', states=_STATES, depends=_DEPENDS)
    move_line = fields.Many2One('account.move.line', 'Move Line',
        required=True,
        domain=[
            ('party', '=', Eval('party')),
            If(Eval('kind') == 'customer',
                ('credit', '>', 0),
                ('debit', '>', 0)
                )
            ],
        states=_STATES, depends=_DEPENDS + ['party', 'kind'],
        ondelete='RESTRICT')
    move_line_amount = fields.Function(Monetary('Move Line Amount',
            currency='currency', digits='currency'),
        'on_change_with_move_line_amount', searcher='search_move_line_amount')
    state = fields.Selection([
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('done', 'Done'),
            ], 'State', required=True, readonly=True)

    @classmethod
    def __setup__(cls):
        super(Group, cls).__setup__()
        cls._transitions |= set((
                ('draft', 'confirmed'),
                ('confirmed', 'draft'),
                ('confirmed', 'done'),
                ('done', 'confirmed'),
                ))
        cls._buttons.update({
                'draft': {
                    'invisible': Eval('state') != 'confirmed',
                    'icon': 'tryton-clear',
                    },
                'confirm': {
                    'invisible': Eval('state') != 'draft',
                    'icon': 'tryton-forward',
                    },
                'search_lines': {
                    'invisible': Eval('state') == 'done',
                    'icon': 'tryton-find',
                    },
                'import_payments': {
                    'invisible': Eval('state') != 'draft',
                    'icon': 'tryton-launch',
                    },
                })
        t = cls.__table__()
        cls._sql_constraints += [
            ('move_line_uniq', Unique(t, t.move_line), 'There can not be two '
                'Invoice Line Payment Groups with the same Move Line.'),
            ]

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_currency():
        Company = Pool().get('company.company')
        if Transaction().context.get('company'):
            company = Company(Transaction().context['company'])
            return company.currency.id

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_kind():
        return 'customer'

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        if self.company:
            return self.company.currency.id

    @fields.depends('move_line')
    def on_change_with_move_line_amount(self, name=None):
        if not self.move_line:
            return Decimal(0)
        return abs(self.move_line.debit - self.move_line.credit)

    @classmethod
    def search_move_line_amount(cls, name, clause):
        pool = Pool()
        MoveLine = pool.get('account.move.line')
        _, operator, value = clause
        Operator = fields.SQL_OPERATORS[operator]
        table = cls.__table__()
        move_line = MoveLine.__table__()

        main_amount = Abs(move_line.credit - move_line.debit)
        value = cls.move_line_amount.sql_format(value)

        query = table.join(move_line,
            condition=(table.move_line == move_line.id)).select(table.id,
                    where=Operator(main_amount, value))
        return [('id', 'in', query)]

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        Sequence = pool.get('ir.sequence')

        vlist = [v.copy() for v in vlist]
        for values in vlist:
            if 'reference' not in values:
                values['reference'] = Sequence.get(
                    'account.invoice.line.payment.group')

        return super(Group, cls).create(vlist)

    @classmethod
    def copy(cls, groups, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('move_line')
        default.setdefault('payments')
        return super(Group, cls).copy(groups, default=default)

    def is_done(self):
        if all(p.state == 'done' for p in self.payments):
            return True
        return False

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, groups):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('confirmed')
    def confirm(cls, groups):
        for group in groups:
            payments_amount = sum([x.amount for x in group.payments])
            if payments_amount != group.move_line_amount:
                raise UserError(gettext('account_invoice_line_payment.invalid_amounts',
                    amount=payments_amount,
                    payment=group.rec_name,
                    move_line_amount=group.move_line_amount))

    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def done(cls, groups):
        pass

    @classmethod
    def process(cls, groups):
        done = []
        confirm = []
        for group in groups:
            if group.is_done():
                if group.state != 'done':
                    done.append(group)
            if group.state != 'confirmed':
                payments_amount = sum([x.amount for x in group.payments])
                if payments_amount == group.move_line_amount:
                    confirm.append(group)
        if confirm:
            cls.confirm(confirm)
        if done:
            cls.done(done)

    @classmethod
    @ModelView.button
    def search_lines(cls, groups):
        pool = Pool()
        Payment = pool.get('account.invoice.line.payment')
        payments = list(chain(*[g.payments for g in groups]))
        Payment.search_line(payments)

    @classmethod
    @ModelView.button_action(
        'account_invoice_line_payment.wizard_import_payments')
    def import_payments(cls, groups):
        pass

_STATES = {
    'readonly': Eval('state') != 'draft',
    }
_DEPENDS = ['state']


class Payment(Workflow, ModelSQL, ModelView):
    'Invoice Line Payment'
    __name__ = 'account.invoice.line.payment'
    company = fields.Function(fields.Many2One('company.company', 'Company'),
        'on_change_with_company', searcher='search_group_field')
    party = fields.Function(fields.Many2One('party.party', 'Party'),
        'on_change_with_party', searcher='search_group_field')
    kind = fields.Function(fields.Selection(KINDS, 'Kind'),
        'on_change_with_kind', searcher='search_group_field')
    currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'), 'on_change_with_currency', searcher='search_group_field')
    date = fields.Date('Date', required=True, states=_STATES, depends=_DEPENDS)
    amount = Monetary('Amount', currency='currency', digits='currency',
        required=True, states=_STATES, depends=_DEPENDS)
    line = fields.Many2One('account.invoice.line', 'Line', ondelete='RESTRICT',
        domain=[
            ('type', '=', 'line'),
            If(Eval('kind') == 'customer',
                ('invoice.type', '=', 'out'),
                ('invoice.type', '=', 'in'),
                ),
            ('party', '=', Eval('party')),
            ('currency', '=', Eval('currency')),
            ],
        # This domain breaks when moving a paiment from done to draft with a
        # paid invoice.
        #     If(Eval('state') == 'draft',
        #         (('payment_amount', '!=', 0),),
        #         ()
        #         ),
        #     If(Eval('state') == 'draft',
        #         [
        #             ('invoice.state', '=', 'posted'),
        #             ],
        #         []),
        states={
            'readonly': Eval('state') != 'draft',
            'required': Eval('state') == 'done',
            },
        depends=['state', 'group', 'kind', 'party', 'currency'])
    description = fields.Char('Description', states=_STATES, depends=_DEPENDS)
    group = fields.Many2One('account.invoice.line.payment.group', 'Group',
        readonly=True, required=True, ondelete='CASCADE')
    difference = fields.Function(Monetary('Difference',
        currency='currency', digits='currency'), 'on_change_with_difference')
    difference_move = fields.Many2One('account.move', 'Diference Move',
        readonly=True,
        states={
            'invisible': ~Bool(Eval('difference_move')),
            },)
    state = fields.Selection([
            ('draft', 'Draft'),
            ('done', 'Done'),
            ], 'State', readonly=True, select=True)

    @classmethod
    def __setup__(cls):
        super(Payment, cls).__setup__()
        cls._order.insert(0, ('date', 'DESC'))
        cls._transitions |= set((
                ('draft', 'done'),
                ('done', 'draft'),
                ))
        cls._buttons.update({
                'draft': {
                    'invisible': Eval('state') != 'done',
                    'icon': 'tryton-back',
                    },
                'done': {
                    'invisible': Eval('state') != 'draft',
                    'icon': 'tryton-forward',
                    },
                'search_line': {
                    'invisible': Bool(Eval('line')),
                    'icon': 'tryton-find',
                    },
                'create_writeoff': {
                    'invisible': (Bool(Eval('difference_move') |
                            ~Bool(Eval('line')) | (Eval('state') == 'done'))
                        | ~(Eval('difference'))),
                    'icon': 'tryton-ok',
                    },
                })

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_date():
        pool = Pool()
        Date = pool.get('ir.date')
        return Date.today()

    @staticmethod
    def default_state():
        return 'draft'

    @fields.depends('group', '_parent_group.kind')
    def on_change_with_kind(self, name=None):
        return self.group and self.group.kind

    @fields.depends('group', '_parent_group.party')
    def on_change_with_party(self, name=None):
        return self.group and self.group.party and self.group.party.id

    @fields.depends('group', '_parent_group.currency')
    def on_change_with_currency(self, name=None):
        return self.group and self.group.currency and self.group.currency.id

    @fields.depends('line', '_parent_line.amount', 'amount', 'currency')
    def on_change_with_difference(self, name=None):
        if not self.line or not self.amount:
            return Decimal(0)
        digits = self.currency and self.currency.digits or 2
        amount = (self.line.amount + self.line.tax_amount) - self.amount
        return amount.quantize(Decimal(str(10 ** -digits)))

    @fields.depends('group', '_parent_group.company')
    def on_change_with_company(self, name=None):
        if self.group:
            return self.group.company.id

    @classmethod
    def search_group_field(cls, name, clause):
        return [('group.%s' % clause[0],) + tuple(clause[1:])]

    @classmethod
    def process_invoices(cls, payments):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        invoices = list({p.line.invoice for p in payments
            if p.line and p.line.invoice})
        invoices = Invoice.browse(invoices)
        Invoice.process(invoices)

    @classmethod
    def delete(cls, payments):
        for payment in payments:
            if payment.state != 'draft':
                raise UserError(gettext('account_invoice_line_payment.delete_draft',
                    payment=payment.rec_name))
        super(Payment, cls).delete(payments)

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, payments):
        pool = Pool()
        Move = pool.get('account.move')
        Group = pool.get('account.invoice.line.payment.group')
        groups = set([p.group for p in payments])
        moves = [p.difference_move for p in payments if p.difference_move]
        if moves:
            Move.draft(moves)
            Move.delete(moves)
        # Write state before processing
        cls.write(payments, {'state': 'draft'})
        cls.process_invoices(payments)
        Group.process(list(groups))

    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def done(cls, payments):
        pool = Pool()
        Group = pool.get('account.invoice.line.payment.group')
        Move = pool.get('account.move')
        groups = set()
        moves = []
        for payment in payments:
            if not payment.line:
                raise UserError(gettext('account_invoice_line_payment.done_needs_line',
                    payment=payment.rec_name))
            if payment.difference < Decimal(0) and not payment.difference_move:
                raise UserError(gettext('account_invoice_line_payment.different_amount',
                    payment=payment.rec_name,
                    difference=payment.difference))

            if payment.difference_move:
                moves.append(payment.difference_move)
            groups.add(payment.group)
        if moves:
            Move.post(moves)
        # Write state before processing
        cls.write(payments, {'state': 'done'})
        cls.process_invoices(payments)
        Group.process(list(groups))

    def get_difference_move(self, writeoff, date=None, description=None):
        pool = Pool()
        Period = pool.get('account.period')
        Move = pool.get('account.move')
        Line = pool.get('account.move.line')
        amount = self.difference
        if date is None:
            date = self.date
        reconcile_account = self.line.invoice.account
        reconcile_party = self.group.party
        if amount >= 0:
            account = writeoff.debit_account
        else:
            account = writeoff.credit_account
        move = Move()
        move.journal = writeoff.journal
        move.period = Period(Period.find(reconcile_account.company.id,
                date=date))
        move.date = date
        move.description = description
        move.origin = str(self)
        lines = []
        line = Line()
        line.account = reconcile_account
        line.party = (reconcile_party if reconcile_account.party_required
            else None)
        line.debit = amount < Decimal(0) and abs(amount) or Decimal(0)
        line.credit = amount > Decimal(0) and amount or Decimal(0)
        lines.append(line)
        line = Line()
        line.account = account
        line.party = reconcile_party if account.party_required else None
        line.debit = amount > Decimal(0) and amount or Decimal(0)
        line.credit = amount < Decimal(0) and abs(amount) or Decimal(0)
        lines.append(line)
        move.lines = lines
        return move

    def _invoice_line_search_domain(self):
        return [
            ('invoice.party', '=', self.group.party.id),
            ('invoice.currency', '=', self.group.currency.id),
            ('invoice.state', '=', 'posted'),
            ]

    def _get_invoice_line(self, skip_ids=None):
        'Returns the invoice line for the current payment'
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        if skip_ids is None:
            skip_ids = set()
        domain = self._invoice_line_search_domain()
        domain.append(('id', 'not in', skip_ids))
        lines = []
        for line in InvoiceLine.search(domain):
            if line.payment_amount == self.amount:
                lines.append(line)
                if len(lines) > 1:
                    break
        if len(lines) == 1:
            return lines[0]

    @classmethod
    @ModelView.button
    def search_line(cls, payments):
        skip_ids = set()
        to_write = []
        for payment in payments:
            if payment.line:
                continue
            line = payment._get_invoice_line(skip_ids=skip_ids)
            if line:
                skip_ids.add(line.id)
                to_write.extend(([payment], {
                            'line': line.id,
                            }))
        if to_write:
            cls.write(*to_write)

    @classmethod
    @ModelView.button_action(
        'account_invoice_line_payment.wizard_writeoff')
    def create_writeoff(cls, payments):
        pass


class ImportPaymentsStart(ModelView):
    'Import Payments Start'
    __name__ = 'account.invoice.line.payment.import.start'

    data = fields.Binary('File', required=True)
    confirm = fields.Boolean('Confirm group')

    @staticmethod
    def default_confirm():
        return True


class ImportPayments(Wizard):
    'Import Payments'
    __name__ = 'account.invoice.line.payment.import'
    start = StateView('account.invoice.line.payment.import.start',
        'account_invoice_line_payment.import_payments_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Import', 'import_', 'tryton-ok', default=True),
            ])
    import_ = StateTransition()

    def get_payment(self, row):
        pool = Pool()
        Payment = pool.get('account.invoice.line.payment')
        date, amount, description = row
        payment = Payment()
        date_args = list(map(int, date.split('/')))
        date_args.reverse()
        payment.date = datetime.date(*date_args)
        payment.amount = Decimal(str(amount.replace(',', '.')))
        payment.description = description
        return payment

    def transition_import_(self):
        pool = Pool()
        Group = pool.get('account.invoice.line.payment.group')
        group = Group(Transaction().context['active_id'])
        dialect = csv.Sniffer().sniff(str(self.start.data[:1024]))
        reader = csv.reader(StringIO(self.start.data.decode('utf8')),
            dialect=dialect)
        next(reader)  # Skip header line
        payments = []
        for row in reader:
            payments.append(self.get_payment(row))
        group.payments = payments
        group.save()
        Group.search_lines([group])
        if self.start.confirm:
            Group.confirm([group])
        return 'end'


class CreateWriteOffMoveStart(ModelView):
    'Create Write-Off Move'
    __name__ = 'account.invoice.line.payment.write-off.start'
    writeoff = fields.Many2One('account.move.reconcile.write_off', 'Journal',
        required=True)
    date = fields.Date('Date', required=True)
    amount = Monetary('Amount', digits='currency', currency='currency',
        readonly=True)
    currency = fields.Many2One('currency.currency', 'Currency', readonly=True)
    description = fields.Char('Description')


class CreateWriteOffMove(Wizard):
    'Create Write-Off Move'
    __name__ = 'account.invoice.line.payment.write-off'
    start = StateView('account.invoice.line.payment.write-off.start',
        'account_invoice_line_payment.writeoff_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Create', 'create_', 'tryton-ok', default=True),
            ])
    create_ = StateTransition()

    def default_start(self, fields):
        payment = self.get_payment()
        return {
            'date': payment.date,
            'amount': payment.difference,
            'currency': payment.currency,
            }

    def get_payment(self):
        pool = Pool()
        Payment = pool.get('account.invoice.line.payment')
        return Payment(Transaction().context['active_id'])

    def transition_create_(self):
        pool = Pool()
        Payment = pool.get('account.invoice.line.payment')
        payment = self.get_payment()
        move = payment.get_difference_move(self.start.writeoff,
            self.start.date, self.start.description)
        move.save()
        payment.difference_move = move
        payment.save()
        Payment.done([payment])
        return 'end'
