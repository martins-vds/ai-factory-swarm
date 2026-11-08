package lib;

import java.time.LocalDate;

/** A book lent to a member. Due 14 days after it was lent. */
public record Loan(String id, String member, String isbn, LocalDate lentOn, LocalDate returnedOn) {
    public static final int LOAN_DAYS = 14;

    public LocalDate dueOn() {
        return lentOn.plusDays(LOAN_DAYS);
    }

    public Loan returned(LocalDate on) {
        return new Loan(id, member, isbn, lentOn, on);
    }
}
