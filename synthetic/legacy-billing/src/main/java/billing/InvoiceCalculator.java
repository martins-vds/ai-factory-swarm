package billing;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;

/** Totals a member's monthly charges. */
public final class InvoiceCalculator {
    static final BigDecimal MONTHLY_FEE = new BigDecimal("3.00");
    static final BigDecimal TAX_RATE = new BigDecimal("0.05");
    static final BigDecimal FEE_CAP = new BigDecimal("25.00");

    private InvoiceCalculator() {
    }

    /** Late fees are capped per month; the membership fee is not. Tax is rounded half-up, once, on the total. */
    public static BigDecimal total(List<InvoiceLine> lateFees, boolean member) {
        BigDecimal fees = lateFees.stream().map(InvoiceLine::amount).reduce(BigDecimal.ZERO, BigDecimal::add);
        if (fees.compareTo(FEE_CAP) > 0) {
            fees = FEE_CAP;
        }
        BigDecimal subtotal = member ? fees.add(MONTHLY_FEE) : fees;
        BigDecimal tax = subtotal.multiply(TAX_RATE).setScale(2, RoundingMode.HALF_UP);
        return subtotal.add(tax).setScale(2, RoundingMode.HALF_UP);
    }

    /** Nothing is charged under a dollar; it carries over to next month. */
    public static boolean chargeable(BigDecimal total) {
        return total.compareTo(BigDecimal.ONE) >= 0;
    }
}
