// Export every table of a JDBC database in the afs-data-pipeline snapshot format (ADR-0032).
//
//   java -cp <driver.jar>:<classes> JdbcSnapshot <jdbc url> <out dir> [schema]
//   java JdbcSnapshot --selftest
//
// One <TABLE>.csv per table: UTF-8, RFC 4180 quoting, a header row of column names, NULL as \N,
// rows ordered by primary key (else by every column) so the file is stable. Timestamps are written as
// ISO 8601 without a zone (the mapping's defaults.timestamp_tz names it), dates as yyyy-MM-dd, decimals
// in plain notation, binary as hex prefixed with \x. Tables come from DatabaseMetaData (type TABLE),
// skipping the engine's system schemas. data_snapshot.py compiles and runs this, then writes manifest.json.
// Java 8 source, standard library only (JDBC); the driver jar is given on the class path.

import java.io.*;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;
import java.util.*;

public class JdbcSnapshot {
    static final String NULL = "\\N";
    static final Set<String> SYSTEM = new HashSet<>(Arrays.asList(
        "SYS", "SYSIBM", "SYSCAT", "SYSCS_DIAG", "SYSCS_UTIL", "SYSFUN", "SYSPROC", "SYSSTAT", "SQLJ", "NULLID",
        "INFORMATION_SCHEMA", "PG_CATALOG", "MYSQL", "PERFORMANCE_SCHEMA", "SYS_", "CTXSYS", "MDSYS", "XDB"));

    static String field(String v) {
        if (v == null) return NULL;
        boolean quote = v.isEmpty() || v.equals(NULL) || v.indexOf(',') >= 0 || v.indexOf('"') >= 0
            || v.indexOf('\n') >= 0 || v.indexOf('\r') >= 0;
        return quote ? "\"" + v.replace("\"", "\"\"") + "\"" : v;
    }

    static String text(Object o) throws SQLException {
        if (o == null) return null;
        if (o instanceof Timestamp) {
            java.time.LocalDateTime t = ((Timestamp) o).toLocalDateTime();
            String base = t.format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
            return t.getNano() == 0 ? base : base + String.format(".%09d", t.getNano()).replaceAll("0+$", "");
        }
        if (o instanceof java.sql.Date) return o.toString();
        if (o instanceof Time) return o.toString();
        if (o instanceof BigDecimal) return ((BigDecimal) o).toPlainString();
        if (o instanceof Boolean) return ((Boolean) o) ? "true" : "false";
        if (o instanceof byte[]) {
            StringBuilder b = new StringBuilder("\\x");
            for (byte x : (byte[]) o) b.append(String.format("%02x", x));
            return b.toString();
        }
        if (o instanceof Clob) { Clob c = (Clob) o; return c.getSubString(1, (int) c.length()); }
        if (o instanceof Blob) { Blob c = (Blob) o; return text(c.getBytes(1, (int) c.length())); }
        return o.toString();
    }

    static String line(List<String> values) {
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < values.size(); i++) {
            if (i > 0) b.append(',');
            b.append(field(values.get(i)));
        }
        return b.append('\n').toString();
    }

    static String q(Connection c, String name) throws SQLException {
        String s = c.getMetaData().getIdentifierQuoteString();
        s = (s == null || s.trim().isEmpty()) ? "\"" : s;
        return s + name + s;
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("--selftest")) { selftest(); return; }
        if (args.length < 2) { System.err.println("usage: JdbcSnapshot <jdbc url> <out dir> [schema]"); System.exit(2); }
        Path out = Paths.get(args[1]);
        Files.createDirectories(out);
        String only = args.length > 2 ? args[2] : null;
        try (Connection c = DriverManager.getConnection(args[0])) {
            DatabaseMetaData md = c.getMetaData();
            List<String[]> tables = new ArrayList<>();
            try (ResultSet rs = md.getTables(null, only, "%", new String[]{"TABLE"})) {
                while (rs.next()) {
                    String schema = rs.getString("TABLE_SCHEM"), table = rs.getString("TABLE_NAME");
                    if (only == null && schema != null && SYSTEM.contains(schema.toUpperCase())) continue;
                    tables.add(new String[]{schema, table});
                }
            }
            Set<String> names = new HashSet<>();
            for (String[] t : tables) {
                if (!names.add(t[1])) throw new IllegalStateException(
                    "table " + t[1] + " exists in more than one schema; give the schema as the third argument");
            }
            for (String[] t : tables) {
                List<String> key = new ArrayList<>();
                try (ResultSet rs = md.getPrimaryKeys(null, t[0], t[1])) {
                    SortedMap<Integer, String> seq = new TreeMap<>();
                    while (rs.next()) seq.put(rs.getInt("KEY_SEQ"), rs.getString("COLUMN_NAME"));
                    key.addAll(seq.values());
                }
                String from = (t[0] == null ? "" : q(c, t[0]) + ".") + q(c, t[1]);
                int rows = 0;
                try (Statement st = c.createStatement();
                     ResultSet probe = st.executeQuery("SELECT * FROM " + from + " WHERE 1 = 0")) {
                    ResultSetMetaData m = probe.getMetaData();
                    List<String> header = new ArrayList<>();
                    for (int i = 1; i <= m.getColumnCount(); i++) header.add(m.getColumnName(i));
                    List<String> order = key.isEmpty() ? header : key;
                    StringBuilder by = new StringBuilder();
                    for (String k : order) by.append(by.length() == 0 ? "" : ", ").append(q(c, k));
                    try (Writer w = new BufferedWriter(new OutputStreamWriter(
                             Files.newOutputStream(out.resolve(t[1] + ".csv")), StandardCharsets.UTF_8));
                         Statement s2 = c.createStatement();
                         ResultSet rs = s2.executeQuery("SELECT * FROM " + from + " ORDER BY " + by)) {
                        w.write(line(header));
                        while (rs.next()) {
                            List<String> v = new ArrayList<>();
                            for (int i = 1; i <= header.size(); i++) v.add(text(rs.getObject(i)));
                            w.write(line(v));
                            rows++;
                        }
                    }
                }
                System.out.println(t[1] + " " + rows);
            }
        }
    }

    static void check(boolean ok, String what) { if (!ok) throw new AssertionError(what); }

    static void selftest() throws Exception {
        check(field(null).equals("\\N"), "null is the marker");
        check(field("").equals("\"\""), "empty string is quoted, so it differs from NULL");
        check(field("\\N").equals("\"\\N\""), "a literal \\N is quoted");
        check(field("a,b").equals("\"a,b\""), "comma quoted");
        check(field("say \"hi\"").equals("\"say \"\"hi\"\"\""), "quotes doubled");
        check(field("two\nlines").equals("\"two\nlines\""), "newline quoted");
        check(text(Timestamp.valueOf("2026-03-01 10:15:00.0")).equals("2026-03-01 10:15:00"), "timestamp keeps seconds");
        check(text(Timestamp.valueOf("2026-03-01 10:15:00.25")).equals("2026-03-01 10:15:00.25"), "fraction kept");
        check(text(new BigDecimal("1E+3")).equals("1000"), "plain decimal");
        check(text(new byte[]{1, (byte) 0xab}).equals("\\x01ab"), "binary hex");
        check(line(Arrays.asList("1", null, "")).equals("1,\\N,\"\"\n"), "a row");
        System.out.println("selftest ok");
    }
}
