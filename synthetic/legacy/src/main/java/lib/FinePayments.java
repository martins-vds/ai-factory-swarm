package lib;

import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

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
@Path("payments")
public class FinePayments {
    private final LoanRepository loans;
    private final HttpClient http = HttpClient.newHttpClient();

    FinePayments(LoanRepository loans) {
        this.loans = loans;
    }

    @POST
    @Path("{id}")
    @Produces(MediaType.TEXT_PLAIN)
    public Response pay(@PathParam("id") String id) {
        if (loans.find(id).isEmpty()) {
            return Response.status(404).entity("no such loan\n").build();
        }
        String gateway = System.getenv().getOrDefault("PAYMENT_GATEWAY_URL", "https://payments.lending-library.invalid");
        try {
            HttpResponse<String> r = http.send(HttpRequest.newBuilder(URI.create(gateway + "/charge?loan=" + id))
                    .POST(HttpRequest.BodyPublishers.noBody()).build(), HttpResponse.BodyHandlers.ofString());
            return Response.status(r.statusCode() == 200 ? 200 : 502).entity(r.body()).build();
        } catch (IOException | InterruptedException e) {
            return Response.status(502).entity("payment gateway unavailable\n").build();
        }
    }
}
