"""Regression tests for NRS tax totals and legal monetary totals.

These cover the USD invoice that was sent to NRS with NGN tax amounts, the
VAT/withholding sign merge, multi-rate aggregation, zero-rated supply and
credit notes. They run against the builder's pure helpers with a fake frappe
module, so no site or database is required.
"""

import sys
import types
import unittest


try:
    from theoskaris_einvoice.payload import builder
except ModuleNotFoundError:  # pragma: no cover - only when frappe is absent
    _frappe = types.ModuleType("frappe")
    _utils = types.ModuleType("frappe.utils")
    _utils.flt = lambda value=0, precision=None: value
    _utils.get_datetime = lambda value: value
    _frappe.utils = _utils
    sys.modules["frappe"] = _frappe
    sys.modules["frappe.utils"] = _utils
    from theoskaris_einvoice.payload import builder


class TaxValidationError(Exception):
    """Raised by the fake frappe.throw in these tests."""


class FakeFrappe:
    def _(self, message):
        return message

    def throw(self, message, title=None):
        raise TaxValidationError(str(message))


class FakeDoc:
    """Minimal Frappe Document stand-in with attribute and get() access."""

    def __init__(self, values=None, **kwargs):
        self._values = dict(values or {})
        self._values.update(kwargs)
        for key, value in self._values.items():
            setattr(self, key, value)

    def get(self, key, default=None):
        if key in self._values:
            return self._values[key]
        return getattr(self, key, default)


def flt(value, precision=None):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        value = 0.0
    if precision is None:
        return value
    return round(value + 1e-9, precision)


def make_tax(
    description="",
    rate=0.0,
    amount=0.0,
    base_amount=0.0,
    net_amount=0.0,
    category="",
    add_deduct_tax=None,
    included_in_print_rate=0,
    tax_category="Total",
    account_head="",
):
    return FakeDoc(
        description=description,
        account_head=account_head,
        rate=rate,
        tax_amount=amount,
        tax_amount_after_discount_amount=amount,
        base_tax_amount=base_amount,
        net_amount=net_amount,
        custom_nrs_tax_category=category,
        add_deduct_tax=add_deduct_tax,
        included_in_print_rate=included_in_print_rate,
        category=tax_category,
    )


def make_invoice(
    net_total,
    grand_total,
    taxes,
    is_return=False,
    currency="USD",
    name="SINV-TEST",
):
    return FakeDoc(
        name=name,
        doctype="Sales Invoice",
        net_total=net_total,
        grand_total=grand_total,
        taxes=taxes,
        is_return=is_return,
        currency=currency,
        base_grand_total=grand_total,
    )


