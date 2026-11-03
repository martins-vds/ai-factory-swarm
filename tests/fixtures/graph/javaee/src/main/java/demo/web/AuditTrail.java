package demo.web;

import demo.domain.Customer;
import javax.enterprise.event.Observes;

// Observes a different event type: must not be triggered by OrderChecker.
public class AuditTrail {
    public void onCustomer(@Observes Customer customer) {
    }
}
