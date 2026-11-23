package lib;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.LocalDate;

/** A member waiting for a book that is out on loan. A hold lasts 30 days from the day it was placed. */
@Entity
@Table(name = "HOLD")
public class Hold {
    public static final int HOLD_DAYS = 30;

    @Id
    @Column(name = "ID")
    private String id;
    @Column(name = "SEQ", nullable = false)
    private long seq;
    @Column(name = "MEMBER", nullable = false)
    private String member;
    @Column(name = "ISBN", nullable = false)
    private String isbn;
    @Column(name = "PLACED_ON", nullable = false)
    private LocalDate placedOn;
    @Column(name = "CANCELLED_ON")
    private LocalDate cancelledOn;

    protected Hold() {
    }

    public Hold(long seq, String member, String isbn, LocalDate placedOn) {
        this.id = "H" + seq;
        this.seq = seq;
        this.member = member;
        this.isbn = isbn;
        this.placedOn = placedOn;
    }

    public String getId() { return id; }
    public long getSeq() { return seq; }
    public String getMember() { return member; }
    public String getIsbn() { return isbn; }
    public LocalDate getPlacedOn() { return placedOn; }
    public LocalDate getCancelledOn() { return cancelledOn; }

    public LocalDate expiresOn() {
        return placedOn.plusDays(HOLD_DAYS);
    }

    public boolean activeOn(LocalDate day) {
        return cancelledOn == null && !day.isAfter(expiresOn());
    }

    public void cancel(LocalDate on) {
        cancelledOn = on;
    }
}
