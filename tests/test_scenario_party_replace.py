import unittest
from decimal import Decimal

from proteus import Model, Wizard
from trytond.modules.account.tests.tools import (create_chart,
                                                 create_fiscalyear, create_tax,
                                                 create_tax_code, get_accounts)
from trytond.modules.account_invoice.tests.tools import \
    set_fiscalyear_invoice_sequences
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):

        # Install account_invoice_line_payment
        activate_modules('account_invoice_line_payment')

        # Create company
        _ = create_company()
        company = get_company()
        tax_identifier = company.party.identifiers.new()
        tax_identifier.type = 'eu_vat'
        tax_identifier.code = 'BE0897290877'
        company.party.save()

        # Create fiscal year
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company))
        fiscalyear.click('create_period')
        period = fiscalyear.periods[0]

        # Create chart of accounts
        _ = create_chart(company)
        accounts = get_accounts(company)
        receivable = accounts['receivable']
        account_cash = accounts['cash']

        # Create tax
        tax = create_tax(Decimal('.10'))
        tax.save()
        invoice_base_code = create_tax_code(tax, 'base', 'invoice')
        invoice_base_code.save()
        invoice_tax_code = create_tax_code(tax, 'tax', 'invoice')
        invoice_tax_code.save()
        credit_note_base_code = create_tax_code(tax, 'base', 'credit')
        credit_note_base_code.save()
        credit_note_tax_code = create_tax_code(tax, 'tax', 'credit')
        credit_note_tax_code.save()

        # Create party
        Party = Model.get('party.party')
        party = Party(name='Party')
        party.save()
        party2 = Party(name='Party')
        party2.save()

        # Create a Move for the reconciling the first line
        Journal = Model.get('account.journal')
        Move = Model.get('account.move')
        MoveLine = Model.get('account.move.line')
        journal_cash, = Journal.find([
            ('code', '=', 'CASH'),
        ])
        move = Move()
        move.period = period
        move.journal = journal_cash
        move.date = period.start_date
        line = move.lines.new()
        line.account = account_cash
        line.debit = Decimal(440)
        line = move.lines.new()
        line.account = receivable
        line.credit = Decimal(440)
        line.party = party
        move.save()
        move.click('post')
        customer_move, = MoveLine.find([
            ('move', '=', move.id),
            ('account', '=', receivable.id),
        ])

        # Create a payment group for the first line
        Group = Model.get('account.invoice.line.payment.group')
        group = Group()
        group.reference = '1'
        group.party = party
        group.kind = 'customer'
        group.move_line = customer_move
        group.save()

        # Try replace active party
        replace = Wizard('party.replace', models=[party])
        replace.form.source = party
        replace.form.destination = party2
        replace.execute('replace')

        # Check fields have been replaced
        group.reload()
        self.assertEqual(group.party, party2)
