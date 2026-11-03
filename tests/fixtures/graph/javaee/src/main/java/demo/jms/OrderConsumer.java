package demo.jms;

import demo.domain.OrderRepository;
import javax.ejb.ActivationConfigProperty;
import javax.ejb.MessageDriven;
import javax.inject.Inject;
import javax.jms.Message;
import javax.jms.MessageListener;

@MessageDriven(activationConfig = {
        @ActivationConfigProperty(propertyName = "destinationLookup", propertyValue = "java:app/jms/OrderQueue") })
public class OrderConsumer implements MessageListener {
    @Inject
    private OrderRepository orderRepository;

    @Override
    public void onMessage(Message message) {
        orderRepository.find("id");
    }
}
