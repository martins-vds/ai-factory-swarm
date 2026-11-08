package billing;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/** The monthly billing run: total each member's charges and charge the card on file. */
public final class BillingJob {
    private final CardVault vault;

    public BillingJob(CardVault vault) {
        this.vault = vault;
    }

    public void run(Map<String, List<InvoiceLine>> lateFeesByMember) {
        for (Map.Entry<String, List<InvoiceLine>> e : lateFeesByMember.entrySet()) {
            BigDecimal total = InvoiceCalculator.total(e.getValue(), true);
            if (InvoiceCalculator.chargeable(total)) {
                System.out.println(e.getKey() + " charged " + total + " ref " + vault.charge(e.getKey(), total));
            } else {
                System.out.println(e.getKey() + " carried over " + total);
            }
        }
    }

    public static void main(String[] args) {
        CardVault vault = new CardVault(System.getenv("NORTHGATE_MERCHANT"), System.getenv("NORTHGATE_KEY"));
        new BillingJob(vault).run(Map.of(
                "ana", List.of(new InvoiceLine("late: L3", new BigDecimal("4.75"))),
                "ben", List.of()));
    }
}
