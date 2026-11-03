package demo.batch;

import demo.jms.Events;
import java.util.List;
import javax.inject.Inject;
import javax.inject.Named;

@Named("OrderLineWriter")
public class OrderLineWriter {
    @Inject
    private Events events;

    public void writeItems(List<Object> items) {
        events.orderReported("line");
    }
}
