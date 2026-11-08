package lib;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;

import java.io.IOException;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;

/**
 * GET /fees/{loanId}: an HTML page with the loan's late fee.
 *
 * The fee rule lives here, in the page that renders it: 25 cents per day late, capped at 10 dollars,
 * waived for returns at most 2 days late. (Scenario `misplaced-rule`, ADR-0037.)
 */
public final class LateFeeView implements HttpHandler {
    private final LoanStore store;

    LateFeeView(LoanStore store) {
        this.store = store;
    }

    @Override
    public void handle(HttpExchange ex) throws IOException {
        String id = ex.getRequestURI().getPath().replaceFirst("^/fees/?", "");
        var found = store.find(id);
        if (found.isEmpty()) {
            App.send(ex, 404, "text/html", "<p>No such loan.</p>");
            return;
        }
        Loan loan = found.get();
        LocalDate end = loan.returnedOn() == null ? LocalDate.now() : loan.returnedOn();
        long late = Math.max(0, ChronoUnit.DAYS.between(loan.dueOn(), end));
        long cents = late <= 2 ? 0 : Math.min(1000, late * 25);
        String html = "<h1>Late fee for " + loan.id() + "</h1>"
                + "<p>Due " + loan.dueOn() + ", " + late + " day(s) late.</p>"
                + "<p class=\"fee\">Fee: $" + (cents / 100) + "." + String.format("%02d", cents % 100) + "</p>";
        App.send(ex, 200, "text/html", html);
    }
}
