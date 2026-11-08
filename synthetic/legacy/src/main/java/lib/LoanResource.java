package lib;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;

import java.io.IOException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;

/**
 * GET /loans -> all loans as CSV-ish lines; GET /loans/{id}; POST /loans (member, isbn) lends today;
 * POST /loans/{id}/return returns it today.
 */
public final class LoanResource implements HttpHandler {
    private final LoanStore store;

    LoanResource(LoanStore store) {
        this.store = store;
    }

    @Override
    public void handle(HttpExchange ex) throws IOException {
        String[] parts = ex.getRequestURI().getPath().split("/");
        String method = ex.getRequestMethod();
        if (parts.length == 2 && method.equals("GET")) {
            StringBuilder out = new StringBuilder();
            for (Loan l : store.all()) {
                out.append(line(l)).append('\n');
            }
            App.send(ex, 200, "text/plain", out.toString());
        } else if (parts.length == 2 && method.equals("POST")) {
            Map<String, String> form = form(new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            if (!form.containsKey("member") || !form.containsKey("isbn")) {
                App.send(ex, 400, "text/plain", "member and isbn are required\n");
                return;
            }
            Loan l = store.lend(form.get("member"), form.get("isbn"), LocalDate.now());
            App.send(ex, 201, "text/plain", line(l) + "\n");
        } else if (parts.length == 3 && method.equals("GET")) {
            var found = store.find(parts[2]);
            if (found.isPresent()) {
                App.send(ex, 200, "text/plain", line(found.get()) + "\n");
            } else {
                App.send(ex, 404, "text/plain", "no such loan\n");
            }
        } else if (parts.length == 4 && parts[3].equals("return") && method.equals("POST")) {
            var found = store.find(parts[2]);
            if (found.isEmpty()) {
                App.send(ex, 404, "text/plain", "no such loan\n");
                return;
            }
            Loan l = store.put(found.get().returned(LocalDate.now()));
            App.send(ex, 200, "text/plain", line(l) + "\n");
        } else {
            App.send(ex, 405, "text/plain", "method not allowed\n");
        }
    }

    static String line(Loan l) {
        return String.join(";", l.id(), l.member(), l.isbn(), l.lentOn().toString(), l.dueOn().toString(),
                l.returnedOn() == null ? "" : l.returnedOn().toString());
    }

    static Map<String, String> form(String body) {
        Map<String, String> out = new HashMap<>();
        for (String pair : body.split("&")) {
            String[] kv = pair.split("=", 2);
            if (kv.length == 2) {
                out.put(URLDecoder.decode(kv[0], StandardCharsets.UTF_8), URLDecoder.decode(kv[1], StandardCharsets.UTF_8));
            }
        }
        return out;
    }
}
