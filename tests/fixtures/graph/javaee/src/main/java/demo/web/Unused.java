package demo.web;

import javax.persistence.NamedQuery;

@NamedQuery(name = "x", query = "Select u from Unused u")
public class Unused {
}
