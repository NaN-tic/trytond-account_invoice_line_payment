=============================
Invoice Line Payment Scenario
=============================

Imports::
    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from operator import attrgetter
    >>> from proteus import config, Model, Wizard
    >>> from trytond.tests.tools import activate_modules
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> from trytond.modules.account.tests.tools import create_fiscalyear, \
    ...     create_chart, get_accounts, create_tax
    >>> from trytond.modules.account_invoice.tests.tools import \
    ...     set_fiscalyear_invoice_sequences, create_payment_term
    >>> today = datetime.date.today()

Install account_invoice::

    >>> config = activate_modules('account_invoice_line_payment')

Create company::

    >>> _ = create_company()
    >>> company = get_company()

Create fiscal year::

    >>> fiscalyear = set_fiscalyear_invoice_sequences(
    ...     create_fiscalyear(company))
    >>> fiscalyear.click('create_period')
    >>> period = fiscalyear.periods[0]

Create chart of accounts::

    >>> _ = create_chart(company)
    >>> accounts = get_accounts(company)
    >>> revenue = accounts['revenue']
    >>> expense = accounts['expense']
    >>> receivable = accounts['receivable']
    >>> cash = accounts['cash']

Create tax::

    >>> tax = create_tax(Decimal('.10'))
    >>> tax.save()

Create customer::

    >>> Party = Model.get('party.party')
    >>> customer = Party(name='Customer')
    >>> customer.save()
    >>> customer2 = Party(name='Customer2')
    >>> customer2.save()

Create account category::

    >>> ProductCategory = Model.get('product.category')
    >>> account_category = ProductCategory(name="Account Category")
    >>> account_category.accounting = True
    >>> account_category.account_expense = expense
    >>> account_category.account_revenue = revenue
    >>> account_category.customer_taxes.append(tax)
    >>> account_category.save()

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
    >>> template.account_category = account_category
    >>> template.save()
    >>> product.template = template
    >>> product.save()

Create payment term::

    >>> payment_term = create_payment_term()
    >>> payment_term.save()

Create invoice::

    >>> Invoice = Model.get('account.invoice')
    >>> invoice = Invoice()
    >>> invoice.party = customer
    >>> invoice.payment_term = payment_term
    >>> line = invoice.lines.new()
    >>> line.party = customer
    >>> line.product = product
    >>> line.quantity = 5
    >>> line.unit_price = Decimal('40.0')
    >>> line = invoice.lines.new()
    >>> line.party = customer
    >>> line.product = product
    >>> line.quantity = 10
    >>> line.unit_price = Decimal('40.0')
    >>> invoice.untaxed_amount
    Decimal('600.00')
    >>> invoice.tax_amount
    Decimal('60.00')
    >>> invoice.total_amount
    Decimal('660.00')
    >>> invoice.click('post')
    >>> invoice.reload()
    >>> invoice.state
    'posted'
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
    'done'
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
    'done'

Check that the invoice is reconciled::

    >>> invoice.reload()
    >>> invoice.amount_to_pay == Decimal('0.0')
    True
    >>> invoice.state
    'paid'

Create invoice to be partialy reconciled::

    >>> invoice = Invoice()
    >>> invoice.party = customer
    >>> invoice.payment_term = payment_term
    >>> line = invoice.lines.new()
    >>> line.party = customer
    >>> line.product = product
    >>> line.quantity = 5
    >>> line.unit_price = Decimal('40.0')
    >>> invoice.untaxed_amount
    Decimal('200.00')
    >>> invoice.tax_amount
    Decimal('20.00')
    >>> invoice.total_amount
    Decimal('220.00')
    >>> invoice.click('post')
    >>> invoice.reload()
    >>> invoice.state
    'posted'
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

    >>> Sequence = Model.get('ir.sequence')
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
    ...     sequence=sequence_journal)
    >>> journal_writeoff.save()
    >>> WriteOff = Model.get('account.move.reconcile.write_off')
    >>> writeoff_method = WriteOff()
    >>> writeoff_method.name = 'Writeoff'
    >>> writeoff_method.journal = journal_writeoff
    >>> writeoff_method.credit_account = revenue
    >>> writeoff_method.debit_account = expense
    >>> writeoff_method.save()
    >>> writeoff = Wizard('account.invoice.line.payment.write-off',
    ...     [first_payment])
    >>> writeoff.form.amount
    Decimal('20.00')
    >>> writeoff.form.writeoff = writeoff_method
    >>> writeoff.form.description = 'Write off'
    >>> writeoff.execute('create_')
    >>> group.reload()
    >>> group.state
    'done'

Check that the invoice is reconciled::

    >>> invoice.reload()
    >>> invoice.state
    'paid'

Upgrade party lines when create or write an invoice::

    >>> invoice = Invoice()
    >>> invoice.party = customer
    >>> invoice.payment_term = payment_term
    >>> line = invoice.lines.new()
    >>> line.party = customer
    >>> line.product = product
    >>> line.quantity = 5
    >>> line.unit_price = Decimal('40.0')
    >>> invoice.save()
    >>> line, = invoice.lines
    >>> line.party == invoice.party
    True
    >>> invoice.party = customer2
    >>> invoice.save()
    >>> line, = invoice.lines
    >>> line.party == invoice.party
    True
