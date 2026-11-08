package lib;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/** In-memory loans, seeded with three for characterization. */
public final class LoanStore {
    private final Map<String, Loan> loans = new LinkedHashMap<>();
    private int next = 4;

    public LoanStore() {
        put(new Loan("L1", "ana", "9780134685991", LocalDate.of(2026, 1, 2), null));
        put(new Loan("L2", "bo", "9780596007126", LocalDate.of(2026, 1, 10), LocalDate.of(2026, 1, 20)));
        put(new Loan("L3", "cy", "9781617294945", LocalDate.of(2025, 12, 1), LocalDate.of(2026, 1, 3)));
    }

    public synchronized Loan lend(String member, String isbn, LocalDate on) {
        return put(new Loan("L" + next++, member, isbn, on, null));
    }

    public synchronized Optional<Loan> find(String id) {
        return Optional.ofNullable(loans.get(id));
    }

    public synchronized List<Loan> all() {
        return new ArrayList<>(loans.values());
    }

    public synchronized Loan put(Loan loan) {
        loans.put(loan.id(), loan);
        return loan;
    }
}
