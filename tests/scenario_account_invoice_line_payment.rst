=============================
Invoice Line Payment Scenario
=============================

Imports::
    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from operator import attrgetter
    >>> from proteus import config, Model, Wizard
    >>> today = datetime.date.today()

Create database::

    >>> config = config.set_trytond()
    >>> config.pool.test = True

Install account_invoice::

    >>> Module = Model.get('ir.module.module')
    >>> module, = Module.find(
    ...     [('name', '=', 'account_invoice_line_payment')])
    >>> module.click('install')
    >>> Wizard('ir.module.module.install_upgrade').execute('upgrade')

Create company::

    >>> Currency = Model.get('currency.currency')
    >>> CurrencyRate = Model.get('currency.currency.rate')
    >>> currencies = Currency.find([('code', '=', 'USD')])
    >>> if not currencies:
    ...     currency = Currency(name='US Dollar', symbol=u'$', code='USD',
    ...         rounding=Decimal('0.01'), mon_grouping='[]',
    ...         mon_decimal_point='.')
    ...     currency.save()
    ...     CurrencyRate(date=today + relativedelta(month=1, day=1),
    ...         rate=Decimal('1.0'), currency=currency).save()
    ... else:
    ...     currency, = currencies
    >>> Company = Model.get('company.company')
    >>> Party = Model.get('party.party')
    >>> company_config = Wizard('company.company.config')
    >>> company_config.execute('company')
    >>> company = company_config.form
    >>> party = Party(name='Dunder Mifflin')
    >>> party.save()
    >>> company.party = party
    >>> company.currency = currency
    >>> company_config.execute('add')
    >>> company, = Company.find([])

Reload the context::

    >>> User = Model.get('res.user')
    >>> config._context = User.get_preferences(True, config.context)

Create fiscal year::

    >>> FiscalYear = Model.get('account.fiscalyear')
    >>> Sequence = Model.get('ir.sequence')
    >>> SequenceStrict = Model.get('ir.sequence.strict')
    >>> fiscalyear = FiscalYear(name=str(today.year))
    >>> fiscalyear.start_date = today + relativedelta(month=1, day=1)
    >>> fiscalyear.end_date = today + relativedelta(month=12, day=31)
    >>> fiscalyear.company = company
    >>> post_move_seq = Sequence(name=str(today.year), code='account.move',
    ...     company=company)
    >>> post_move_seq.save()
    >>> fiscalyear.post_move_sequence = post_move_seq
    >>> invoice_seq = SequenceStrict(name=str(today.year),
    ...     code='account.invoice', company=company)
    >>> invoice_seq.save()
    >>> fiscalyear.out_invoice_sequence = invoice_seq
    >>> fiscalyear.in_invoice_sequence = invoice_seq
    >>> fiscalyear.out_credit_note_sequence = invoice_seq
    >>> fiscalyear.in_credit_note_sequence = invoice_seq
    >>> fiscalyear.save()
    >>> FiscalYear.create_period([fiscalyear.id], config.context)
    >>> period = fiscalyear.periods[0]

