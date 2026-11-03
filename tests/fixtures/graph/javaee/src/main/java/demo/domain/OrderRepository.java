package demo.domain;

import java.util.List;

public interface OrderRepository {
    Order find(String id);
    void store(Order order, List<Customer> buyers);
}
