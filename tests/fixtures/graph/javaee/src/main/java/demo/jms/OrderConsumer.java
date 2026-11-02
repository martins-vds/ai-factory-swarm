package demo.jms;

import demo.domain.OrderRepository;
import javax.ejb.ActivationConfigProperty;
import javax.ejb.MessageDriven;
import javax.inject.Inject;

@MessageDriven(activationConfig = {
        @ActivationConfigProperty(propertyName = "destinationLookup", propertyValue = "java:app/jms/OrderQueue") })
public class OrderConsumer {
    @Inject
    private OrderRepository orderRepository;
}
