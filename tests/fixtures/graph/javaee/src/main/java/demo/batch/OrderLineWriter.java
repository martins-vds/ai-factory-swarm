package demo.batch;

import demo.jms.Events;
import javax.inject.Inject;
import javax.inject.Named;

@Named("OrderLineWriter")
public class OrderLineWriter {
    @Inject
    private Events events;
}
