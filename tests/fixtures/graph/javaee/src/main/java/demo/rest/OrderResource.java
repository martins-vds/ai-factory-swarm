package demo.rest;

import demo.jms.Events;
import javax.inject.Inject;
import javax.ws.rs.POST;
import javax.ws.rs.Path;

@Path("/orders")
public class OrderResource {
    @Inject
    private Events events;

    @POST
    @Path("/report")
    public void report() {
    }
}
