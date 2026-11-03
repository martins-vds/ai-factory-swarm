package demo.app;

import demo.domain.Order;
import demo.domain.OrderRepository;
import javax.enterprise.event.Event;
import javax.inject.Inject;

public class OrderChecker {
    @Inject
    private OrderRepository orderRepository;
    @Inject
    @OrderChecked
    private Event<Order> orderChecked;

    public void check(Order order) {
        orderChecked.fire(order);
    }
}
