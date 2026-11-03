package demo.infra;

import demo.domain.Customer;
import demo.domain.Order;
import demo.domain.OrderRepository;
import javax.persistence.EntityManager;
import javax.persistence.PersistenceContext;

public class JpaOrderRepository implements OrderRepository {
    @PersistenceContext
    private EntityManager entityManager;

    public Order find(String id) {
        // createQuery("Select x from Ignored x") in a comment must not count
        entityManager.createQuery("Select c from Customer c join c.orders o");
        return entityManager.createNamedQuery("Order.findAll", Order.class).getSingleResult();
    }

    public void store(Order order, java.util.List<Customer> buyers) {
        for (Customer buyer : buyers) {
            entityManager.persist(buyer);     // a for-each variable: still a write
        }
        entityManager.persist(order);
    }
}
