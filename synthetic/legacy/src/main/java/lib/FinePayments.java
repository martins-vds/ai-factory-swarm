package lib;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

/**
 * POST /payments/{loanId}: charges the late fee through the library's payment gateway.
 *
 * The gateway (PAYMENT_GATEWAY_URL, default https://payments.lending-library.invalid) has no test
 * instance, so this part of the legacy app can't run outside production: it can be characterized only
 * partly. (Scenario `partial-runtime`, ADR-0037.)
 */
public final class FinePayments implements HttpHandler {
    private final LoanStore store;
    private final HttpClient http = HttpClient.newHttpClient();

    FinePayments(LoanStore store) {
        this.store = store;
    }

    @Override
    public void handle(HttpExchange ex) throws IOException {
        String id = ex.getRequestURI().getPath().replaceFirst("^/payments/?", "");
        if (store.find(id).isEmpty()) {
            App.send(ex, 404, "text/plain", "no such loan\n");
            return;
        }
        String gateway = System.getenv().getOrDefault("PAYMENT_GATEWAY_URL", "https://payments.lending-library.invalid");
        try {
            HttpResponse<String> r = http.send(HttpRequest.newBuilder(URI.create(gateway + "/charge?loan=" + id))
                    .POST(HttpRequest.BodyPublishers.noBody()).build(), HttpResponse.BodyHandlers.ofString());
            App.send(ex, r.statusCode() == 200 ? 200 : 502, "text/plain", r.body());
        } catch (IOException | InterruptedException e) {
            App.send(ex, 502, "text/plain", "payment gateway unavailable\n");
        }
    }
}
