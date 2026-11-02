package demo.domain;

import javax.persistence.Entity;
import javax.persistence.NamedQuery;
import javax.persistence.Table;

@Entity
@Table(name = "orders")
@NamedQuery(name = "Order.findAll", query = "Select o from Order o")
public class Order {
}
