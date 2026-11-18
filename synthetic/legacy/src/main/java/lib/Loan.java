package lib;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.LocalDate;

/** A book lent to a member. Due 14 days after it was lent. */
@Entity
@Table(name = "LOAN")
public class Loan {
    public static final int LOAN_DAYS = 14;

    @Id
    @Column(name = "ID")
    private String id;
    @Column(name = "MEMBER", nullable = false)
    private String member;
    @Column(name = "ISBN", nullable = false)
    private String isbn;
    @Column(name = "LENT_ON", nullable = false)
    private LocalDate lentOn;
    @Column(name = "RETURNED_ON")
    private LocalDate returnedOn;

    protected Loan() {
    }

    public Loan(String id, String member, String isbn, LocalDate lentOn) {
        this.id = id;
        this.member = member;
        this.isbn = isbn;
        this.lentOn = lentOn;
    }

    public String getId() { return id; }
    public String getMember() { return member; }
    public String getIsbn() { return isbn; }
    public LocalDate getLentOn() { return lentOn; }
    public LocalDate getReturnedOn() { return returnedOn; }

    public LocalDate dueOn() {
        return lentOn.plusDays(LOAN_DAYS);
    }

    public void markReturned(LocalDate on) {
        returnedOn = on;
    }
}
