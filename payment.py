# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO
import csv
import datetime
from decimal import Decimal
from itertools import chain
from sql.functions import Abs

from trytond.model import Workflow, ModelView, ModelSQL, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, If, Bool
from trytond.transaction import Transaction
from trytond.wizard import Wizard, StateView, StateTransition, Button

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


class Move:
    __name__ = 'account.move'
    __metaclass__ = PoolMeta

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
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
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
    move_line_amount = fields.Function(fields.Numeric('Move Line Amount',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']),
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
        cls._error_messages.update({
                'invalid_amounts': ('Total payments amount "%s" in payment '
                    'group "%s" must match Move Line amount "%s".'),
                })
        cls._buttons.update({
                'draft': {
                    'invisible': Eval('state') != 'confirmed',
                    'icon': 'tryton-clear',
                    },
                'confirm': {
                    'invisible': Eval('state') != 'draft',
                    'icon': 'tryton-go-next',
                    },
                'search_lines': {
                    'invisible': Eval('state') == 'done',
                    'icon': 'tryton-find',
                    },
                'import_payments': {
                    'invisible': Eval('state') != 'draft',
                    'icon': 'tryton-executable',
                    },
                })
        cls._sql_constraints += [
            ('move_line_uniq', 'UNIQUE(move_line)', 'There can not be two '
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

    @fields.depends('currency')
    def on_change_with_currency_digits(self, name=None):
        if self:
            return self.currency.digits
        return 2

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
                cls.raise_user_error('invalid_amounts', (payments_amount,
                        group.rec_name, group.move_line_amount))

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
        'get_group_field', searcher='search_group_field')
    party = fields.Function(fields.Many2One('party.party', 'Party'),
        'get_group_field', searcher='search_group_field')
    currency = fields.Function(fields.Many2One('currency.currency',
            'Currency'), 'on_change_with_currency')
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
    kind = fields.Function(fields.Selection(KINDS, 'Kind'), 'get_group_field',
        searcher='search_group_field')
    date = fields.Date('Date', required=True, states=_STATES, depends=_DEPENDS)
    amount = fields.Numeric('Amount', required=True,
        digits=(16, Eval('currency_digits', 2)), states=_STATES,
        depends=_DEPENDS + ['currency_digits'])
    line = fields.Many2One('account.invoice.line', 'Line', ondelete='RESTRICT',
        domain=[
            ('type', '=', 'line'),
            If(Eval('kind') == 'customer',
                ('invoice.type', 'in', ['out_invoice', 'out_credit_note']),
                ('invoice.type', 'in', ['in_invoice', 'in_credit_note']),
                ),
            ('invoice.party', '=', Eval('party')),
            ('invoice.currency', '=', Eval('currency')),
            If(Eval('state') == 'draft',
                (('payment_amount', '!=', 0),),
                ()
                ),
            ],
    # This domain breaks when moving a paiment from done to draft with a paid
    # invoice.
    #        If(Eval('state') == 'draft',
    #            [
    #                ('invoice.state', '=', 'posted'),
    #                ],
    #            []),
        states={
            'readonly': Eval('state') != 'draft',
            'required': Eval('state') == 'done',
            },
        depends=['state', 'party', 'currency', 'kind'])
    description = fields.Char('Description', states=_STATES, depends=_DEPENDS)
    group = fields.Many2One('account.invoice.line.payment.group', 'Group',
        readonly=True, required=True, ondelete='CASCADE',
        states={
            'required': Eval('state').in_(['processing', 'succeeded']),
            },
        domain=[
            ('company', '=', Eval('company', -1)),
            ],
        depends=['state', 'company'])
    difference = fields.Function(fields.Numeric('Difference',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']),
        'on_change_with_difference')
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
        cls._error_messages.update({
                'delete_draft': ('Payment "%s" must be in draft state before '
                    'deletion.'),
                'done_needs_line': ('Payment "%s" must have an invoice line '
                    'before it can be done.'),
                'different_amount': ('Payment "%(payment)s" can not be mark as'
                    ' done as it has a difference of "%(difference)s" between '
                    'it amount and its line amount.'),
                })
        cls._transitions |= set((
                ('draft', 'done'),
                ('done', 'draft'),
                ))
        cls._buttons.update({
                'draft': {
                    'invisible': Eval('state') != 'done',
                    'icon': 'tryton-go-previous',
                    },
                'done': {
                    'invisible': Eval('state') != 'draft',
                    'icon': 'tryton-go-next',
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

    def get_group_field(self, name):
        value = getattr(self.group, name)
        if isinstance(value, ModelSQL):
            return value.id
        return value

    @fields.depends('line', 'amount', methods=['currency_digits'])
    def on_change_with_difference(self, name=None):
        if not self.line:
            return Decimal(0)
        digits = self.on_change_with_currency_digits()
        amount = (self.line.amount + self.line.tax_amount) - self.amount
        return amount.quantize(Decimal(str(10 ** -digits)))

    @classmethod
    def search_group_field(cls, name, clause):
        return [('group.%s' % clause[0],) + tuple(clause[1:])]

    @fields.depends('group')
    def on_change_with_currency(self, name=None):
        if self.group:
            return self.group.currency.id

    @fields.depends('group')
    def on_change_with_currency_digits(self, name=None):
        if self.group:
            return self.group.currency.digits
        return 2

    @fields.depends('kind')
    def on_change_kind(self):
        return {
            'line': None,
            }

    @fields.depends('party')
    def on_change_party(self):
        return {
            'line': None,
            }

    @classmethod
    def process_invoices(cls, payments):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        invoices = [p.line.invoice for p in payments
            if p.line and p.line.invoice]
        Invoice.process(invoices)

    @classmethod
    def delete(cls, payments):
        for payment in payments:
            if payment.state != 'draft':
                cls.raise_user_error('delete_draft', (payment.rec_name))
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
                cls.raise_user_error('done_needs_line', payment.rec_name)
            if payment.difference < Decimal(0) and not payment.difference_move:
                cls.raise_user_error('different_amount', {
                        'payment': payment.rec_name,
                        'difference': payment.difference,
                        })
            if payment.difference_move:
                moves.append(payment.difference_move)
            groups.add(payment.group)
        if moves:
            Move.post(moves)
        # Write state before processing
        cls.write(payments, {'state': 'done'})
        cls.process_invoices(payments)
        Group.process(list(groups))

    def get_difference_move(self, journal, date=None, description=None):
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
            account = journal.debit_account
        else:
            account = journal.credit_account
        move = Move()
        move.journal = journal
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
            ('invoice.currency', '=', self.currency.id),
            ('invoice.state', '=', 'posted'),
            ('payment_amount', '=', self.amount),
            ]

    def _get_invoice_line(self, skip_ids=None):
        'Returns the invoice line for the current payment'
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        if skip_ids is None:
            skip_ids = set()
        domain = self._invoice_line_search_domain()
        domain.append(('id', 'not in', skip_ids))
        lines = InvoiceLine.search(domain)
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
        'account.open_journal_ask_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Import', 'import_', 'tryton-ok', default=True),
            ])
    import_ = StateTransition()

    def get_payment(self, row):
        pool = Pool()
        Payment = pool.get('account.invoice.line.payment')
        date, amount, description = row
        payment = Payment()
        date_args = map(int, date.split('/'))
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
        reader = csv.reader(StringIO.StringIO(str(self.start.data)),
            dialect=dialect)
        reader.next()  # Skip header line
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
    'Creat Write-Off Move'
    __name__ = 'account.invoice.line.payment.write-off.start'
    journal = fields.Many2One('account.journal', 'Journal', required=True,
        domain=[
            ('type', '=', 'write-off'),
            ])
    date = fields.Date('Date', required=True)
    amount = fields.Numeric('Amount', digits=(16, Eval('currency_digits', 2)),
        readonly=True, depends=['currency_digits'])
    currency_digits = fields.Integer('Currency Digits', readonly=True)
    description = fields.Char('Description')


class CreateWriteOffMove(Wizard):
    'Creat Write-Off Move'
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
            }

    def get_payment(self):
        pool = Pool()
        Payment = pool.get('account.invoice.line.payment')
        return Payment(Transaction().context['active_id'])

    def transition_create_(self):
        pool = Pool()
        Payment = pool.get('account.invoice.line.payment')
        payment = self.get_payment()
        move = payment.get_difference_move(self.start.journal, self.start.date,
            self.start.description)
        move.save()
        payment.difference_move = move
        payment.save()
        Payment.done([payment])
        return 'end'
