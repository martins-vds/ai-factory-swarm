package demo.jms;

import javax.annotation.Resource;
import javax.inject.Inject;
import javax.jms.JMSContext;
import javax.jms.Queue;

// One class, two queues, sent from two different methods (pilot: JmsApplicationEvents).
public class Events {
    @Resource(lookup = "java:app/jms/OrderQueue")
    private Queue orderQueue;
    @Resource(lookup = "java:app/jms/AuditQueue")
    private Queue auditQueue;
    @Inject
    private JMSContext context;

    public void orderReported(String id) {
        context.createProducer().send(orderQueue, id);
    }

    public void audited(String note) {
        context.createProducer().send(auditQueue, note);
    }
}
