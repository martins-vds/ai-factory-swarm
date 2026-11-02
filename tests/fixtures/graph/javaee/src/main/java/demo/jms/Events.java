package demo.jms;

import javax.annotation.Resource;
import javax.jms.Queue;

public class Events {
    @Resource(lookup = "java:app/jms/OrderQueue")
    private Queue orderQueue;
}
