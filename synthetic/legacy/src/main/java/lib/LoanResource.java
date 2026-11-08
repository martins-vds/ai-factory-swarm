package lib;

import jakarta.ws.rs.FormParam;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.time.LocalDate;
import java.util.stream.Collectors;

/** Loans as `;`-separated lines: id, member, isbn, lent on, due on, returned on. */
@Path("loans")
@Produces(MediaType.TEXT_PLAIN)
public class LoanResource {
    private final LoanRepository loans;

    LoanResource(LoanRepository loans) {
        this.loans = loans;
    }

    @GET
    public String list() {
        return loans.all().stream().map(LoanResource::line).collect(Collectors.joining("\n", "", "\n"));
    }

    @GET
    @Path("{id}")
    public Response one(@PathParam("id") String id) {
        return loans.find(id).map(l -> Response.ok(line(l) + "\n").build())
                .orElse(Response.status(404).entity("no such loan\n").build());
    }

    @POST
    public Response lend(@FormParam("member") String member, @FormParam("isbn") String isbn) {
        if (member == null || isbn == null) {
            return Response.status(400).entity("member and isbn are required\n").build();
        }
        return Response.status(201).entity(line(loans.lend(member, isbn, LocalDate.now())) + "\n").build();
    }

    @POST
    @Path("{id}/return")
    public Response giveBack(@PathParam("id") String id) {
        return loans.markReturned(id, LocalDate.now()).map(l -> Response.ok(line(l) + "\n").build())
                .orElse(Response.status(404).entity("no such loan\n").build());
    }

    static String line(Loan l) {
        return String.join(";", l.getId(), l.getMember(), l.getIsbn(), l.getLentOn().toString(), l.dueOn().toString(),
                l.getReturnedOn() == null ? "" : l.getReturnedOn().toString());
    }
}