class TaxTotalTest(unittest.TestCase):
    def setUp(self):
        self._frappe = builder.frappe
        self._flt = builder.flt
        self._template = builder._get_template_tax_category
        builder.frappe = FakeFrappe()
        builder.flt = flt
        self.template_category = ""
        builder._get_template_tax_category = lambda inv: self.template_category
        self.addCleanup(self._restore)

    def _restore(self):
        builder.frappe = self._frappe
        builder.flt = self._flt
        builder._get_template_tax_category = self._template

    @staticmethod
    def _subtotals(tax_total):
        result = {}
        for total in tax_total:
            for sub in total["tax_subtotal"]:
                result[sub["tax_category"]["id"]] = sub
        return result

    @staticmethod
    def _subtotals_by_rate(tax_total):
        result = {}
        for total in tax_total:
            for sub in total["tax_subtotal"]:
                key = (sub["tax_category"]["id"], sub["tax_category_percent"])
                result[key] = sub
        return result

    def test_usd_vat_and_withholding_use_document_currency(self):
        # SINV-00556: net 122,216.10 USD, VAT +9,166.21, VAT withheld -9,166.21.
        # Company-currency base amounts are ~12,478,322.82 NGN each.
        vat = make_tax(
            description="VAT 7.5%",
            rate=7.5,
            amount=9166.21,
            base_amount=12478322.82,
            net_amount=122216.10,
            category="STANDARD_VAT",
        )
        wht = make_tax(
            description="VAT Withheld/Receivable NGN",
            rate=-7.5,
            amount=-9166.21,
            base_amount=-12478322.82,
            net_amount=122216.10,
            category="WITHHOLDING_TAX",
        )
        inv = make_invoice(122216.10, 122216.10, [vat, wht], currency="USD")

        result = builder._build_tax_total(inv)
        by_category = self._subtotals(result)

        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(by_category["STANDARD_VAT"]["tax_amount"], 9166.21, places=2)
        self.assertAlmostEqual(by_category["STANDARD_VAT"]["taxable_amount"], 122216.10, places=2)
        self.assertAlmostEqual(by_category["WITHHOLDING_TAX"]["tax_amount"], -9166.21, places=2)
        self.assertAlmostEqual(by_category["WITHHOLDING_TAX"]["taxable_amount"], 122216.10, places=2)
        self.assertAlmostEqual(sum(t["tax_amount"] for t in result), 0.0, places=2)

        # The NGN base amounts must never leak into a USD payload.
        for total in result:
            self.assertLess(abs(total["tax_amount"]), 1_000_000)

        legal = builder._build_legal_monetary_total(inv, result)
        self.assertAlmostEqual(legal["line_extension_amount"], 122216.10, places=2)
        self.assertAlmostEqual(legal["tax_exclusive_amount"], 122216.10, places=2)
        self.assertAlmostEqual(legal["tax_inclusive_amount"], 122216.10, places=2)
        self.assertAlmostEqual(legal["payable_amount"], 122216.10, places=2)

    def test_template_category_does_not_absorb_a_withholding_row(self):
        # The template says STANDARD_VAT; the negative row's wording is the
        # only signal that it is withholding. It must not be merged into VAT.
        self.template_category = "STANDARD_VAT"
        vat = make_tax(
            description="VAT 7.5%",
            rate=7.5,
            amount=9166.21,
            net_amount=122216.10,
        )
        wht = make_tax(
            description="VAT Withheld/Receivable NGN",
            rate=-7.5,
            amount=-9166.21,
            net_amount=122216.10,
        )
        inv = make_invoice(122216.10, 122216.10, [vat, wht], currency="USD")

        by_category = self._subtotals(builder._build_tax_total(inv))

        self.assertEqual(set(by_category), {"STANDARD_VAT", "WITHHOLDING_TAX"})
        self.assertAlmostEqual(by_category["STANDARD_VAT"]["tax_amount"], 9166.21, places=2)
        self.assertAlmostEqual(by_category["WITHHOLDING_TAX"]["tax_amount"], -9166.21, places=2)

    def test_ordinary_ngn_invoice_reconciles(self):
        self.template_category = "STANDARD_VAT"
        vat = make_tax(
            description="VAT 7.5%",
            rate=7.5,
            amount=15000.0,
            net_amount=200000.0,
        )
        inv = make_invoice(200000.0, 215000.0, [vat], currency="NGN")

        result = builder._build_tax_total(inv)
        legal = builder._build_legal_monetary_total(inv, result)

        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["tax_amount"], 15000.0, places=2)
        self.assertAlmostEqual(result[0]["tax_subtotal"][0]["taxable_amount"], 200000.0, places=2)
        self.assertAlmostEqual(legal["line_extension_amount"], 200000.0, places=2)
        self.assertAlmostEqual(legal["tax_inclusive_amount"], 215000.0, places=2)
        self.assertAlmostEqual(legal["payable_amount"], 215000.0, places=2)

    def test_distinct_rates_use_each_rows_own_base(self):
        # Both rows apply to the same 100,000 net. A cumulative total would
        # give the second row a 107,500 base and overstate the tax.
        self.template_category = "STANDARD_VAT"
        first = make_tax(description="VAT 7.5%", rate=7.5, amount=7500.0, net_amount=100000.0)
        second = make_tax(description="VAT 5%", rate=5.0, amount=5000.0, net_amount=100000.0)
        inv = make_invoice(100000.0, 112500.0, [first, second], currency="NGN")

        result = builder._build_tax_total(inv)
        by_rate = self._subtotals_by_rate(result)
        legal = builder._build_legal_monetary_total(inv, result)

        self.assertEqual(set(by_rate), {("STANDARD_VAT", 7.5), ("STANDARD_VAT", 5.0)})
        for sub in by_rate.values():
            self.assertAlmostEqual(sub["taxable_amount"], 100000.0, places=2)
        self.assertAlmostEqual(legal["tax_inclusive_amount"], 112500.0, places=2)
        self.assertAlmostEqual(legal["payable_amount"], 112500.0, places=2)

    def test_zero_rated_and_exempt_rows_keep_a_subtotal(self):
        for category in ("ZERO_VAT", "EXEMPTED"):
            with self.subTest(category=category):
                row = make_tax(
                    description=category,
                    rate=0.0,
                    amount=0.0,
                    net_amount=50000.0,
                    category=category,
                )
                inv = make_invoice(50000.0, 50000.0, [row], currency="NGN")

                result = builder._build_tax_total(inv)
                legal = builder._build_legal_monetary_total(inv, result)

                self.assertEqual(len(result), 1)
                sub = result[0]["tax_subtotal"][0]
                self.assertEqual(sub["tax_category"]["id"], category)
                self.assertAlmostEqual(sub["taxable_amount"], 50000.0, places=2)
                self.assertAlmostEqual(sub["tax_amount"], 0.0, places=2)
                self.assertAlmostEqual(legal["payable_amount"], 50000.0, places=2)

    def test_legacy_exempt_value_is_normalized(self):
        row = make_tax(
            description="Exempt supply",
            rate=0.0,
            amount=0.0,
            net_amount=50000.0,
            category="EXEMPT",
        )
        inv = make_invoice(50000.0, 50000.0, [row], currency="NGN")

        result = builder._build_tax_total(inv)

        self.assertEqual(result[0]["tax_subtotal"][0]["tax_category"]["id"], "EXEMPTED")

    def test_credit_note_is_sent_as_positive_magnitudes(self):
        vat = make_tax(
            description="VAT 7.5%",
            rate=7.5,
            amount=-7500.0,
            net_amount=-100000.0,
            category="STANDARD_VAT",
        )
        inv = make_invoice(-100000.0, -107500.0, [vat], is_return=True, currency="NGN")

        result = builder._build_tax_total(inv)
        legal = builder._build_legal_monetary_total(inv, result)

        self.assertAlmostEqual(result[0]["tax_amount"], 7500.0, places=2)
        self.assertAlmostEqual(result[0]["tax_subtotal"][0]["taxable_amount"], 100000.0, places=2)
        self.assertAlmostEqual(legal["line_extension_amount"], 100000.0, places=2)
        self.assertAlmostEqual(legal["tax_inclusive_amount"], 107500.0, places=2)
        self.assertAlmostEqual(legal["payable_amount"], 107500.0, places=2)

    def test_unsupported_deduction_fails_with_actionable_message(self):
        self.template_category = "STANDARD_VAT"
        row = make_tax(
            description="Discount adjustment",
            rate=-7.5,
            amount=-9166.21,
            net_amount=122216.10,
        )
        inv = make_invoice(122216.10, 122216.10, [row], currency="USD")

        with self.assertRaises(TaxValidationError) as ctx:
            builder._build_tax_total(inv)

        message = str(ctx.exception)
        self.assertIn("WITHHOLDING_TAX", message)
        self.assertIn("reduces the invoice total", message)

    def test_explicit_wrong_category_on_deduction_is_rejected(self):
        row = make_tax(
            description="VAT withheld",
            rate=-7.5,
            amount=-9166.21,
            net_amount=122216.10,
            category="STANDARD_VAT",
        )
        inv = make_invoice(122216.10, 122216.10, [row], currency="USD")

        with self.assertRaises(TaxValidationError) as ctx:
            builder._build_tax_total(inv)

        self.assertIn("STANDARD_VAT", str(ctx.exception))
        self.assertIn("WITHHOLDING_TAX", str(ctx.exception))

    def test_unknown_category_is_rejected_with_supported_codes(self):
        row = make_tax(
            description="VAT 7.5%",
            rate=7.5,
            amount=7500.0,
            net_amount=100000.0,
            category="BOGUS_TAX",
        )
        inv = make_invoice(100000.0, 107500.0, [row], currency="NGN")

        with self.assertRaises(TaxValidationError) as ctx:
            builder._build_tax_total(inv)

        message = str(ctx.exception)
        self.assertIn("BOGUS_TAX", message)
        self.assertIn("STANDARD_VAT", message)

    def test_positive_withholding_is_rejected(self):
        row = make_tax(
            description="Withholding tax",
            rate=7.5,
            amount=7500.0,
            net_amount=100000.0,
            category="WITHHOLDING_TAX",
        )
        inv = make_invoice(100000.0, 107500.0, [row], currency="NGN")

        with self.assertRaises(TaxValidationError) as ctx:
            builder._build_tax_total(inv)

        self.assertIn("increases the invoice total", str(ctx.exception))

    def test_tax_inclusive_row_is_rejected(self):
        row = make_tax(
            description="VAT 7.5%",
            rate=7.5,
            amount=7500.0,
            net_amount=100000.0,
            category="STANDARD_VAT",
            included_in_print_rate=1,
        )
        inv = make_invoice(100000.0, 100000.0, [row], currency="NGN")

        with self.assertRaises(TaxValidationError) as ctx:
            builder._build_tax_total(inv)

        self.assertIn("included in Basic Rate", str(ctx.exception))

    def test_unreconciled_totals_are_rejected(self):
        self.template_category = "STANDARD_VAT"
        row = make_tax(description="VAT 7.5%", rate=7.5, amount=7500.0, net_amount=100000.0)
        inv = make_invoice(100000.0, 120000.0, [row], currency="NGN")
        result = builder._build_tax_total(inv)

        with self.assertRaises(TaxValidationError) as ctx:
            builder._build_legal_monetary_total(inv, result)

        self.assertIn("do not reconcile", str(ctx.exception))

    def test_invoice_without_taxes_has_no_tax_total(self):
        inv = make_invoice(100000.0, 100000.0, [], currency="NGN")

        result = builder._build_tax_total(inv)
        legal = builder._build_legal_monetary_total(inv, result)

        self.assertEqual(result, [])
        self.assertAlmostEqual(legal["payable_amount"], 100000.0, places=2)


if __name__ == "__main__":
    unittest.main()
