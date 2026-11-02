package demo.web;

import demo.domain.OrderRepository;
import javax.inject.Inject;
import javax.inject.Named;

@Named("public.orders")
public class OrderView {
    @Inject
    private OrderRepository orderRepository;
}
