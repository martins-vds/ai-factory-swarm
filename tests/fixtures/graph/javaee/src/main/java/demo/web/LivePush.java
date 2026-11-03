package demo.web;

import demo.app.OrderChecked;
import demo.domain.Order;
import javax.enterprise.event.Observes;
import javax.websocket.server.ServerEndpoint;

@ServerEndpoint("/live")
public class LivePush {
    public void onOrderChecked(@Observes @OrderChecked Order order) {
    }
}
