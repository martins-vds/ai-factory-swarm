package lib;

import jakarta.persistence.EntityManager;
import jakarta.persistence.EntityManagerFactory;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import java.util.function.Function;
import java.util.stream.Collectors;

/** Holds in the HOLD table, queued per book in the order they were placed. */
public final class HoldRepository {
    private final EntityManagerFactory emf;

    HoldRepository(EntityManagerFactory emf) {
        this.emf = emf;
    }

    public List<Hold> active(String isbn, LocalDate on) {
        return read(em -> em.createQuery("select h from Hold h order by h.seq", Hold.class).getResultList())
                .stream()
                .filter(h -> isbn == null || h.getIsbn().equals(isbn))
                .filter(h -> h.activeOn(on))
                .collect(Collectors.toList());
    }

    public long activeFor(String member, LocalDate on) {
        return active(null, on).stream().filter(h -> h.getMember().equals(member)).count();
    }

    public boolean holding(String member, String isbn, LocalDate on) {
        return active(isbn, on).stream().anyMatch(h -> h.getMember().equals(member));
    }

    public Optional<Hold> find(String id) {
        return read(em -> Optional.ofNullable(em.find(Hold.class, id)));
    }

    public Hold place(String member, String isbn, LocalDate on) {
        return write(em -> {
            long n = em.createQuery("select coalesce(max(h.seq), 0) from Hold h", Long.class).getSingleResult();
            Hold hold = new Hold(n + 1, member, isbn, on);
            em.persist(hold);
            return hold;
        });
    }

    public Optional<Hold> cancel(String id, LocalDate on) {
        return write(em -> {
            Hold hold = em.find(Hold.class, id);
            if (hold == null) {
                return Optional.empty();
            }
            hold.cancel(on);
            return Optional.of(em.merge(hold));
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
