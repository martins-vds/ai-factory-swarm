package billing;

import com.northgate.vault.ChargeResult;
import com.northgate.vault.VaultClient;
import com.northgate.vault.VaultCredentials;
import java.math.BigDecimal;

/** Charges the card the member keeps on file with Northgate. */
public final class CardVault {
    private final VaultClient client;

    public CardVault(String merchantId, String apiKey) {
        this.client = VaultClient.connect(new VaultCredentials(merchantId, apiKey));
    }

    public String charge(String memberId, BigDecimal amount) {
        ChargeResult result = client.charge(memberId, amount.movePointRight(2).longValueExact(), "USD");
        if (!result.approved()) {
            throw new IllegalStateException("card declined for " + memberId + ": " + result.reason());
        }
        return result.reference();
    }
}
