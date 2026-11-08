package lib;

import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.time.LocalDate;
import java.time.temporal.ChronoUnit;

/** GET /fees/{loanId}: an HTML page with the loan's late fee (25 cents per day late, capped at 10 dollars,
 * waived for returns at most 2 days late). */
@Path("fees")
public class LateFeeView {
    private final LoanRepository loans;

    LateFeeView(LoanRepository loans) {
        this.loans = loans;
    }

    @GET
    @Path("{id}")
    @Produces(MediaType.TEXT_HTML)
    public Response page(@PathParam("id") String id) {
        var found = loans.find(id);
        if (found.isEmpty()) {
            return Response.status(404).entity("<p>No such loan.</p>").build();
        }
        Loan loan = found.get();
        LocalDate end = loan.getReturnedOn() == null ? LocalDate.now() : loan.getReturnedOn();
        long late = Math.max(0, ChronoUnit.DAYS.between(loan.dueOn(), end));
        long cents = late <= 2 ? 0 : Math.min(1000, late * 25);
        return Response.ok("<h1>Late fee for " + loan.getId() + "</h1>"
                + "<p>Due " + loan.dueOn() + ", " + late + " day(s) late.</p>"
                + "<p class=\"fee\">Fee: $" + (cents / 100) + "." + String.format("%02d", cents % 100) + "</p>").build();
    }
}