Create chart of accounts::

    >>> AccountTemplate = Model.get('account.account.template')
    >>> Account = Model.get('account.account')
    >>> account_template, = AccountTemplate.find([('parent', '=', None)])
    >>> create_chart = Wizard('account.create_chart')
    >>> create_chart.execute('account')
    >>> create_chart.form.account_template = account_template
    >>> create_chart.form.company = company
    >>> create_chart.execute('create_account')
    >>> receivable, = Account.find([
    ...         ('kind', '=', 'receivable'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> payable, = Account.find([
    ...         ('kind', '=', 'payable'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> revenue, = Account.find([
    ...         ('kind', '=', 'revenue'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> expense, = Account.find([
    ...         ('kind', '=', 'expense'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> cash, = Account.find([
    ...         ('kind', '=', 'other'),
    ...         ('company', '=', company.id),
    ...         ('name', '=', 'Main Cash'),
    ...         ])
    >>> account_tax, = Account.find([
    ...         ('kind', '=', 'other'),
    ...         ('company', '=', company.id),
    ...         ('name', '=', 'Main Tax'),
    ...         ])
    >>> create_chart.form.account_receivable = receivable
    >>> create_chart.form.account_payable = payable
    >>> create_chart.execute('create_properties')

Create tax::

    >>> TaxCode = Model.get('account.tax.code')
    >>> Tax = Model.get('account.tax')
    >>> tax = Tax()
    >>> tax.name = 'Tax'
    >>> tax.description = 'Tax'
    >>> tax.type = 'percentage'
    >>> tax.rate = Decimal('.10')
    >>> tax.invoice_account = account_tax
    >>> tax.credit_note_account = account_tax
    >>> invoice_base_code = TaxCode(name='invoice base')
    >>> invoice_base_code.save()
    >>> tax.invoice_base_code = invoice_base_code
    >>> invoice_tax_code = TaxCode(name='invoice tax')
    >>> invoice_tax_code.save()
    >>> tax.invoice_tax_code = invoice_tax_code
    >>> credit_note_base_code = TaxCode(name='credit note base')
    >>> credit_note_base_code.save()
    >>> tax.credit_note_base_code = credit_note_base_code
    >>> credit_note_tax_code = TaxCode(name='credit note tax')
    >>> credit_note_tax_code.save()
    >>> tax.credit_note_tax_code = credit_note_tax_code
    >>> tax.save()

Create customer::

    >>> Party = Model.get('party.party')
    >>> customer = Party(name='Customer')
    >>> customer.save()

Create product::

    >>> ProductUom = Model.get('product.uom')
    >>> unit, = ProductUom.find([('name', '=', 'Unit')])
    >>> ProductTemplate = Model.get('product.template')
    >>> Product = Model.get('product.product')
    >>> product = Product()
    >>> template = ProductTemplate()
    >>> template.name = 'product'
    >>> template.default_uom = unit
    >>> template.type = 'service'
    >>> template.list_price = Decimal('40')
    >>> template.cost_price = Decimal('25')
    >>> template.account_expense = expense
    >>> template.account_revenue = revenue
    >>> template.customer_taxes.append(tax)
    >>> template.save()
    >>> product.template = template
    >>> product.save()

Create payment term::

    >>> PaymentTerm = Model.get('account.invoice.payment_term')
    >>> PaymentTermLine = Model.get('account.invoice.payment_term.line')
    >>> payment_term = PaymentTerm(name='Term')
    >>> payment_term_line = PaymentTermLine(type='percent', days=20,
    ...     percentage=Decimal(50))
    >>> payment_term.lines.append(payment_term_line)
    >>> payment_term_line = PaymentTermLine(type='remainder', days=40)
    >>> payment_term.lines.append(payment_term_line)
    >>> payment_term.save()

Create invoice::

    >>> Invoice = Model.get('account.invoice')
    >>> invoice = Invoice()
    >>> invoice.party = customer
    >>> invoice.payment_term = payment_term
    >>> line = invoice.lines.new()
    >>> line.product = product
    >>> line.quantity = 5
    >>> line = invoice.lines.new()
    >>> line.product = product
    >>> line.quantity = 10
    >>> invoice.untaxed_amount
    Decimal('600.00')
    >>> invoice.tax_amount
    Decimal('60.00')
    >>> invoice.total_amount
    Decimal('660.00')
    >>> invoice.click('post')
    >>> invoice.reload()
    >>> invoice.state
    u'posted'
    >>> first_line, second_line = invoice.lines
    >>> first_line.payment_amount
    Decimal('220.00')

Create a Move for the reconciling the first line::

    >>> Journal = Model.get('account.journal')
    >>> Move = Model.get('account.move')
    >>> MoveLine = Model.get('account.move.line')
    >>> journal_cash, = Journal.find([
    ...         ('code', '=', 'CASH'),
    ...         ])
    >>> move = Move()
    >>> move.period = period
    >>> move.journal = journal_cash
    >>> move.date = period.start_date
    >>> line = move.lines.new()
    >>> line.account = cash
    >>> line.debit = Decimal(440)
    >>> line = move.lines.new()
    >>> line.account = receivable
    >>> line.credit = Decimal(440)
    >>> line.party = customer
    >>> move.save()
    >>> move.click('post')
    >>> customer_move, = MoveLine.find([
    ...         ('move', '=', move.id),
    ...         ('account', '=', receivable.id),
    ...         ])

Create a payment group for the first line::

    >>> Group = Model.get('account.invoice.line.payment.group')
    >>> group = Group()
    >>> group.reference = '1'
    >>> group.party = customer
    >>> group.kind = 'customer'
    >>> group.move_line = customer_move
    >>> group.save()


Create a payment for the first line::

    >>> payment = group.payments.new()
    >>> payment.amount = Decimal(440)
    >>> payment.line = second_line
    >>> group.save()
    >>> payment, = group.payments
    >>> payment.click('done')
    >>> group.reload()
    >>> group.state
    u'done'
    >>> second_line.reload()
    >>> second_line.payment_amount
    Decimal('0.00')
    >>> invoice.reload()
    >>> invoice.amount_to_pay
    Decimal('220.00')

Create a Move for the reconciling the second line::

    >>> move = Move()
    >>> move.period = period
    >>> move.journal = journal_cash
    >>> move.date = period.start_date
    >>> line = move.lines.new()
    >>> line.account = cash
    >>> line.debit = Decimal(220)
    >>> line = move.lines.new()
    >>> line.account = receivable
    >>> line.credit = Decimal(220)
    >>> line.party = customer
    >>> move.save()
    >>> move.click('post')
    >>> customer_move, = MoveLine.find([
    ...         ('move', '=', move.id),
    ...         ('account', '=', receivable.id),
    ...         ])

Create a payment group for the remaining line::

    >>> group = Group()
    >>> group.reference = '2'
    >>> group.party = customer
    >>> group.kind = 'customer'
    >>> group.move_line = customer_move
    >>> first_payment = group.payments.new()
    >>> first_payment.amount = Decimal(120)
    >>> first_payment.line = first_line
    >>> second_payment = group.payments.new()
    >>> second_payment.amount = Decimal(100)
    >>> group.save()
    >>> first_payment, second_payment = group.payments
    >>> first_line.payment_amount
    Decimal('220.00')
    >>> first_payment.click('done')
    >>> first_line.reload()
    >>> first_line.payment_amount
    Decimal('100.00')
    >>> second_payment.line = first_line
    >>> second_payment.click('done')
    >>> group.reload()
    >>> group.state
    u'done'


Check that the invoice is reconciled::

    >>> invoice.reload()
    >>> invoice.amount_to_pay
    Decimal('0.0')
    >>> invoice.reconciled
    True
    >>> invoice.state
    u'paid'

Create invoice to be partialy reconciled::

    >>> invoice = Invoice()
    >>> invoice.party = customer
    >>> invoice.payment_term = payment_term
    >>> line = invoice.lines.new()
    >>> line.product = product
    >>> line.quantity = 5
    >>> invoice.untaxed_amount
    Decimal('200.00')
    >>> invoice.tax_amount
    Decimal('20.00')
    >>> invoice.total_amount
    Decimal('220.00')
    >>> invoice.click('post')
    >>> invoice.reload()
    >>> invoice.state
    u'posted'
    >>> first_line, = invoice.lines

Create a Move for the reconciling the first line::

    >>> move = Move()
    >>> move.period = period
    >>> move.journal = journal_cash
    >>> move.date = period.start_date
    >>> line = move.lines.new()
    >>> line.account = cash
    >>> line.debit = Decimal(200)
    >>> line = move.lines.new()
    >>> line.account = receivable
    >>> line.credit = Decimal(200)
    >>> line.party = customer
    >>> move.save()
    >>> move.click('post')
    >>> customer_move, = MoveLine.find([
    ...         ('move', '=', move.id),
    ...         ('account', '=', receivable.id),
    ...         ])


Create a payment group for reconciling with write-off::

    >>> group = Group()
    >>> group.reference = '3'
    >>> group.party = customer
    >>> group.kind = 'customer'
    >>> group.move_line = customer_move
    >>> first_payment = group.payments.new()
    >>> first_payment.amount = Decimal(200)
    >>> first_payment.line = first_line
    >>> group.click('confirm')
    >>> first_payment, = group.payments
    >>> sequence_journal, = Sequence.find([('code', '=', 'account.journal')])
    >>> journal_writeoff = Journal(name='Write-Off', type='write-off',
    ...     sequence=sequence_journal,
    ...     credit_account=revenue, debit_account=expense)
    >>> journal_writeoff.save()
    >>> writeoff = Wizard('account.invoice.line.payment.write-off',
    ...     [first_payment])
    >>> writeoff.form.amount
    Decimal('20.00')
    >>> writeoff.form.journal = journal_writeoff
    >>> writeoff.form.description = 'Write off'
    >>> writeoff.execute('create_')
    >>> group.reload()
    >>> group.state
    u'done'


Check that the invoice is reconciled::

    >>> invoice.reload()
    >>> invoice.reconciled
    True
    >>> invoice.state
    u'paid'
