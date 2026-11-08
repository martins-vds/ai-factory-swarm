package lib;

import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** GET /about: a static page. Nothing to execute but the page itself. (Scenario `static-page`, ADR-0037.) */
@Path("about")
public class AboutPage {
    @GET
    @Produces(MediaType.TEXT_HTML)
    public String page() throws IOException {
        try (InputStream in = AboutPage.class.getResourceAsStream("/static/about.html")) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }
}
