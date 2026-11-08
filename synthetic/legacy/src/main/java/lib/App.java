package lib;

import jakarta.persistence.EntityManagerFactory;
import jakarta.persistence.Persistence;
import org.glassfish.grizzly.http.server.HttpServer;
import org.glassfish.jersey.grizzly2.httpserver.GrizzlyHttpServerFactory;
import org.glassfish.jersey.server.ResourceConfig;

import java.net.URI;

/** The Lending Library: loans, late fees, fine payments, an about page. JAX-RS on Grizzly, JPA on H2. */
public final class App {
    public static void main(String[] args) throws Exception {
        String port = System.getenv().getOrDefault("PORT", "8080");
        EntityManagerFactory emf = Persistence.createEntityManagerFactory("library");
        LoanRepository loans = new LoanRepository(emf);
        ResourceConfig config = new ResourceConfig()
                .register(new LoanResource(loans))
                .register(new LateFeeView(loans))
                .register(new FinePayments(loans))
                .register(new AboutPage());
        HttpServer server = GrizzlyHttpServerFactory.createHttpServer(URI.create("http://0.0.0.0:" + port + "/"), config);
        System.out.println("Lending Library listening on " + port);
        Runtime.getRuntime().addShutdownHook(new Thread(() -> { server.shutdownNow(); emf.close(); }));
        Thread.currentThread().join();
    }
}
