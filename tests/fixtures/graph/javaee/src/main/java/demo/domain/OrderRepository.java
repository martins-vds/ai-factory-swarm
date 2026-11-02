package demo.domain;

public interface OrderRepository {
    Order find(String id);
    void store(Order order);
}
