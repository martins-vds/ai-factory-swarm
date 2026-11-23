package lib;

import jakarta.ws.rs.FormParam;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.time.LocalDate;
import java.util.stream.Collectors;

/** Holds as `;`-separated lines: id, member, isbn, placed on, expires on. */
@Path("holds")
@Produces(MediaType.TEXT_PLAIN)
public class HoldResource {
    static final int MAX_ACTIVE_HOLDS = 3;

    private final HoldRepository holds;
    private final LoanRepository loans;

    HoldResource(HoldRepository holds, LoanRepository loans) {
        this.holds = holds;
        this.loans = loans;
    }

    @GET
    public String list(@QueryParam("isbn") String isbn) {
        return holds.active(isbn, LocalDate.now()).stream().map(HoldResource::line)
                .collect(Collectors.joining("\n", "", "\n"));
    }

    @POST
    public Response place(@FormParam("member") String member, @FormParam("isbn") String isbn) {
        if (member == null || member.isBlank() || isbn == null || isbn.isBlank()) {
            return Response.status(400).entity("member and isbn are required\n").build();
        }
        LocalDate today = LocalDate.now();
        Loan out = loans.all().stream().filter(l -> l.getIsbn().equals(isbn) && l.getReturnedOn() == null)
                .findFirst().orElse(null);
        if (out == null) {
            return Response.status(409).entity("book is available\n").build();
        }
        if (out.getMember().equals(member)) {
            return Response.status(409).entity("member has this book\n").build();
        }
        if (holds.holding(member, isbn, today)) {
            return Response.status(409).entity("already on hold\n").build();
        }
        if (holds.activeFor(member, today) > MAX_ACTIVE_HOLDS) {
            return Response.status(409).entity("hold limit reached\n").build();
        }
        return Response.status(201).entity(line(holds.place(member, isbn, today)) + "\n").build();
    }

    @POST
    @Path("{id}/cancel")
    public Response cancel(@PathParam("id") String id) {
        Hold hold = holds.find(id).orElse(null);
        if (hold == null) {
            return Response.status(404).entity("no such hold\n").build();
        }
        if (hold.getCancelledOn() != null) {
            return Response.status(409).entity("hold already cancelled\n").build();
        }
        return Response.ok(line(holds.cancel(id, LocalDate.now()).orElseThrow()) + "\n").build();
    }

    static String line(Hold h) {
        return String.join(";", h.getId(), h.getMember(), h.getIsbn(), h.getPlacedOn().toString(),
                h.expiresOn().toString());
    }
}
