package billing;

import java.math.BigDecimal;

/** One charge on a member's monthly invoice. */
public record InvoiceLine(String description, BigDecimal amount) {
    public InvoiceLine {
        if (amount.signum() < 0) {
            throw new IllegalArgumentException("negative charge: " + description);
        }
    }
}
