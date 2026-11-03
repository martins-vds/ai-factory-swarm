package demo.batch;

import javax.batch.runtime.BatchRuntime;
import javax.ejb.Schedule;
import javax.ejb.Stateless;

@Stateless
public class Nightly {
    @Schedule(minute = "*/2", hour = "*") // the comment says hourly
    public void run() {
        BatchRuntime.getJobOperator().start("OrderImportJob", null);
    }
}
