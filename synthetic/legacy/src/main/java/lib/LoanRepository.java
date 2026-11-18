package lib;

import jakarta.persistence.EntityManager;
import jakarta.persistence.EntityManagerFactory;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import java.util.function.Function;

/** Loans in the LOAN table. */
public final class LoanRepository {
    private final EntityManagerFactory emf;

    LoanRepository(EntityManagerFactory emf) {
        this.emf = emf;
    }

    public List<Loan> all() {
        return read(em -> em.createQuery("select l from Loan l order by l.id", Loan.class).getResultList());
    }

    public Optional<Loan> find(String id) {
        return read(em -> Optional.ofNullable(em.find(Loan.class, id)));
    }

    public Loan lend(String member, String isbn, LocalDate on) {
        return write(em -> {
            long n = em.createQuery("select count(l) from Loan l", Long.class).getSingleResult();
            Loan loan = new Loan("L" + (n + 1), member, isbn, on);
            em.persist(loan);
            return loan;
        });
    }

    public Optional<Loan> markReturned(String id, LocalDate on) {
        return write(em -> {
            Loan loan = em.find(Loan.class, id);
            if (loan == null) {
                return Optional.empty();
            }
            loan.markReturned(on);
            return Optional.of(em.merge(loan));
        });
    }

    private <T> T read(Function<EntityManager, T> work) {
        EntityManager em = emf.createEntityManager();
        try {
            return work.apply(em);
        } finally {
            em.close();
        }
    }

    private <T> T write(Function<EntityManager, T> work) {
        EntityManager em = emf.createEntityManager();
        try {
            em.getTransaction().begin();
            T out = work.apply(em);
            em.getTransaction().commit();
            return out;
        } finally {
            if (em.getTransaction().isActive()) {
                em.getTransaction().rollback();
            }
            em.close();
        }
    }
}
