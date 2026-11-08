package lib;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/** The Lending Library: loans, late fees, fine payments, an about page. Standard library only. */
public final class App {
    public static void main(String[] args) throws IOException {
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8080"));
        LoanStore store = new LoanStore();
        HttpServer server = HttpServer.create(new InetSocketAddress(port), 0);
        server.createContext("/loans", new LoanResource(store));
        server.createContext("/fees", new LateFeeView(store));
        server.createContext("/payments", new FinePayments(store));
        server.createContext("/about", ex -> send(ex, 200, "text/html",
                Files.readString(Path.of("src/main/resources/static/about.html"))));
        server.start();
        System.out.println("Lending Library listening on " + port);
    }

    static void send(HttpExchange ex, int status, String type, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", type + "; charset=utf-8");
        ex.sendResponseHeaders(status, bytes.length);
        try (OutputStream out = ex.getResponseBody()) {
            out.write(bytes);
        }
    }
}
