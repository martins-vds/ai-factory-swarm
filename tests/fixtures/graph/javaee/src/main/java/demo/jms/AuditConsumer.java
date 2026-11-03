package demo.jms;

import javax.ejb.ActivationConfigProperty;
import javax.ejb.MessageDriven;
import javax.jms.Message;
import javax.jms.MessageListener;

// Reads no data: a path through the audit queue must not reach a table.
@MessageDriven(activationConfig = {
        @ActivationConfigProperty(propertyName = "destinationLookup", propertyValue = "java:app/jms/AuditQueue") })
public class AuditConsumer implements MessageListener {
    @Override
    public void onMessage(Message message) {
        System.out.println(message);
    }
}
