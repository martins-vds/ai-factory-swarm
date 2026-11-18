package billing;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.math.BigDecimal;
import java.util.List;
import org.junit.Test;

public class InvoiceCalculatorTest {
    private static InvoiceLine fee(String amount) {
        return new InvoiceLine("late", new BigDecimal(amount));
    }

    @Test
    public void memberWithOneLateFee() {
        assertEquals(new BigDecimal("8.14"), InvoiceCalculator.total(List.of(fee("4.75")), true));
    }

    @Test
    public void lateFeesAreCappedButTheMonthlyFeeIsNot() {
        assertEquals(new BigDecimal("29.40"),
                InvoiceCalculator.total(List.of(fee("20.00"), fee("12.50")), true));
    }

    @Test
    public void nonMemberPaysOnlyFees() {
        assertEquals(new BigDecimal("2.10"), InvoiceCalculator.total(List.of(fee("2.00")), false));
    }

    @Test
    public void taxRoundsHalfUpOnce() {
        assertEquals(new BigDecimal("0.53"), InvoiceCalculator.total(List.of(fee("0.50")), false));
    }

    @Test
    public void underADollarCarriesOver() {
        assertFalse(InvoiceCalculator.chargeable(new BigDecimal("0.99")));
        assertTrue(InvoiceCalculator.chargeable(new BigDecimal("1.00")));
    }

    @Test(expected = IllegalArgumentException.class)
    public void negativeChargesAreRejected() {
        fee("-1.00");
    }
}
